"""Governed, verifier-bound action selection for V.E.R.A.

This module ranks externally supplied candidate actions under an externally
supplied policy. It does not generate, own, authenticate, or execute goals.
Authority, permission, and evidence claims are accepted only when a trusted
runtime verifier attests the exact policy and complete candidate set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
import hmac
import json
from math import isfinite
from typing import Any, Iterable, Literal, Protocol, runtime_checkable

DecisionResult = Literal["SELECTED", "ABSTAIN"]
ATTESTATION_SCHEMA = "VERA_INITIATIVE_INPUT_ATTESTATION_V1"
RECEIPT_SCHEMA = "VERA_INITIATIVE_DECISION_RECEIPT_V1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ScoreWeights:
    """Weights for tradeoffs allowed only after hard policy gating."""

    alignment: float = 3.0
    evidence: float = 2.0
    reversibility: float = 1.0
    urgency: float = 1.0
    benefit: float = 2.0
    harm: float = 3.0
    uncertainty: float = 2.0
    cost: float = 1.0

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not isfinite(value) or value < 0:
                raise ValueError(f"weight {name!r} must be finite and non-negative")


@dataclass(frozen=True)
class InitiativePolicy:
    """External governance for one action-selection decision."""

    policy_version: str = "VERA_INITIATIVE_POLICY_V1"
    minimum_authority: float = 0.5
    minimum_evidence: float = 0.5
    minimum_alignment: float = 0.5
    minimum_reversibility: float = 0.25
    maximum_harm: float = 0.5
    maximum_uncertainty: float = 0.6
    minimum_score: float = 0.0
    allow_production_mutation: bool = False
    weights: ScoreWeights = field(default_factory=ScoreWeights)

    def validate(self) -> None:
        _validate_text(self.policy_version, "policy_version")
        for name in (
            "minimum_authority",
            "minimum_evidence",
            "minimum_alignment",
            "minimum_reversibility",
            "maximum_harm",
            "maximum_uncertainty",
        ):
            _validate_unit_interval(name, getattr(self, name))
        if not isfinite(self.minimum_score):
            raise ValueError("minimum_score must be finite")
        self.weights.validate()

    def canonical_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class AttributableEvidence:
    """One bounded source reference supporting candidate evaluation claims."""

    surface: str
    reference_id: str
    observation: str

    def validate(self) -> None:
        _validate_text(self.surface, "evidence.surface")
        _validate_text(self.reference_id, "evidence.reference_id")
        _validate_text(self.observation, "evidence.observation")


@dataclass(frozen=True)
class CandidateAction:
    """One externally proposed action and its attested evaluation inputs."""

    candidate_id: str
    description: str
    authority: float
    evidence: float
    objective_alignment: float
    expected_benefit: float
    expected_harm: float
    uncertainty: float
    resource_cost: float
    reversibility: float
    urgency: float = 0.0
    production_mutation: bool = False
    forbidden_by_policy: bool = False
    blocked_by_correction: bool = False
    required_permissions: tuple[str, ...] = ()
    available_permissions: tuple[str, ...] = ()
    source_evidence: tuple[AttributableEvidence, ...] = ()

    def validate(self) -> None:
        _validate_text(self.candidate_id, "candidate_id")
        _validate_text(self.description, f"candidate {self.candidate_id!r} description")
        for name in (
            "authority",
            "evidence",
            "objective_alignment",
            "expected_benefit",
            "expected_harm",
            "uncertainty",
            "resource_cost",
            "reversibility",
            "urgency",
        ):
            _validate_unit_interval(name, getattr(self, name))
        _validate_unique_strings("required_permissions", self.required_permissions)
        _validate_unique_strings("available_permissions", self.available_permissions)
        if not self.source_evidence:
            raise ValueError(
                f"candidate {self.candidate_id!r} requires attributable source_evidence"
            )
        for item in self.source_evidence:
            if not isinstance(item, AttributableEvidence):
                raise TypeError("source_evidence items must be AttributableEvidence")
            item.validate()

    def canonical_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    eligible: bool
    score: float | None
    rejection_reasons: tuple[str, ...]
    priority_vector: tuple[float, ...] | None


@dataclass(frozen=True)
class InitiativeInputAttestation:
    """Verifier-issued attestation for one exact policy and candidate set."""

    schema: str
    issuer_id: str
    subject: str
    verification_token: str

    def canonical_body(self) -> dict[str, str]:
        return {
            "schema": self.schema,
            "issuer_id": self.issuer_id,
            "subject": self.subject,
        }


@runtime_checkable
class InitiativeInputVerifier(Protocol):
    def verify(
        self,
        attestation: InitiativeInputAttestation,
        *,
        expected_subject: str,
    ) -> bool:
        ...


class HmacInitiativeAuthority:
    """Reference external issuer/verifier using a runtime-held HMAC secret.

    The attestation is evidence about an exact decision input, not an execution
    capability. Re-verifying the same immutable input is therefore permitted.
    """

    def __init__(self, issuer_id: str, secret: bytes) -> None:
        _validate_text(issuer_id, "issuer_id")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("secret must be at least 32 bytes")
        self.issuer_id = issuer_id
        self._secret = secret

    def issue(
        self,
        policy: InitiativePolicy,
        candidates: Iterable[CandidateAction],
    ) -> InitiativeInputAttestation:
        canonical_candidates = _canonical_candidates(tuple(candidates))
        subject = decision_subject(policy, canonical_candidates)
        unsigned = InitiativeInputAttestation(
            schema=ATTESTATION_SCHEMA,
            issuer_id=self.issuer_id,
            subject=subject,
            verification_token="",
        )
        token = hmac.new(
            self._secret,
            _canonical_bytes(unsigned.canonical_body()),
            sha256,
        ).hexdigest()
        return replace(unsigned, verification_token=token)

    def verify(
        self,
        attestation: InitiativeInputAttestation,
        *,
        expected_subject: str,
    ) -> bool:
        try:
            if not isinstance(attestation, InitiativeInputAttestation):
                return False
            if attestation.schema != ATTESTATION_SCHEMA:
                return False
            if attestation.issuer_id != self.issuer_id:
                return False
            if attestation.subject != expected_subject:
                return False
            expected = hmac.new(
                self._secret,
                _canonical_bytes(attestation.canonical_body()),
                sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, attestation.verification_token)
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True)
class DecisionReceipt:
    schema: str
    policy_version: str
    policy_hash: str
    attestation_issuer_id: str
    decision_subject: str
    result: DecisionResult
    selected_candidate_id: str | None
    candidate_set_hash: str
    evaluations: tuple[CandidateEvaluation, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class InitiativeKernel:
    """Select a feasible candidate from externally verified decision inputs."""

    def __init__(
        self,
        policy: InitiativePolicy | None = None,
        *,
        input_verifier: InitiativeInputVerifier | None = None,
    ) -> None:
        self.policy = policy or InitiativePolicy()
        self.policy.validate()
        self._input_verifier = input_verifier

    def decide(
        self,
        candidates: Iterable[CandidateAction],
        *,
        attestation: InitiativeInputAttestation | None,
    ) -> DecisionReceipt:
        materialized = _canonical_candidates(tuple(candidates))
        candidate_hash = candidate_set_hash(materialized)
        applied_policy_hash = policy_hash(self.policy)
        subject = decision_subject(self.policy, materialized)
        verifier = self._input_verifier
        if verifier is None:
            raise PermissionError("initiative decision requires an injected trusted verifier")
        if not isinstance(attestation, InitiativeInputAttestation):
            raise PermissionError(
                "initiative decision requires a verifier-issued input attestation"
            )
        if not verifier.verify(attestation, expected_subject=subject):
            raise PermissionError(
                "initiative input attestation failed for the exact policy and candidate set"
            )

        evaluations = tuple(self.evaluate(candidate) for candidate in materialized)
        eligible = [item for item in evaluations if item.eligible]
        limitations = (
            "Candidate metrics and permissions are externally attested inputs, not model self-reports.",
            "Source evidence is attributable but is not automatically true or sufficient outside this policy.",
            "Selection proves policy evaluation only; it does not execute the action.",
        )

        if not eligible:
            return self._receipt(
                attestation=attestation,
                subject=subject,
                applied_policy_hash=applied_policy_hash,
                candidate_hash=candidate_hash,
                result="ABSTAIN",
                selected_candidate_id=None,
                evaluations=evaluations,
                limitations=limitations,
            )

        ranked = sorted(
            eligible,
            key=lambda item: (
                tuple(-value for value in item.priority_vector or ()),
                item.candidate_id,
            ),
        )
        best = ranked[0]
        if best.score is None or best.score < self.policy.minimum_score:
            return self._receipt(
                attestation=attestation,
                subject=subject,
                applied_policy_hash=applied_policy_hash,
                candidate_hash=candidate_hash,
                result="ABSTAIN",
                selected_candidate_id=None,
                evaluations=evaluations,
                limitations=limitations
                + ("The highest-ranked feasible candidate did not clear minimum_score.",),
            )

        return self._receipt(
            attestation=attestation,
            subject=subject,
            applied_policy_hash=applied_policy_hash,
            candidate_hash=candidate_hash,
            result="SELECTED",
            selected_candidate_id=best.candidate_id,
            evaluations=evaluations,
            limitations=limitations,
        )

    def _receipt(
        self,
        *,
        attestation: InitiativeInputAttestation,
        subject: str,
        applied_policy_hash: str,
        candidate_hash: str,
        result: DecisionResult,
        selected_candidate_id: str | None,
        evaluations: tuple[CandidateEvaluation, ...],
        limitations: tuple[str, ...],
    ) -> DecisionReceipt:
        return DecisionReceipt(
            schema=RECEIPT_SCHEMA,
            policy_version=self.policy.policy_version,
            policy_hash=applied_policy_hash,
            attestation_issuer_id=attestation.issuer_id,
            decision_subject=subject,
            result=result,
            selected_candidate_id=selected_candidate_id,
            candidate_set_hash=candidate_hash,
            evaluations=evaluations,
            limitations=limitations,
        )

    def evaluate(self, candidate: CandidateAction) -> CandidateEvaluation:
        candidate.validate()
        reasons: list[str] = []
        if candidate.forbidden_by_policy:
            reasons.append("FORBIDDEN_BY_POLICY")
        if candidate.blocked_by_correction:
            reasons.append("BLOCKED_BY_CURRENT_CORRECTION")
        if candidate.production_mutation and not self.policy.allow_production_mutation:
            reasons.append("PRODUCTION_MUTATION_NOT_AUTHORIZED")

        missing_permissions = sorted(
            set(candidate.required_permissions) - set(candidate.available_permissions)
        )
        reasons.extend(f"MISSING_PERMISSION:{item}" for item in missing_permissions)
        threshold_checks = (
            (candidate.authority < self.policy.minimum_authority, "INSUFFICIENT_AUTHORITY"),
            (candidate.evidence < self.policy.minimum_evidence, "INSUFFICIENT_EVIDENCE"),
            (
                candidate.objective_alignment < self.policy.minimum_alignment,
                "INSUFFICIENT_OBJECTIVE_ALIGNMENT",
            ),
            (
                candidate.reversibility < self.policy.minimum_reversibility,
                "INSUFFICIENT_REVERSIBILITY",
            ),
            (candidate.expected_harm > self.policy.maximum_harm, "HARM_LIMIT_EXCEEDED"),
            (
                candidate.uncertainty > self.policy.maximum_uncertainty,
                "UNCERTAINTY_LIMIT_EXCEEDED",
            ),
        )
        reasons.extend(code for failed, code in threshold_checks if failed)
        if reasons:
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                eligible=False,
                score=None,
                rejection_reasons=tuple(reasons),
                priority_vector=None,
            )

        score = self._score(candidate)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            eligible=True,
            score=score,
            rejection_reasons=(),
            priority_vector=(
                candidate.authority,
                candidate.evidence,
                candidate.objective_alignment,
                candidate.reversibility,
                score,
                candidate.urgency,
            ),
        )

    def _score(self, candidate: CandidateAction) -> float:
        weights = self.policy.weights
        return (
            weights.alignment * candidate.objective_alignment
            + weights.evidence * candidate.evidence
            + weights.reversibility * candidate.reversibility
            + weights.urgency * candidate.urgency
            + weights.benefit * candidate.expected_benefit
            - weights.harm * candidate.expected_harm
            - weights.uncertainty * candidate.uncertainty
            - weights.cost * candidate.resource_cost
        )


def policy_hash(policy: InitiativePolicy) -> str:
    return _hash(policy.canonical_dict())


def candidate_set_hash(candidates: Iterable[CandidateAction]) -> str:
    canonical = _canonical_candidates(tuple(candidates))
    return _hash([candidate.canonical_dict() for candidate in canonical])


def decision_subject(
    policy: InitiativePolicy,
    candidates: Iterable[CandidateAction],
) -> str:
    canonical = _canonical_candidates(tuple(candidates))
    body = {
        "operation": "initiative_decide",
        "policy_hash": policy_hash(policy),
        "candidate_set_hash": candidate_set_hash(canonical),
    }
    return "initiative-decision-v1:" + _hash(body)


def _canonical_candidates(
    candidates: tuple[CandidateAction, ...],
) -> tuple[CandidateAction, ...]:
    ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, CandidateAction):
            raise TypeError("candidates must be CandidateAction instances")
        candidate.validate()
        ids.append(candidate.candidate_id)
    if len(set(ids)) != len(ids):
        raise ValueError("candidate_id values must be unique")
    return tuple(sorted(candidates, key=lambda item: item.candidate_id))


def _validate_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _validate_unit_interval(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and within [0, 1]")


def _validate_unique_strings(name: str, values: tuple[str, ...]) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} may not contain blank values")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} may not contain duplicates")


def receipt_to_json(receipt: DecisionReceipt) -> str:
    """Serialize a receipt canonically for storage or comparison."""

    return _canonical_bytes(receipt.as_dict()).decode("utf-8")
