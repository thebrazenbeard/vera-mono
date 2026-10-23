"""Experimental host-supplied evaluator custody seam (not yet implemented)."""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class EvaluatorRequirement:
    provider_id: str
    key_id: str
    key_digest: str
    preoutcome_head: str
    evaluator_instance_id: str

@dataclass(frozen=True, slots=True)
class SignedCorrectionEnvelope:
    correction_id: str
    preoutcome_head: str
    nonce: str
    evaluator_instance_id: str
    learner_instance_id: str
    observations: tuple

def correction_envelope_subject(envelope: SignedCorrectionEnvelope) -> bytes:
    raise NotImplementedError("separate signed evidence subject")

def verify_correction_envelope(**kwargs):
    raise NotImplementedError("host-injected signature verification")
