"""Signed-terminal gate before returning generated text to networkless QVR.

These are bounded mock-boundary tests. A separate physical probe must stage
exact PR95 GatewayDispatch and PR87 verify_terminal_v2 source.
"""
from __future__ import annotations
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from research.goal1_acceptance_bridge.gateway_terminal_text_bridge import (
    CapturingBackend, GatewayTerminalTextBridge, GatewayTextHold,
)

SHA=lambda value:sha256(value.encode("utf-8")).hexdigest()
PROMPT="synthetic bridge test"
MODEL="synthetic-model"
DIGEST=SHA("reported tag only")
MISMATCH_DIGEST=SHA("substituted registry digest")
RESERVATION={
    "reservation_id":"res-test","run_id":"run-test","arm":"FROZEN",
    "challenge_id":"case-test","challenge_view_digest":SHA("view"),
    "model_prompt_sha256":SHA(PROMPT),"model_identity":MODEL,
    "model_artifact_sha256":SHA("not a weight attestation"),
}
INVOCATION="inv-test"
GATEWAY="test-gateway"

def build(*,bad_sha=False,unknown=False,unverified=False,
          expected_registry_digest=DIGEST,expected_artifact_sha256=None):
    call_log=[]
    class Backend:
        def generate(self,prompt,*,model,max_tokens):
            call_log.append("backend")
            return SimpleNamespace(text="SYNTHETIC OUTPUT",model=model)
    capture=CapturingBackend(Backend())
    payload={**RESERVATION,"gateway_id":GATEWAY,"invocation_id":INVOCATION,
             "claim_id":"claim-test","status":"OUTCOME_UNKNOWN" if unknown else "COMPLETED",
             "response_sha256":None if unknown else (
                 "0"*64 if bad_sha else SHA("SYNTHETIC OUTPUT"))}
    wire=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
    sig=b"disposable-test-signature"
    class Dispatch:
        backend=capture
        gateway_id=GATEWAY
        def execute(self,*,reservation,invocation_id,prompt,max_tokens):
            assert invocation_id==INVOCATION and reservation==RESERVATION
            capture.generate(prompt,model=MODEL,max_tokens=max_tokens)
            call_log.append("dispatch")
            return payload,sig
    class Store:
        def signed_terminal(self,invocation_id):
            assert invocation_id==INVOCATION
            call_log.append("cold-terminal-readback")
            return SimpleNamespace(status=payload["status"],payload_bytes=wire,
                signature=sig,payload_sha256=sha256(wire).hexdigest(),
                qualified=False,independent_claim_verified=False)
    def verifier(**k):
        call_log.append("verify-v2")
        assert k["payload_bytes"]==wire and k["signature"]==sig
        assert k["expected_binding"]=={**RESERVATION,"gateway_id":GATEWAY,
                                      "invocation_id":INVOCATION,"claim_id":"claim-test"}
        if unverified: raise ValueError("independent claim evidence unavailable")
        return {"status":"VERIFIED_OUTCOME_UNKNOWN" if unknown else "VERIFIED_COMPLETED",
                "qualified":False,"automatic_retry_permitted":False,
                "payload_sha256":sha256(wire).hexdigest(),"payload":payload}
    class ClaimEvidence:
        def verify_claim_evidence(self, *, expected_binding):
            return {**expected_binding, "status":"CLAIMED"}
    bridge=GatewayTerminalTextBridge(
        dispatch=Dispatch(),backend=capture,store=Store(),
        reservation=RESERVATION,invocation_id=INVOCATION,
        verify_terminal_v2=verifier,
        claim_evidence_verifier=ClaimEvidence(),
        pinned_gateway_public_key=b"pinned-only-test",
        expected_gateway_id=GATEWAY,expected_key_id="test-key",
        expected_reported_registry_digest=expected_registry_digest,
        expected_model_artifact_sha256=(expected_artifact_sha256
            if expected_artifact_sha256 is not None
            else RESERVATION["model_artifact_sha256"]))
    return bridge,call_log

def test_signed_terminal_and_claim_verification_precede_qvr_text():
    bridge,calls=build()
    receipt=bridge(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)
    assert receipt=={"kind":"GATEWAY_RESPONSE","text":"SYNTHETIC OUTPUT",
        "model":MODEL,"model_digest":DIGEST,
        "prompt_sha256":SHA(PROMPT),"response_sha256":SHA("SYNTHETIC OUTPUT")}
    assert calls==["backend","dispatch","cold-terminal-readback","verify-v2"]

@pytest.mark.parametrize("kwargs",[
    {"bad_sha":True},{"unknown":True},{"unverified":True},
])
def test_no_qvr_text_if_signed_terminal_cannot_authorize_it(kwargs):
    bridge,_=build(**kwargs)
    with pytest.raises(GatewayTextHold):
        bridge(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)

def test_mismatched_reservation_rejected_before_backend():
    bridge,calls=build()
    with pytest.raises(GatewayTextHold):
        bridge("substituted prompt",model=MODEL,model_digest=DIGEST,max_tokens=3)
    assert calls==[]

def test_registry_digest_must_match_its_own_pinned_identity_before_any_dispatch():
    bridge,calls=build()
    assert MISMATCH_DIGEST != RESERVATION["model_artifact_sha256"]
    assert DIGEST != RESERVATION["model_artifact_sha256"]
    with pytest.raises(GatewayTextHold,match="model/prompt/permit mismatch"):
        bridge(PROMPT,model=MODEL,model_digest=MISMATCH_DIGEST,max_tokens=3)
    assert calls==[]
    # The attempt is consumed before dispatch; a subsequent correct digest
    # must never replay the same invocation.
    with pytest.raises(GatewayTextHold,match="already consumed"):
        bridge(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)
    assert calls==[]

def test_artifact_sha_is_independently_bound_before_any_dispatch():
    with pytest.raises(ValueError,match="artifact"):
        build(expected_artifact_sha256=SHA("other selected artifact"))

def test_unpinned_registry_and_artifact_identities_are_refused_at_init():
    for registry,artifact in (("not-a-digest",RESERVATION["model_artifact_sha256"]),
                              (DIGEST,"not-a-digest")):
        with pytest.raises(ValueError,match="identities/trust inputs"):
            build(expected_registry_digest=registry,
                  expected_artifact_sha256=artifact)

def test_one_shot_no_automatic_replay_after_success_or_failure():
    bridge,calls=build()
    bridge(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)
    with pytest.raises(GatewayTextHold):
        bridge(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)
    assert calls.count("backend")==1
    failed,_=build(unverified=True)
    with pytest.raises(GatewayTextHold):
        failed(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)
    with pytest.raises(GatewayTextHold):
        failed(PROMPT,model=MODEL,model_digest=DIGEST,max_tokens=3)

def test_plain_object_cannot_masquerade_as_claim_evidence_verifier():
    bridge,_=build()
    with pytest.raises(ValueError,match="gateway composition"):
        GatewayTerminalTextBridge(
            dispatch=bridge.dispatch,backend=bridge.backend,store=bridge.store,
            reservation=RESERVATION,invocation_id=INVOCATION,
            verify_terminal_v2=bridge.verify_terminal_v2,
            claim_evidence_verifier=object(),
            pinned_gateway_public_key=b"pinned-only-test",
            expected_gateway_id=GATEWAY,expected_key_id="test-key",
            expected_reported_registry_digest=DIGEST,
            expected_model_artifact_sha256=RESERVATION["model_artifact_sha256"])
