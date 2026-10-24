"""Exact pinned PR95 GatewayDispatch + PR87 V2 -> FULL networkless QVR.

Three disposable physical cases: verified simulated COMPLETED, claim DENIED,
and signed OUTCOME_UNKNOWN. Uses ephemeral signer, fake same-process evaluator
and inert backend: NOT real model or independent claim custody.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy
import subprocess
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from research.goal1_acceptance_bridge.full_qvr_stdio_broker import (
    invoke_with_host_callback, cold_readback,
)
from research.goal1_acceptance_bridge.gateway_terminal_text_bridge import (
    CapturingBackend, GatewayTerminalTextBridge, GatewayTextHold,
)

PR95="7c191b2a97063ccc5821f3f274fb4f5e47ff99ed"
PR87="d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf"
SOURCES={
    "research/goal1_gateway/sole_route.py":(PR95,"ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d"),
    "research/goal1_evaluator/terminal_v2.py":(PR87,"153aed3f37e013f9c9d9d9?"),
}
# The authoritative V2 source digest is used rather than the Git blob ID.
SOURCES["research/goal1_evaluator/terminal_v2.py"]=(PR87,"153aed3f37e013f9cbb213af2539a1984bebf3086a1d77544d189e0c8104d187")
SOURCES["research/goal1_evaluator/reservation_status_contract.py"]=(PR87,"eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc")


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def load_sources(repo: Path, scratch: Path):
    result={}
    for path,(commit,expected) in SOURCES.items():
        try:
            raw=subprocess.check_output(["git","-C",str(repo),"show",commit+":"+path])
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("immutable PR95/PR87 source not fetched") from exc
        if digest(raw)!=expected:
            raise ValueError("immutable gateway/evaluator source pin mismatch: "+path)
        target=scratch/Path(path).name
        target.write_bytes(raw)
        result[path]=runpy.run_path(str(target))
    return result


def exercise(*, repo: Path, image_id: str, volume_prefix: str):
    from tempfile import TemporaryDirectory
    prompt="Real QVR, inert backend, V2-gated IPC"
    model="qwen3:4b-instruct"
    reported_digest="a"*64
    gateway_id="gateway-research-only"
    records=[]
    with TemporaryDirectory(prefix="goal1-full-qvr-gateway-") as td:
        root=Path(td)
        modules=load_sources(repo,root)
        gw=modules["research/goal1_gateway/sole_route.py"]
        v2=modules["research/goal1_evaluator/terminal_v2.py"]
        claim=modules["research/goal1_evaluator/reservation_status_contract.py"]
        for variant in ("completed","denied","unknown"):
            key=Ed25519PrivateKey.generate()
            public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
            class Signer:
                key_id="ephemeral-test-only"
                def sign(self, wire: bytes)->bytes:
                    return key.sign(wire)
            class Endpoint:
                calls=0
                def claim_reservation(self,*,reservation,gateway_id,invocation_id):
                    self.calls+=1
                    row={**reservation,"gateway_id":gateway_id,
                         "invocation_id":invocation_id,"status":"CLAIMED",
                         "claim_id":"claim-"+invocation_id}
                    if variant=="denied":
                        row["gateway_id"]="WRONG-GATEWAY"
                    return row
            class Backend:
                calls=0
                def generate(self,text,*,model,max_tokens):
                    self.calls+=1
                    if variant=="unknown":
                        raise TimeoutError("simulated outcome unknown, do not replay")
                    return gw["ModelObservation"](
                        text="GATEWAY CONTROLLED INERT RESULT",model=model,
                        prompt_tokens=2,output_tokens=1,backend_wall_ms=0)
            class SimulatedClaimCustody:
                calls=0
                def verify_claim_evidence(self,*,expected_binding):
                    self.calls+=1
                    return {**expected_binding,"status":"CLAIMED"}
            class ActualV2Witness:
                calls=0
                def __call__(self,**kwargs):
                    self.calls+=1
                    return v2["verify_terminal_v2"](**kwargs)
            inv="full-qvr-v2-"+variant
            reservation={
                "reservation_id":"reservation-"+variant,
                "run_id":"run-"+variant,"arm":"FROZEN",
                "challenge_id":"challenge-"+variant,
                "challenge_view_digest":digest(("view-"+variant).encode()),
                "model_prompt_sha256":digest(prompt.encode()),
                "model_identity":model,
                "model_artifact_sha256":digest(b"not-real-weight-attestation"),
            }
            endpoint,backend,claim_custody,witness=(
                Endpoint(),Backend(),SimulatedClaimCustody(),ActualV2Witness())
            capture=CapturingBackend(backend)
            store=gw["GatewayAttemptStore"](root/("gateway-"+variant+".sqlite"))
            dispatch=gw["GatewayDispatch"](
                store=store,gateway_id=gateway_id,endpoint_client=endpoint,
                claim_authorization=claim["claim_dispatch_authorization"],
                backend=capture,signer=Signer())
            callback=GatewayTerminalTextBridge(
                dispatch=dispatch,backend=capture,store=store,
                reservation=reservation,invocation_id=inv,
                verify_terminal_v2=witness,
                claim_evidence_verifier=claim_custody,
                pinned_gateway_public_key=public,
                expected_gateway_id=gateway_id,
                expected_key_id="ephemeral-test-only")
            volume=volume_prefix+"-"+variant
            result=None
            try:
                result=invoke_with_host_callback(
                    image_id=image_id,volume=volume,prompt=prompt,
                    model=model,digest=reported_digest,invocation_id=inv,
                    callback=callback,max_tokens=3)
            except GatewayTextHold:
                if variant=="completed":
                    raise
            else:
                if variant!="completed":
                    raise AssertionError("denied/unknown gateway produced QVR text")
            history=cold_readback(image_id=image_id,volume=volume)
            gateway_state=gw["GatewayAttemptStore"](root/("gateway-"+variant+".sqlite")).history()
            if len(gateway_state)!=1 or endpoint.calls!=1:
                raise AssertionError("gateway never reserved exactly once")
            if variant=="completed":
                assert result["kind"]=="INVOKE_RESULT"
                assert result["journal_entries"]==1
                assert history["invocation_ids"]==[inv]
                assert gateway_state[0]["status"]=="COMPLETED"
                assert backend.calls==1 and witness.calls==1 and claim_custody.calls==1
                persisted=gw["GatewayAttemptStore"](root/("gateway-"+variant+".sqlite")).signed_terminal(inv)
                assert persisted.payload_sha256==digest(persisted.payload_bytes)
                assert persisted.qualified is False
                assert result["response_sha256"]==json.loads(persisted.payload_bytes)["response_sha256"]
            else:
                assert history["entries"]==0
                if variant=="denied":
                    assert gateway_state[0]["status"]=="RESERVED"
                    assert backend.calls==0 and witness.calls==0
                else:
                    assert gateway_state[0]["status"]=="OUTCOME_UNKNOWN"
                    assert backend.calls==1 and witness.calls==0
            records.append({"case":variant,"gateway_state":gateway_state[0]["status"],
                            "qvr_journal_entries":history["entries"],
                            "fake_backend_calls":backend.calls,
                            "actual_v2_verifier_calls":witness.calls,
                            "qualified":False})
    return {"schema":"GOAL1_FULL_QVR_GATEWAY_V2_PHYSICAL_V1",
            "source_shas":{k:v[1] for k,v in SOURCES.items()},
            "cases":records,"image_id":image_id,
            "real_model_called":False,
            "independent_claim_custody":False,
            "selected_production_route":False,
            "learning_qualified":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--image-id",required=True)
    parser.add_argument("--volume-prefix",required=True)
    args=parser.parse_args()
    print(json.dumps(exercise(repo=args.repo,image_id=args.image_id,
                              volume_prefix=args.volume_prefix),sort_keys=True))
