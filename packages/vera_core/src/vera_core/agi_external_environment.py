"""Externally attested environment-generalization measurement.

This module does not execute external tasks. It measures host/provider-executed
attempts using Vera Mono's existing behavior-attestation receipts and preserves
all attempts, including failures and unresolved outcomes.

Successful measurement remains PARTIAL pending live independent review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable

from portfolio_runtime.lantern.canonical import (
    canonical_json_bytes,
    sha256_hex,
)

from .behavior_attestation import (
    BehaviorAttestationReceipt,
    BehaviorAttestationStore,
)


_RUNTIME_BINDINGS = frozenset({
    "SOURCE_ONLY",
    "LOCAL_TEST_RUNTIME",
    "QUALIFIED_RUNTIME",
})
_OUTCOME_STATES = frozenset({"SUCCESS", "FAILURE", "UNRESOLVED"})
_EXTERNAL_AUTHORSHIP = "NON_VERA_THIRD_PARTY"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(value: str, field: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{field} must be an exact SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _exact_head(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            "exact_head must be 40 lowercase hexadecimal characters"
        )


def _rate(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out) or not 0.0 <= out <= 1.0:
        raise ValueError(f"{field} must be finite and in [0, 1]")
    return out


def _non_negative(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"{field} must be finite and non-negative")
    return out


@dataclass(frozen=True, slots=True)
class ExternalEnvironmentAttempt:
    attempt_id: str
    environment_id: str
    environment_owner: str
    environment_declaration_digest: str
    environment_authorship: str
    attestation: BehaviorAttestationReceipt
    outcome_state: str
    intervention_count: int

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "environment_id",
            "environment_owner",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty exact string")
        _digest(
            self.environment_declaration_digest,
            "environment_declaration_digest",
        )
        if self.environment_authorship != _EXTERNAL_AUTHORSHIP:
            raise ValueError(
                "EXTERNAL_ENVIRONMENT requires NON_VERA_THIRD_PARTY authorship"
            )
        if type(self.attestation) is not BehaviorAttestationReceipt:
            raise TypeError(
                "attestation must be exact BehaviorAttestationReceipt"
            )
        if self.outcome_state not in _OUTCOME_STATES:
            raise ValueError(
                f"unsupported external outcome state: {self.outcome_state!r}"
            )
        if (
            type(self.intervention_count) is not int
            or self.intervention_count < 0
        ):
            raise ValueError(
                "intervention_count must be an exact non-negative int"
            )


@dataclass(frozen=True, slots=True)
class ExternalEnvironmentMetrics:
    attempted: int
    succeeded: int
    failed: int
    unresolved: int
    task_success_rate: float
    mean_interventions: float
    unresolved_rate: float
    invalid_attestation_count: int


@dataclass(frozen=True, slots=True)
class ExternalEnvironmentQualificationResult:
    metrics: ExternalEnvironmentMetrics
    packet: dict[str, object]
    qualification_artifact_json: str
    qualification_artifact_digest: str


def _valid_attestation(
    receipt: BehaviorAttestationReceipt,
    *,
    probe_id: str,
) -> bool:
    if receipt.probe_id != probe_id or receipt.status != "PASS":
        return False
    expected_receipt_digest = sha256_hex(
        canonical_json_bytes(BehaviorAttestationStore._payload(receipt))
    )
    if expected_receipt_digest != receipt.receipt_digest:
        return False
    if receipt.observed_signature_valid is not True:
        return False
    if (
        receipt.observed_provider_id != receipt.expected_provider_id
        or receipt.observed_provider_key_id
        != receipt.expected_provider_key_id
        or receipt.observed_provider_key_digest
        != receipt.expected_provider_key_digest
        or receipt.observed_declaration_digest
        != receipt.expected_declaration_digest
        or receipt.observed_behavior_effect_receipt_digest
        != receipt.behavior_effect_receipt_digest
    ):
        return False
    required_digests = (
        receipt.packet_digest,
        receipt.expected_declaration_digest,
        receipt.expected_provider_key_digest,
        receipt.behavior_effect_receipt_digest,
        receipt.observed_runtime_state_digest,
        receipt.observed_stimulus_digest,
        receipt.observed_outcome_digest,
        receipt.observed_raw_response_digest,
        receipt.observed_attestation_subject_digest,
        receipt.observed_external_evidence_digest,
        receipt.predecessor_digest,
        receipt.receipt_digest,
    )
    if any(
        value is None
        or type(value) is not str
        or len(value) != 64
        for value in required_digests
    ):
        return False
    try:
        for value in required_digests:
            int(value, 16)
    except ValueError:
        return False
    if (
        type(receipt.observed_attestation_nonce) is not str
        or not receipt.observed_attestation_nonce
        or type(receipt.observed_raw_response_digest) is not str
        or type(receipt.observed_external_evidence_digest) is not str
        or type(receipt.evidence_ref) is not str
        or not receipt.evidence_ref
    ):
        return False
    return True


def qualify_external_environment(
    attempts: Iterable[ExternalEnvironmentAttempt],
    *,
    min_attempts: int,
    min_task_success_rate: float,
    max_mean_interventions: float,
    max_unresolved_rate: float,
    repository: str,
    exact_head: str,
    runtime_binding: str,
    probe_id: str,
    items_digest: str,
    curator_independence: str,
    training_overlap: str,
    developer_item_access: bool,
    tool_access: Iterable[str],
    claim_ceiling: str,
) -> ExternalEnvironmentQualificationResult:
    """Measure external usefulness without self-promoting to PASS."""

    rows = tuple(attempts)
    if not rows:
        raise ValueError("attempts must not be empty")
    if any(type(item) is not ExternalEnvironmentAttempt for item in rows):
        raise TypeError(
            "attempts must contain exact ExternalEnvironmentAttempt values"
        )
    if type(min_attempts) is not int or min_attempts < 1:
        raise ValueError("min_attempts must be an exact positive int")
    min_success = _rate(min_task_success_rate, "min_task_success_rate")
    max_interventions = _non_negative(
        max_mean_interventions,
        "max_mean_interventions",
    )
    max_unresolved = _rate(max_unresolved_rate, "max_unresolved_rate")
    if type(repository) is not str or not repository:
        raise ValueError("repository must be a non-empty exact string")
    _exact_head(exact_head)
    if runtime_binding not in _RUNTIME_BINDINGS:
        raise ValueError("unsupported runtime_binding")
    if type(probe_id) is not str or not probe_id:
        raise ValueError("probe_id must be a non-empty exact string")
    items_digest = _digest(items_digest, "items_digest")
    if type(curator_independence) is not str or not curator_independence:
        raise ValueError(
            "curator_independence must be a non-empty exact string"
        )
    if type(training_overlap) is not str or not training_overlap:
        raise ValueError("training_overlap must be a non-empty exact string")
    if type(developer_item_access) is not bool:
        raise TypeError("developer_item_access must be bool")
    tools = tuple(tool_access)
    if any(type(item) is not str or not item for item in tools):
        raise ValueError("tool_access must contain non-empty exact strings")
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    first = rows[0]
    environment_identity = (
        first.environment_id,
        first.environment_owner,
        first.environment_declaration_digest,
        first.environment_authorship,
    )
    if any(
        (
            row.environment_id,
            row.environment_owner,
            row.environment_declaration_digest,
            row.environment_authorship,
        )
        != environment_identity
        for row in rows
    ):
        raise ValueError(
            "all external attempts in one packet must bind one environment"
        )

    attempt_ids: set[str] = set()
    receipt_digests: set[str] = set()
    nonces: set[str] = set()
    invalid_attestations = 0
    succeeded = 0
    failed = 0
    unresolved = 0
    intervention_total = 0
    artifact_attempts: list[dict[str, object]] = []

    for row in rows:
        if row.attempt_id in attempt_ids:
            raise ValueError("external attempt IDs must be unique")
        attempt_ids.add(row.attempt_id)

        receipt = row.attestation
        canonical = _valid_attestation(receipt, probe_id=probe_id)
        if receipt.receipt_digest in receipt_digests:
            canonical = False
        receipt_digests.add(receipt.receipt_digest)
        nonce = receipt.observed_attestation_nonce
        if nonce is None or nonce in nonces:
            canonical = False
        else:
            nonces.add(nonce)

        invalid_attestations += int(not canonical)
        if row.outcome_state == "SUCCESS" and canonical:
            succeeded += 1
        elif row.outcome_state == "UNRESOLVED":
            unresolved += 1
        else:
            failed += 1
        intervention_total += row.intervention_count

        artifact_attempts.append(
            {
                "attempt_id": row.attempt_id,
                "outcome_state": row.outcome_state,
                "intervention_count": row.intervention_count,
                "attestation_valid": canonical,
                "attestation": asdict(receipt),
            }
        )

    attempted = len(rows)
    success_rate = succeeded / attempted
    mean_interventions = intervention_total / attempted
    unresolved_rate = unresolved / attempted
    metrics = ExternalEnvironmentMetrics(
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        unresolved=unresolved,
        task_success_rate=success_rate,
        mean_interventions=mean_interventions,
        unresolved_rate=unresolved_rate,
        invalid_attestation_count=invalid_attestations,
    )

    metrics_pass = (
        attempted >= min_attempts
        and invalid_attestations == 0
        and success_rate >= min_success
        and mean_interventions <= max_interventions
        and unresolved_rate <= max_unresolved
    )
    state = "PARTIAL" if metrics_pass else "FAIL"
    dimensions = {"EXTERNAL_GENERALIZATION": state}

    artifact = {
        "schema": "VERA_AGI_EXTERNAL_ENVIRONMENT_QUALIFICATION_V1",
        "probe_id": probe_id,
        "items_digest": items_digest,
        "environment": {
            "environment_id": first.environment_id,
            "owner": first.environment_owner,
            "declaration_digest": first.environment_declaration_digest,
            "authorship": first.environment_authorship,
        },
        "thresholds": {
            "min_attempts": min_attempts,
            "min_task_success_rate": min_success,
            "max_mean_interventions": max_interventions,
            "max_unresolved_rate": max_unresolved,
        },
        "metrics": asdict(metrics),
        "attempts": artifact_attempts,
        "curator_independence": curator_independence,
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "measurement_only": True,
        "independent_review_required_for_pass": True,
        "environment_authorship_requires_independent_confirmation": True,
        "dimension_states": dimensions,
    }
    artifact_json = _canonical_json(artifact)
    artifact_digest = hashlib.sha256(
        artifact_json.encode("utf-8")
    ).hexdigest()

    packet = {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": repository,
            "exact_head": exact_head,
            "runtime_binding": runtime_binding,
        },
        "probe": {
            "probe_id": probe_id,
            "family": "EXTERNAL_ENVIRONMENT",
            "held_out": True,
            "curator_independence": curator_independence,
            "items_digest": items_digest,
        },
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "results": {
            "attempted": attempted,
            "passed": succeeded,
            "failed": attempted - succeeded,
            "raw_artifact_digest": artifact_digest,
            "negative_results_preserved": True,
        },
        "dimension_states": dimensions,
        "independent_review": None,
        "claim_ceiling": claim_ceiling,
    }
    return ExternalEnvironmentQualificationResult(
        metrics=metrics,
        packet=packet,
        qualification_artifact_json=artifact_json,
        qualification_artifact_digest=artifact_digest,
    )
