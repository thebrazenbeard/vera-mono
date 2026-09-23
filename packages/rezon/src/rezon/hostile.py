from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class HostileViolation(str, Enum):
    PROPOSITION_SUBSTITUTION = "PROPOSITION_SUBSTITUTION"
    STALE_SOURCE = "STALE_SOURCE"
    ROLLBACK_SOURCE = "ROLLBACK_SOURCE"
    DUPLICATE_EVIDENCE_LAUNDERING = "DUPLICATE_EVIDENCE_LAUNDERING"
    CORRELATED_CONSENSUS_LAUNDERING = "CORRELATED_CONSENSUS_LAUNDERING"
    ADVISORY_AUTHORITY_LAUNDERING = "ADVISORY_AUTHORITY_LAUNDERING"
    MALFORMED_RECEIPT = "MALFORMED_RECEIPT"
    PARTIAL_FAILURE_HIDDEN = "PARTIAL_FAILURE_HIDDEN"


_ADVISORY_AUTHORITY_BASES = {
    "token_confidence",
    "path_score",
    "learned_geometry",
    "embedding_similarity",
    "model_prestige",
    "consensus",
}


def audit_hostile_case(case: Mapping[str, Any]) -> tuple[HostileViolation, ...]:
    violations: list[HostileViolation] = []

    literal = case.get("literal_request")
    solved = case.get("solved_request")
    if literal is not None and solved is not None and literal != solved:
        violations.append(HostileViolation.PROPOSITION_SUBSTITUTION)

    source_version = case.get("source_version")
    required_version = case.get("required_source_version")
    if source_version is not None and required_version is not None and source_version != required_version:
        violations.append(HostileViolation.STALE_SOURCE)

    generation = case.get("source_generation")
    min_generation = case.get("required_min_generation")
    if generation is not None and min_generation is not None and generation < min_generation:
        violations.append(HostileViolation.ROLLBACK_SOURCE)

    origins = case.get("evidence_origins")
    declared_count = case.get("declared_independent_evidence_count")
    if origins is not None and declared_count is not None and len(set(origins)) < declared_count:
        violations.append(HostileViolation.DUPLICATE_EVIDENCE_LAUNDERING)

    independence = case.get("worker_independence")
    if case.get("consensus_counted_as_evidence"):
        if (
            independence is None
            or not independence
            or not all(value is True for value in independence)
        ):
            violations.append(HostileViolation.CORRELATED_CONSENSUS_LAUNDERING)

    if case.get("authority_basis") in _ADVISORY_AUTHORITY_BASES:
        violations.append(HostileViolation.ADVISORY_AUTHORITY_LAUNDERING)

    receipt = case.get("receipt")
    if receipt is not None:
        if not isinstance(receipt, Mapping) or not receipt.get("task_id") or not receipt.get("episode_version"):
            violations.append(HostileViolation.MALFORMED_RECEIPT)

    if case.get("reported_clean_success") and case.get("failures"):
        violations.append(HostileViolation.PARTIAL_FAILURE_HIDDEN)

    return tuple(violations)
