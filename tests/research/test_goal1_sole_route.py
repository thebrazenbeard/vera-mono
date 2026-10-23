from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research.goal1_gateway.sole_route import (
    GatewayAttemptStore, GatewayDispatch, GatewayHold, ModelObservation,
    verify_terminal,
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_reservation(prompt="test prompt", run="run1", arm="FROZEN", case="case1"):
    return dict(reservation_id="res-"+run+arm+case,run_id=run,arm=arm,
        challenge_id=case,challenge_view_digest=sha(b"view"),
        model_prompt_sha256=sha(prompt.encode()), model_identity="qwen3:4b-instruct",
        model_artifact_sha256=sha(b"placeholder-model-unattested"))


class Endpoint:
    def __init__(self):
        self.calls=0
        self.mode="good"
    def claim_reservation(self, *, reservation, gateway_id, invocation_id):
        self.calls+=1
        if self.mode == "timeout":
            raise TimeoutError("remote ambiguous")
        result = {**reservation,"gateway_id":gateway_id,"invocation_id":invocation_id,
                  "status":"CLAIMED","claim_id":"claim-"+invocation_id}
        if self.mode=="mutate":result["model_artifact_sha256"]="0"*64
        if self.mode=="denied":result["status"]="DENIED"
        return result


def helper(client, *, reservation, gateway_id, invocation_id):
    result=client.claim_reservation(reservation=reservation,gateway_id=gateway_id,
                                    invocation_id=invocation_id)
    expected={**reservation,"gateway_id":gateway_id,"invocation_id":invocation_id,
              "status":"CLAIMED"}
    if type(result) is not dict or frozenset(result)!=frozenset((*expected,"claim_id")) or any(result[k]!=v for k,v in expected.items()):
        raise ValueError("claim mismatch")
    return result


class Backend:
    def __init__(self):
        self.calls=0
        self.fail=False
    def generate(self,prompt, *, model, max_tokens):
        self.calls+=1
        if self.fail:raise TimeoutError("provider may have consumed tokens")
        return ModelObservation(text="OK",model=model,prompt_tokens=3,output_tokens=2,backend_wall_ms=17)


class Signer:
    key_id="fake-lab-key"
    def __init__(self):self.key=Ed25519PrivateKey.generate()
    def sign(self,message):return self.key.sign(message)
    def public(self):return self.key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="goal1-sole-route-")
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"gateway.sqlite"
        self.store=GatewayAttemptStore(self.path)
        self.endpoint=Endpoint()
        self.backend=Backend()
        self.signer=Signer()
        self.gate=GatewayDispatch(store=self.store,gateway_id="gateway1",
            endpoint_client=self.endpoint,claim_authorization=helper,
            backend=self.backend,signer=self.signer)
        self.res=fixture_reservation()

    def test_positive_claim_precedes_model_and_signs_measured_terminal(self):
        payload,sig=self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.endpoint.calls,1)
        self.assertEqual(self.backend.calls,1)
        self.assertEqual(self.store.history()[0]["status"],"COMPLETED")
        self.assertEqual(payload["response_sha256"],sha(b"OK"))
        self.assertEqual((payload["prompt_tokens"],payload["output_tokens"],payload["backend_wall_ms"]),(3,2,17))
        self.assertTrue(verify_terminal(payload,sig,pinned_public_key=self.signer.public(),expected_key_id=self.signer.key_id))
        self.assertFalse(verify_terminal({**payload,"output_tokens":999},sig,pinned_public_key=self.signer.public(),expected_key_id=self.signer.key_id))
        self.assertFalse(verify_terminal(payload,sig,pinned_public_key=Signer().public(),expected_key_id=self.signer.key_id))
        reopened=GatewayAttemptStore(self.path)
        self.assertEqual(reopened.history()[0]["signature_hex"],sig.hex())
        self.assertFalse(reopened.recovery()[0]["automatic_retry_allowed"])

    def test_missing_reservation_claim_never_dispatches(self):
        self.endpoint.mode="denied"
        with self.assertRaises((ValueError,GatewayHold)):
            self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.backend.calls,0)
        self.assertEqual(self.store.history()[0]["status"],"RESERVED")
        with self.assertRaises(GatewayHold):
            self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.endpoint.calls,1)

    def test_remote_timeout_stays_nonretryable_and_no_model(self):
        self.endpoint.mode="timeout"
        with self.assertRaises(TimeoutError):
            self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.store.history()[0]["status"],"RESERVED")
        self.assertEqual(self.backend.calls,0)
        with self.assertRaises(GatewayHold):
            self.gate.execute(reservation=self.res,invocation_id="inv2",prompt="test prompt",max_tokens=2)

    def test_claim_binding_mutation_blocks_model(self):
        self.endpoint.mode="mutate"
        with self.assertRaises(ValueError):self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.backend.calls,0)

    def test_backend_timeout_produces_signed_unknown_and_never_retry(self):
        self.backend.fail=True
        with self.assertRaises(TimeoutError):self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        r=self.store.history()[0]
        self.assertEqual(r["status"],"OUTCOME_UNKNOWN")
        payload=json.loads(r["terminal_json"])
        self.assertTrue(verify_terminal(payload,bytes.fromhex(r["signature_hex"]),pinned_public_key=self.signer.public(),expected_key_id=self.signer.key_id))
        self.assertEqual(payload["output_tokens"],None)
        self.assertEqual(self.backend.calls,1)
        with self.assertRaises(GatewayHold):self.gate.execute(reservation=self.res,invocation_id="inv2",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.backend.calls,1)

    def test_prompt_mismatch_does_not_reserve_or_claim(self):
        with self.assertRaises(ValueError):self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="different",max_tokens=2)
        self.assertEqual(self.store.history(),[])
        self.assertEqual(self.endpoint.calls,0)
        self.assertEqual(self.backend.calls,0)

    def test_concurrent_duplicate_only_one_claim_and_model(self):
        def go(i):
            try:return self.gate.execute(reservation=self.res,invocation_id=f"inv{i}",prompt="test prompt",max_tokens=2)[0]["status"]
            except GatewayHold:return "HOLD"
        with ThreadPoolExecutor(max_workers=12) as pool:result=list(pool.map(go,range(12)))
        self.assertEqual(result.count("COMPLETED"),1)
        self.assertEqual(result.count("HOLD"),11)
        self.assertEqual(self.endpoint.calls,1)
        self.assertEqual(self.backend.calls,1)

    def test_local_journal_has_no_independent_witness_pretence(self):
        self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertFalse(self.store.recovery()[0]["independently_attested"])

    def test_claim_response_exact_fields(self):
        self.endpoint.mode="mutate"
        with self.assertRaises(ValueError):self.gate.execute(reservation=self.res,invocation_id="inv1",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.backend.calls,0)

    def test_crash_after_claim_no_second_claim_on_reopen(self):
        # subprocess is an independent OS process sharing only test SQLite; model stub absent.
        script = '''import sys, os, json
from research.goal1_gateway.sole_route import GatewayAttemptStore
s=GatewayAttemptStore(sys.argv[1]); r=json.loads(sys.argv[2]);
s.reserve(r,"gateway1","inv-crash");s.claim("inv-crash","claim-crash");os._exit(17)
'''
        result=subprocess.run([sys.executable,"-c",script,str(self.path),json.dumps(self.res)],
                              cwd=str(Path(__file__).resolve().parents[2]),capture_output=True)
        self.assertEqual(result.returncode,17,result.stderr)
        reopened=GatewayAttemptStore(self.path)
        self.assertEqual(reopened.history()[0]["status"],"CLAIMED")
        self.assertFalse(reopened.recovery()[0]["automatic_retry_allowed"])
        with self.assertRaises(GatewayHold):self.gate.execute(reservation=self.res,invocation_id="inv-retry",prompt="test prompt",max_tokens=2)
        self.assertEqual(self.backend.calls,0)

if __name__=="__main__":unittest.main()
