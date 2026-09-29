"""Conservative aggregate qualification for AGI research evidence.

Aggregation is deliberately fail-closed. It combines evaluation packets bound
to one exact repository head, preserves explicit failures, and cannot promote
an incompletely evaluated subject into a survival state.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


REQUIRED_AGI_DIMENSIONS = (
    "CROSS_DOMAIN_BREADTH",
    "NOVEL_TASK_TRANSFER",
    "LEARNING_EFFICIENCY",
    "RETENTION_AND_INTERFERENCE",
    "LONG_HORIZON_AGENCY",
    "METACOGNITIVE_CALIBRATION",
    "ROBUSTNESS_AND_ANTI_GAMING",
    "EXTERNAL_GENERALIZATION",
)

_ALLOWED_DIMENSION_STATES = frozenset({
    "NOT_EVALUATED",
    "FAIL",
    "PARTIAL",
    "PASS",
})

_ALLOWED_INDEPENDENT_REVIEW_STATES = frozenset({
    "NOT_REVIEWED",
    "REVIEWED_WITH_UNRESOLVED_OBJECTION",
    "SURVIVES_INDEPENDENT_REVIEW",
})


def _validate_head(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            "subject_head must be 40 lowercase hexadecimal characters"
        )


def _dimension_state_from_evidence(states: Sequence[str]) -> str:
    evaluated = [state for state in states if state != "NOT_EVALUATED"]
    if not evaluated:
        return "NOT_EVALUATED"
    if "FAIL" in evaluated:
        return "FAIL"
    if "PARTIAL" in evaluated:
        return "PARTIAL"
    if all(state == "PASS" for state in evaluated):
        return "PASS"
    raise ValueError("unrecognized dimension state evidence")


def aggregate_agi_qualification(
    packets: Sequence[Mapping[str, Any]],
    *,
    subject_head: str,
    independent_review_state: str,
    claim_ceiling: str,
) -> dict[str, object]:
    """Aggregate packets without exceeding the weakest required dimension."""

    _validate_head(subject_head)
    if independent_review_state not in _ALLOWED_INDEPENDENT_REVIEW_STATES:
        raise ValueError("unsupported independent_review_state")
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    evidence: dict[str, list[str]] = {
        dimension: [] for dimension in REQUIRED_AGI_DIMENSIONS
    }

    for packet in packets:
        if not isinstance(packet, Mapping):
            raise TypeError("packets must contain mapping values")
        if packet.get("schema") != "VERA_AGI_EVALUATION_PACKET_V1":
            raise ValueError("unsupported evaluation packet schema")

        subject = packet.get("subject")
        if not isinstance(subject, Mapping):
            raise ValueError("evaluation packet subject is missing")
        packet_head = subject.get("exact_head")
        if packet_head != subject_head:
            raise ValueError(
                "evaluation packet subject head does not match aggregate "
                f"subject head: {packet_head!r} != {subject_head!r}"
            )

        results = packet.get("results")
        if not isinstance(results, Mapping):
            raise ValueError("evaluation packet results are missing")
        if results.get("negative_results_preserved") is not True:
            raise ValueError(
                "evaluation packet does not preserve negative results"
            )

        contamination = packet.get("contamination")
        if not isinstance(contamination, Mapping):
            raise ValueError("evaluation packet contamination is missing")
        if contamination.get("post_disclosure_tuning") is True:
            raise ValueError(
                "post-disclosure-tuned packet cannot enter aggregation"
            )

        dimension_states = packet.get("dimension_states")
        if not isinstance(dimension_states, Mapping):
            raise ValueError("evaluation packet dimension_states are missing")
        for dimension, state in dimension_states.items():
            if dimension not in evidence:
                continue
            if state not in _ALLOWED_DIMENSION_STATES:
                raise ValueError(
                    f"invalid dimension state for {dimension}: {state!r}"
                )
            evidence[dimension].append(state)

    aggregate_dimensions = {
        dimension: _dimension_state_from_evidence(states)
        for dimension, states in evidence.items()
    }
    values = tuple(aggregate_dimensions.values())

    if all(state == "NOT_EVALUATED" for state in values):
        aggregate_state = "NOT_EVALUATED"
    elif "FAIL" in values:
        aggregate_state = "FAILS_CURRENT_CONTRACT"
    elif all(state == "PASS" for state in values):
        aggregate_state = (
            "SURVIVES_CURRENT_CONTRACT_INDEPENDENTLY_REVIEWED"
            if independent_review_state == "SURVIVES_INDEPENDENT_REVIEW"
            else "SURVIVES_CURRENT_CONTRACT"
        )
    else:
        aggregate_state = "PARTIALLY_EVALUATED"

    return {
        "schema": "VERA_AGI_AGGREGATE_QUALIFICATION_V1",
        "subject_head": subject_head,
        "required_dimensions": list(REQUIRED_AGI_DIMENSIONS),
        "dimension_states": aggregate_dimensions,
        "aggregate_state": aggregate_state,
        "independent_review_state": independent_review_state,
        "claim_ceiling": claim_ceiling,
    }
