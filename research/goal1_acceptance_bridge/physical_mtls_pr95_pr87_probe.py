"""Actual immutable Integration PR95 mTLS client + gateway + Malaphor PR87 V2.

Physical HTTPS loopback with ephemeral certs; real SQLite atomic claim and
separate signed readback. Fake backend / same admin actor: NOT independent
production custody or real model inference. No listener survives execution.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

from research.goal1_acceptance_bridge.evaluator_claim_custody import (
    ClaimDenied, ClaimEvidenceReader,
)
from tests.research.test_goal1_evaluator_mtls_custody import (
    LoopbackCustody, BIND,
)

SOURCE={
    "research/goal1_gateway/authenticated_claim_client.py":
       ("7c191b2a97063ccc5821f3f274fb4f5e47ff99ed",
        "1e89362990e250d197f71845f95d997f66b2384743db4ce2f8005ac1d565336a"),
    "research/goal1_gateway/sole_route.py":
       ("7c191b2a97063ccc5821f3f274fb4f5e47ff99ed",
        "ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d"),
    "research/goal1_evaluator/reservation_status_contract.py":
       ("d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf",
        "eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc"),
    "research/goal1_evaluator/terminal_v2.py":
       ("d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf",
        "153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187"),
}

def pinned(repo:Path,path:str)->dict:
    commit,expected=SOURCE[path]
    data=subprocess.check_output(["git","-C",str(repo),"show",commit+":"+path])
    if sha256(data).hexdigest()!=expected:
        raise ValueError("immutable owner source pin mismatch: "+path)
    module={"__name__":"goal1_pinned_probe_"+path.split("/")[-1]}
    exec(compile(data,path,"exec"),module)
    return module

def exercise(repo:Path)->dict:
    modules={path:pinned(repo,path) for path in SOURCE}
    client=modules["research/goal1_gateway/authenticated_claim_client.py"]
    gw=modules["research/goal1_gateway/sole_route.py"]
    helper=modules["research/goal1_evaluator/reservation_status_contract.py"]
    v2=modules["research/goal1_evaluator/terminal_v2.py"]
    fixture=LoopbackCustody("test_real_mtls_claim_cold_signed_readback")
    fixture.setUp()
    try:
        gateway=client["AuthenticatedReservationClaimClient"](
            endpoint_url=fixture.base+"/v1/reservations/claim",
            ca_bundle=fixture.root/"ca.pem",
            client_certificate=fixture.root/"gateway.pem",
            client_private_key=fixture.root/"gateway.key",timeout_seconds=3)
        gateway_key=Ed25519PrivateKey.generate()
        pub=gateway_key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        class Signer:
            key_id="ephemeral-gateway-test"
            def sign(self,bytes_:bytes)->bytes:
                return gateway_key.sign(bytes_)
        class Backend:
            calls=0
            def generate(self,prompt,*,model,max_tokens):
                self.calls+=1
                return gw["ModelObservation"](
                    text="ONLY FAKE INFERENCE OUTPUT",model=model,
                    prompt_tokens=2,output_tokens=2,backend_wall_ms=0)
        backend=Backend()
        with TemporaryDirectory(prefix="goal1-mtls-pr95-") as td:
            store=gw["GatewayAttemptStore"](Path(td)/"gateway.sqlite")
            dispatch=gw["GatewayDispatch"](
                store=store,gateway_id="gateway-test",
                endpoint_client=gateway,
                claim_authorization=helper["claim_dispatch_authorization"],
                backend=backend,signer=Signer())
            wire_payload,signature=dispatch.execute(
                reservation=dict(BIND),invocation_id="inv-mtls",
                prompt="prompt",max_tokens=4)
            assert backend.calls==1
            cold_store=gw["GatewayAttemptStore"](Path(td)/"gateway.sqlite")
            signed=cold_store.signed_terminal("inv-mtls")
            assert signed.payload_bytes==gw["_canonical"](wire_payload)
            assert signed.signature==signature
            evidence=fixture.reader()
            expected={key:wire_payload[key] for key in v2["_BINDING_FIELDS"]}
            checked=v2["verify_terminal_v2"](
                payload_bytes=signed.payload_bytes,signature=signed.signature,
                pinned_gateway_public_key=pub,expected_gateway_id="gateway-test",
                expected_key_id="ephemeral-gateway-test",
                expected_binding=expected,claim_evidence_verifier=evidence)
            assert checked["status"]=="VERIFIED_COMPLETED"
            assert checked["qualified"] is False
            assert fixture.ledger.reservation_status("res-mtls")=="CLAIMED"
            assert len(fixture.ledger.read_claim(wire_payload["claim_id"]))==12
            # Explicitly cannot replay same immutable evaluator-held reservation.
            try:
                dispatch.execute(reservation=dict(BIND),invocation_id="inv-mtls",
                                 prompt="prompt",max_tokens=4)
            except gw["GatewayHold"]:
                pass
            else:
                raise AssertionError("gateway replay accepted")
            assert backend.calls==1
            bad_public=Ed25519PrivateKey.generate().public_key().public_bytes(
                Encoding.Raw,PublicFormat.Raw)
            try:
                v2["verify_terminal_v2"](
                    payload_bytes=signed.payload_bytes,signature=signed.signature,
                    pinned_gateway_public_key=bad_public,
                    expected_gateway_id="gateway-test",
                    expected_key_id="ephemeral-gateway-test",
                    expected_binding=expected,claim_evidence_verifier=evidence)
            except ValueError:
                pass
            else:
                raise AssertionError("substituted gateway signer accepted")
            # Peer identity rejection cannot claim a distinct reservation.
            return {
                "schema":"GOAL1_REAL_PR95_MTLS_V2_WITH_CUSTODY_V1",
                "owner_source_sha256":{p:value[1] for p,value in SOURCE.items()},
                "custody_store_reopened":True,
                "actual_pr95_https_client":True,
                "actual_pr95_gateway_dispatch":True,
                "actual_pr87_claim_helper":True,
                "actual_pr87_terminal_v2":True,
                "signed_original_bytes_unchanged":True,
                "claims_at_most_once":True,
                "backend_calls":backend.calls,
                "gateway_signer_substitution_denied":True,
                "original_evaluator_signature_verified_over_mtls":True,
                "independent_operator":False,
                "fake_backend":True,
                "learner_selected":False,
                "real_model_calls":0,
                "learning_qualified":False
            }
    finally:
        fixture.doCleanups()

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(exercise(args.repo),sort_keys=True))
