import json
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from research.goal1_evaluator.terminal_v2 import canonical_terminal_bytes,verify_terminal_v2
SHA="a"*64
BINDING={"reservation_id":"res-1","run_id":"run-1","arm":"LEARNED","challenge_id":"case-1","challenge_view_digest":SHA,"model_prompt_sha256":"b"*64,"model_identity":"qwen3:4b-instruct","model_artifact_sha256":"c"*64,"gateway_id":"gateway-1","invocation_id":"inv-1","claim_id":"claim-1"}
class ClaimAuthority:
 def __init__(self,mutation=None): self.mutation=mutation
 def verify_claim_evidence(self,*,expected_binding):
  result={**expected_binding,"status":"CLAIMED"}
  if self.mutation: self.mutation(result)
  return result
def payload(status="COMPLETED"):
 return {**BINDING,"status":status,"response_sha256":SHA if status=="COMPLETED" else None,"prompt_tokens":4 if status=="COMPLETED" else None,"output_tokens":2 if status=="COMPLETED" else None,"gateway_wall_ms":12 if status=="COMPLETED" else None,"backend_wall_ms":10 if status=="COMPLETED" else None,"key_id":"key-1","terminal_utc":"2026-10-24T00:00:00Z","model_identity_scope":"BACKEND_REPORTED_NOT_WEIGHT_ATTESTED" if status=="COMPLETED" else "UNKNOWN"}
def signed(fields,key):
 wire=canonical_terminal_bytes(fields); return wire,key.sign(wire)
def verify(wire,sig,key,fields,authority=None):
 pub=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
 return verify_terminal_v2(payload_bytes=wire,signature=sig,pinned_gateway_public_key=pub,expected_gateway_id="gateway-1",expected_key_id="key-1",expected_binding={k:fields[k] for k in BINDING},claim_evidence_verifier=authority or ClaimAuthority())
def test_completed_v2_binds_claim_and_preserves_exact_signed_bytes():
 key=Ed25519PrivateKey.generate(); fields=payload(); wire,sig=signed(fields,key); result=verify(wire,sig,key,fields)
 assert result["status"]=="VERIFIED_COMPLETED" and result["score_eligible"]
 assert not result["automatic_retry_permitted"] and result["payload_sha256"]
def test_outcome_unknown_is_terminal_but_never_prediction_or_score():
 key=Ed25519PrivateKey.generate(); fields=payload("OUTCOME_UNKNOWN"); wire,sig=signed(fields,key); result=verify(wire,sig,key,fields)
 assert result["status"]=="VERIFIED_OUTCOME_UNKNOWN" and result["prediction"] is None
 assert not result["score_eligible"] and not result["automatic_retry_permitted"] and result["reservation_consumed"]
def test_unknown_with_response_or_usage_is_rejected():
 key=Ed25519PrivateKey.generate(); fields=payload("OUTCOME_UNKNOWN"); fields["output_tokens"]=1; wire,sig=signed(fields,key)
 with pytest.raises(ValueError,match="must not assert"): verify(wire,sig,key,fields)
@pytest.mark.parametrize("field,value",[("claim_id","other-claim"),("reservation_id","other-res"),("run_id","other-run"),("arm","FROZEN"),("challenge_id","other-case"),("challenge_view_digest","d"*64),("model_prompt_sha256","e"*64),("model_identity","other-model"),("model_artifact_sha256","f"*64),("gateway_id","other-gateway"),("invocation_id","other-inv")])
def test_signed_substitution_rejected(field,value):
 key=Ed25519PrivateKey.generate(); fields=payload(); wire,sig=signed(fields,key); changed=json.loads(wire); changed[field]=value
 with pytest.raises(ValueError): verify(canonical_terminal_bytes(changed),sig,key,fields)
def test_changed_wire_bytes_and_noncanonical_json_rejected():
 key=Ed25519PrivateKey.generate(); fields=payload(); wire,sig=signed(fields,key)
 with pytest.raises(ValueError,match="not canonical or were transformed"): verify(wire+b" ",sig,key,fields)
 with pytest.raises(ValueError,match="not canonical"): verify(json.dumps(fields,indent=2).encode(),sig,key,fields)
def test_wrong_gateway_and_claim_binding_fail_closed():
 key=Ed25519PrivateKey.generate(); fields=payload(); wire,sig=signed(fields,key); pub=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
 with pytest.raises(ValueError,match="identity mismatch"):
  verify_terminal_v2(payload_bytes=wire,signature=sig,pinned_gateway_public_key=pub,expected_gateway_id="wrong",expected_key_id="key-1",expected_binding={k:fields[k] for k in BINDING},claim_evidence_verifier=ClaimAuthority())
 authority=ClaimAuthority(lambda r:r.update(claim_id="substituted"))
 with pytest.raises(ValueError,match="claim does not bind"): verify(wire,sig,key,fields,authority)
