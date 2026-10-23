"""Host-injected signature check for *provisional* Vera correction evidence.

A signature binds exact bytes, not the honesty/independence of the signer.
No key provisioning, learner authority, memory admission, model invocation,
provider route, or persistent replay registry is implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Protocol

from .evaluation_commitment import ComparisonConditions, compare_committed_predictions
from .verified_correction import (
    CorrectionEvidenceAssessment,
    EvidenceSplit,
    PairedOutcome,
    assess_correction_evidence,
)

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_OBSERVATIONS = 128


class CorrectionEvidenceVerifier(Protocol):
    """Injected by the trusted host, never from a learner's own response."""
    provider_id: str
    key_id: str
    key_digest: str

    def verify(self, subject: bytes, signature: str) -> bool:
        ...


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
    observations: tuple[PairedOutcome, ...]


@dataclass(frozen=True, slots=True)
class CorrectionEnvelopeResult:
    status: str
    assessment: CorrectionEvidenceAssessment
    nonce: str
    qualified_as_independent: bool = False
    qualified_as_self_learning: bool = False
    authorization_effect: str = "NONE"


def _bounded(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {field}")
    return value


def _sha(value: object, field: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError(f"invalid {field} SHA-256")
    return value


def _conditions(condition: ComparisonConditions) -> dict[str, str]:
    if type(condition) is not ComparisonConditions:
        raise ValueError("invalid issued comparison conditions")
    return {
        "information_condition_id": condition.information_condition_id,
        "opportunity_condition_id": condition.opportunity_condition_id,
        "resource_condition_id": condition.resource_condition_id,
        "representation_version": condition.representation_version,
    }


def _serialize_observation(row: PairedOutcome) -> dict[str, object]:
    if type(row) is not PairedOutcome:
        raise ValueError("invalid paired evidence observation")
    if row.comparison.conditions != row.issued_conditions:
        raise ValueError("issued conditions do not match the scored comparison")
    verified = compare_committed_predictions(
        row.learner, row.frozen, conditions=row.issued_conditions,
    )
    if verified != row.comparison:
        raise ValueError("signed comparison is inconsistent with prediction tickets")
    if type(row.split) is not EvidenceSplit:
        raise ValueError("invalid observation split")
    for name, value in (
        ("case_id", row.case_id),
        ("expected_label", row.expected_label),
        ("evaluator_ref", row.evaluator_ref),
    ):
        _bounded(value, name)
    return {
        "case_id": row.case_id,
        "expected_label": row.expected_label,
        "evaluator_ref": row.evaluator_ref,
        "split": row.split.value,
        "learner": {
            "candidate_id": row.learner.candidate_id,
            "step": row.learner.step,
            "commitment_sha256": row.learner.commitment,
            "prediction": dict(row.learner.prediction),
        },
        "frozen": {
            "candidate_id": row.frozen.candidate_id,
            "step": row.frozen.step,
            "commitment_sha256": row.frozen.commitment,
            "prediction": dict(row.frozen.prediction),
        },
        "issued_conditions": _conditions(row.issued_conditions),
    }


def correction_envelope_subject(envelope: SignedCorrectionEnvelope) -> bytes:
    """Canonical exact signed bytes for an external host/evaluator to sign."""
    if type(envelope) is not SignedCorrectionEnvelope:
        raise ValueError("expected exact SignedCorrectionEnvelope")
    _bounded(envelope.correction_id, "correction_id")
    _sha(envelope.preoutcome_head, "preoutcome_head")
    _bounded(envelope.nonce, "nonce")
    _bounded(envelope.evaluator_instance_id, "evaluator_instance_id")
    _bounded(envelope.learner_instance_id, "learner_instance_id")
    if (type(envelope.observations) is not tuple
            or not 1 <= len(envelope.observations) <= _MAX_OBSERVATIONS):
        raise ValueError("bounded observations required")
    payload = {
        "schema": "VERA_SHADOW_CORRECTION_SIGNED_OUTCOMES_V1",
        "correction_id": envelope.correction_id,
        "preoutcome_head": envelope.preoutcome_head,
        "nonce": envelope.nonce,
        "evaluator_instance_id": envelope.evaluator_instance_id,
        "learner_instance_id": envelope.learner_instance_id,
        "observations": [_serialize_observation(row) for row in envelope.observations],
    }
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def verify_correction_envelope(
    *,
    envelope: SignedCorrectionEnvelope,
    signature: str,
    verifier: CorrectionEvidenceVerifier,
    requirement: EvaluatorRequirement,
    previously_seen_nonces: frozenset[str],
) -> CorrectionEnvelopeResult:
    """Verify pinned identity and signed bytes, then assess (no effects).

    The host alone controls verifier, trust requirement and durable nonce
    registry. That requirement is architectural and NOT verified here.
    """
    if type(requirement) is not EvaluatorRequirement:
        raise ValueError("host-pinned evaluator requirement missing")
    if type(previously_seen_nonces) is not frozenset:
        raise ValueError("host-owned replay snapshot must be a frozenset")
    if type(envelope) is not SignedCorrectionEnvelope:
        raise ValueError("missing exact signed envelope")
    if envelope.nonce in previously_seen_nonces:
        raise ValueError("evaluator nonce replay denied")
    if envelope.evaluator_instance_id == envelope.learner_instance_id:
        raise ValueError("evaluator and learner instance labels must be distinct")
    if envelope.evaluator_instance_id != requirement.evaluator_instance_id:
        raise ValueError("unexpected evaluator instance label")
    if envelope.preoutcome_head != requirement.preoutcome_head:
        raise ValueError("unexpected preoutcome head")
    _sha(requirement.key_digest, "evaluator key digest")
    _sha(requirement.preoutcome_head, "required preoutcome head")
    if (getattr(verifier, "provider_id", None) != requirement.provider_id
            or getattr(verifier, "key_id", None) != requirement.key_id
            or getattr(verifier, "key_digest", None) != requirement.key_digest):
        raise ValueError("provider or key does not match host-pinned requirement")
    if type(signature) is not str or _HEX64.fullmatch(signature) is None:
        raise ValueError("invalid evaluator signature")
    subject = correction_envelope_subject(envelope)
    if not verifier.verify(subject, signature):
        raise ValueError("evaluator signature verification failed")
    assessment = assess_correction_evidence(
        correction_id=envelope.correction_id,
        observations=envelope.observations,
    )
    return CorrectionEnvelopeResult(
        status=(
            "SIGNATURE_VALID_PROVISIONAL_ONLY"
            if assessment.eligible_for_review else "SIGNATURE_VALID_NOT_ELIGIBLE"
        ),
        assessment=assessment,
        nonce=envelope.nonce,
    )
