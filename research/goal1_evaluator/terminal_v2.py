"""Canonical Goal 1 terminal V2 verifier; source-only, fail-closed contract."""
from __future__ import annotations
import hashlib, json, re
from typing import Protocol, Any
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
_SHA = re.compile(r"^[0-9a-f]{64}$")
_BASE_FIELDS = frozenset({"reservation_id","run_id","arm","challenge_id","challenge_view_digest","model_prompt_sha256","model_identity","model_artifact_sha256","gateway_id","invocation_id","claim_id","status","response_sha256","prompt_tokens","output_tokens","gateway_wall_ms","backend_wall_ms","key_id","terminal_utc","model_identity_scope"})
_BINDING_FIELDS = ("reservation_id","run_id","arm","challenge_id","challenge_view_digest","model_prompt_sha256","model_identity","model_artifact_sha256","gateway_id","invocation_id","claim_id")
def canonical_terminal_bytes(payload: dict[str, Any]) -> bytes:
 return json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
class IndependentClaimEvidenceVerifier(Protocol):
 """Must fetch and verify signed claim evidence from separately trusted custody."""
 def verify_claim_evidence(self, *, expected_binding: dict[str,str]) -> dict[str,str]: ...
def _sha(value: object,name: str) -> None:
 if type(value) is not str or _SHA.fullmatch(value) is None: raise ValueError(f"{name} must be lowercase SHA-256")
def _text(value: object,name: str) -> None:
 if type(value) is not str or not value.strip(): raise ValueError(f"{name} must be non-empty text")
def verify_terminal_v2(*,payload_bytes: bytes,signature: bytes,pinned_gateway_public_key: bytes,expected_gateway_id: str,expected_key_id: str,expected_binding: dict[str,str],claim_evidence_verifier: IndependentClaimEvidenceVerifier) -> dict[str,Any]:
 """Verify unchanged signed bytes and independently authenticated claim linkage.

 COMPLETED timing fields are integer milliseconds measured by the emitting owner.
 Zero is a valid floor-quantized observation (<1 ms); do not round it up or invent
 elapsed time. This schema does not attest measurement accuracy or backend usage truth.
 OUTCOME_UNKNOWN is terminal, never a prediction/score, consumes reservation and is not retried.
 """
 if type(payload_bytes) is not bytes or not payload_bytes: raise ValueError("exact terminal payload bytes required")
 if type(signature) is not bytes or not signature: raise ValueError("detached signature bytes required")
 if type(expected_binding) is not dict or frozenset(expected_binding)!=frozenset(_BINDING_FIELDS): raise ValueError("expected binding schema invalid")
 for k,v in expected_binding.items(): _text(v,k)
 _text(expected_gateway_id,"expected_gateway_id"); _text(expected_key_id,"expected_key_id")
 try: payload=json.loads(payload_bytes.decode("utf-8"))
 except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise ValueError("terminal payload is not UTF-8 JSON") from exc
 if type(payload) is not dict or frozenset(payload)!=_BASE_FIELDS: raise ValueError("terminal V2 schema mismatch")
 if canonical_terminal_bytes(payload)!=payload_bytes: raise ValueError("terminal signed bytes are not canonical or were transformed")
 if payload["gateway_id"]!=expected_gateway_id or payload["key_id"]!=expected_key_id: raise ValueError("gateway or signing-key identity mismatch")
 try: Ed25519PublicKey.from_public_bytes(pinned_gateway_public_key).verify(signature,payload_bytes)
 except (ValueError,TypeError,InvalidSignature) as exc: raise ValueError("gateway terminal signature invalid") from exc
 for k,expected in expected_binding.items():
  if payload[k]!=expected: raise ValueError(f"terminal binding mismatch: {k}")
 for k in ("challenge_view_digest","model_prompt_sha256","model_artifact_sha256"): _sha(payload[k],k)
 _text(payload["model_identity"],"model_identity"); _text(payload["terminal_utc"],"terminal_utc")
 if payload["model_identity_scope"] not in ("BACKEND_REPORTED_NOT_WEIGHT_ATTESTED","UNKNOWN"): raise ValueError("unsupported model identity scope")
 if payload["status"] not in ("COMPLETED","OUTCOME_UNKNOWN"): raise ValueError("unsupported terminal status")
 claim=claim_evidence_verifier.verify_claim_evidence(expected_binding={k:payload[k] for k in _BINDING_FIELDS})
 if type(claim) is not dict or claim.get("status")!="CLAIMED": raise ValueError("independent claim evidence missing or invalid")
 if any(claim.get(k)!=payload[k] for k in _BINDING_FIELDS): raise ValueError("independent claim does not bind terminal")
 nullable=("prompt_tokens","output_tokens","gateway_wall_ms","backend_wall_ms")
 if payload["status"]=="OUTCOME_UNKNOWN":
  if payload["response_sha256"] is not None or any(payload[k] is not None for k in nullable): raise ValueError("OUTCOME_UNKNOWN must not assert response or resource measurements")
  if payload["model_identity_scope"]!="UNKNOWN": raise ValueError("OUTCOME_UNKNOWN model scope must be UNKNOWN")
  return {"status":"VERIFIED_OUTCOME_UNKNOWN","qualified":False,"prediction":None,"score_eligible":False,"automatic_retry_permitted":False,"reservation_consumed":True,"payload_sha256":hashlib.sha256(payload_bytes).hexdigest(),"payload":payload}
 _sha(payload["response_sha256"],"response_sha256")
 if payload["model_identity_scope"]!="BACKEND_REPORTED_NOT_WEIGHT_ATTESTED": raise ValueError("COMPLETED model identity scope must remain qualified")
 for k in nullable:
  if type(payload[k]) is not int or payload[k]<0: raise ValueError(f"COMPLETED requires nonnegative integer {k}")
 return {"status":"VERIFIED_COMPLETED","qualified":False,"prediction":None,"score_eligible":True,"automatic_retry_permitted":False,"reservation_consumed":True,"payload_sha256":hashlib.sha256(payload_bytes).hexdigest(),"payload":payload}
