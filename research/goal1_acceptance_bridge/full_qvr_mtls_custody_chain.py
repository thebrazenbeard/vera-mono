"""Real #95 mTLS claim + signed #87 V2 + full contained PR82 QVR.

All three real source contracts execute; backend is inert, evaluator/server TLS
and keys are disposable SAME-OPERATOR test fixtures. DO NOT qualify independence.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

from research.goal1_acceptance_bridge.physical_mtls_pr95_pr87_probe import pinned
from research.goal1_acceptance_bridge.gateway_terminal_text_bridge import (
    CapturingBackend, GatewayTerminalTextBridge,
)
from research.goal1_acceptance_bridge.full_qvr_stdio_broker import (
    invoke_with_host_callback,cold_readback,
)
from tests.research.test_goal1_evaluator_mtls_custody import LoopbackCustody,BIND

def exercise(repo:Path,image_id:str,volume:str)->dict:
    gw=pinned(repo,"research/goal1_gateway/sole_route.py")
    cl=pinned(repo,"research/goal1_gateway/authenticated_claim_client.py")
    h=pinned(repo,"research/goal1_evaluator/reservation_status_contract.py")
    v2=pinned(repo,"research/goal1_evaluator/terminal_v2.py")
    fixture=LoopbackCustody("test_real_mtls_claim_cold_signed_readback")
    fixture.setUp()
    try:
        endpoint=cl["AuthenticatedReservationClaimClient"](
            endpoint_url=fixture.base+"/v1/reservations/claim",
            ca_bundle=fixture.root/"ca.pem",client_certificate=fixture.root/"gateway.pem",
            client_private_key=fixture.root/"gateway.key",timeout_seconds=3)
        signer_key=Ed25519PrivateKey.generate()
        public=signer_key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        class Signer:
            key_id="ephemeral-gateway-test"
            def sign(self,data):return signer_key.sign(data)
        class Backend:
            calls=0
            def generate(self,prompt,*,model,max_tokens):
                self.calls+=1
                return gw["ModelObservation"](
                    text="INERT EXTERNAL CUSTODY RESEARCH",model=model,
                    prompt_tokens=2,output_tokens=3,backend_wall_ms=0)
        delegate=Backend()
        capture=CapturingBackend(delegate)
        with TemporaryDirectory(prefix="goal1-entire-qvr-mtls-") as td:
            gateway_db=Path(td)/"gateway.sqlite"
            store=gw["GatewayAttemptStore"](gateway_db)
            dispatcher=gw["GatewayDispatch"](
                store=store,gateway_id="gateway-test",
                endpoint_client=endpoint,
                claim_authorization=h["claim_dispatch_authorization"],
                backend=capture,signer=Signer())
            bridge=GatewayTerminalTextBridge(
                dispatch=dispatcher,backend=capture,store=store,
                reservation=dict(BIND),invocation_id="inv-mtls",
                verify_terminal_v2=v2["verify_terminal_v2"],
                claim_evidence_verifier=fixture.reader(),
                pinned_gateway_public_key=public,
                expected_gateway_id="gateway-test",
                expected_key_id="ephemeral-gateway-test")
            response=invoke_with_host_callback(
                image_id=image_id,volume=volume,prompt="prompt",model="synthetic",
                digest="a"*64,invocation_id="inv-mtls",
                callback=bridge,max_tokens=4)
            cold=cold_readback(image_id=image_id,volume=volume)
            assert response["kind"]=="INVOKE_RESULT"
            assert response["qualified"] is False
            assert cold["entries"]==1
            assert cold["invocation_ids"]==["inv-mtls"]
            terminal=gw["GatewayAttemptStore"](gateway_db).signed_terminal("inv-mtls")
            parsed=json.loads(terminal.payload_bytes)
            assert parsed["status"]=="COMPLETED"
            assert response["response_sha256"]==parsed["response_sha256"]
            assert delegate.calls==1
            assert fixture.ledger.reservation_status("res-mtls")=="CLAIMED"
            return {
                "schema":"GOAL1_FULL_QVR_MTLS_CUSTODY_CHAIN_V1",
                "full_qvr_process_in_networkless_docker":True,
                "real_pr95_mtls_gateway_client":True,
                "real_pr95_gateway_dispatch":True,
                "real_pr87_claim_helper":True,
                "real_pr87_v2_original_wire":True,
                "evaluator_held_original_signed_claim_over_mtls":True,
                "qvr_cold_journal_entries":cold["entries"],
                "simulated_backend_calls":delegate.calls,
                "gateway_terminal_sha256":sha256(terminal.payload_bytes).hexdigest(),
                "independent_operator":False,
                "authenticated_production_identity":False,
                "actual_selected_service":False,
                "real_model_invoked":False,
                "learning_qualified":False,
            }
    finally:
        fixture.doCleanups()

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--repo",type=Path,required=True)
    p.add_argument("--image-id",required=True)
    p.add_argument("--volume",required=True)
    a=p.parse_args()
    print(json.dumps(exercise(a.repo,a.image_id,a.volume),sort_keys=True))
