"""Executable guardrails for the Vera AGI research qualification contract.

This module evaluates evidence packets and weakest-link dimension state. It does
not establish AGI, runtime authority, consciousness, or protected-effect
permission.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


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

AGI_HELD_OUT_FAMILIES = frozenset(
    {
        "NOVEL_MAPPING",
        "COMPOSITIONAL_TRANSFER",
        "REGIME_RETURN",
        "AMBIGUOUS_SPEC",
        "CORRECTION_TRANSFER",
        "EXTERNAL_ENVIRONMENT",
    }
)

CURATOR_INDEPENDENCE_STATES = frozenset(
    {
        "DEVELOPER_AUTHORED_HIDDEN_CUT",
        "INDEPENDENT_MODEL",
        "INDEPENDENT_HUMAN",
        "EXTERNAL_BENCHMARK",
    }
)

TRAINING_OVERLAP_STATES = frozenset(
    {"NONE_KNOWN", "POSSIBLE", "CONFIRMED", "UNKNOWN"}
)


class DimensionState(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    PASS = "PASS"


class AggregateQualificationState(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    PARTIALLY_EVALUATED = "PARTIALLY_EVALUATED"
    FAILS_CURRENT_CONTRACT = "FAILS_CURRENT_CONTRACT"
    SURVIVES_CURRENT_CONTRACT = "SURVIVES_CURRENT_CONTRACT"
    SURVIVES_CURRENT_CONTRACT_INDEPENDENTLY_REVIEWED = (
        "SURVIVES_CURRENT_CONTRACT_INDEPENDENTLY_REVIEWED"
    )


class IndependentReviewState(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REVIEWED_WITH_UNRESOLVED_OBJECTION = "REVIEWED_WITH_UNRESOLVED_OBJECTION"
    SURVIVES_INDEPENDENT_REVIEW = "SURVIVES_INDEPENDENT_REVIEW"


def _hex(value: str, *, length: int, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            f"{field} must be a lowercase {length}-character hex string"
        )
    return value


def _dimension_map(
    values: Mapping[str, DimensionState],
    *,
    allow_partial: bool,
) -> Mapping[str, DimensionState]:
    if not isinstance(values, Mapping):
        raise TypeError("dimension_states must be a mapping")
    unknown = sorted(set(values) - set(REQUIRED_AGI_DIMENSIONS))
    if unknown:
        raise ValueError("unknown AGI dimension(s): " + ",".join(unknown))
    normalized: dict[str, DimensionState] = {}
    for dimension, state in values.items():
        if type(state) is not DimensionState:
            raise TypeError(
                f"dimension state for {dimension} must be exact DimensionState"
            )
        normalized[dimension] = state
    if not allow_partial and set(normalized) != set(REQUIRED_AGI_DIMENSIONS):
        missing = sorted(set(REQUIRED_AGI_DIMENSIONS) - set(normalized))
        raise ValueError("missing AGI dimension(s): " + ",".join(missing))
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class AGIEvaluationPacket:
    packet_id: str
    subject_head: str
    family: str
    held_out: bool
    curator_independence: str
    training_overlap: str
    post_disclosure_tuning: bool
    developer_item_access: bool
    tool_access: tuple[str, ...]
    attempted: int
    passed: int
    failed: int
    raw_artifact_digest: str
    negative_results_preserved: bool
    dimension_states: Mapping[str, DimensionState]

    def __post_init__(self) -> None:
        if type(self.packet_id) is not str or not self.packet_id:
            raise ValueError("packet_id must be a non-empty exact string")
        _hex(self.subject_head, length=40, field="subject_head")
        _hex(self.raw_artifact_digest, length=64, field="raw_artifact_digest")
        if self.family not in AGI_HELD_OUT_FAMILIES:
            raise ValueError("unknown held-out family")
        if self.curator_independence not in CURATOR_INDEPENDENCE_STATES:
            raise ValueError("unknown curator independence state")
        if self.training_overlap not in TRAINING_OVERLAP_STATES:
            raise ValueError("unknown training overlap state")
        for field in (
            "held_out",
            "post_disclosure_tuning",
            "developer_item_access",
            "negative_results_preserved",
        ):
            if type(getattr(self, field)) is not bool:
                raise TypeError(f"{field} must be an exact bool")
        if type(self.tool_access) is not tuple or any(
            type(item) is not str or not item for item in self.tool_access
        ):
            raise ValueError("tool_access must be a tuple of non-empty strings")
        for field in ("attempted", "passed", "failed"):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} must be a non-negative exact integer")
        if self.attempted < 1:
            raise ValueError("attempted must be positive")
        if self.passed + self.failed != self.attempted:
            raise ValueError("passed + failed must equal attempted")
        object.__setattr__(
            self,
            "dimension_states",
            _dimension_map(self.dimension_states, allow_partial=True),
        )
        if not self.dimension_states:
            raise ValueError("evaluation packet must target at least one dimension")

    @property
    def independent_evidence_eligible(self) -> bool:
        return (
            self.curator_independence
            in {"INDEPENDENT_MODEL", "INDEPENDENT_HUMAN", "EXTERNAL_BENCHMARK"}
            and self.developer_item_access is False
            and self.training_overlap == "NONE_KNOWN"
            and self.post_disclosure_tuning is False
            and self.held_out is True
            and self.negative_results_preserved is True
        )


def evaluation_packet_defects(packet: AGIEvaluationPacket) -> tuple[str, ...]:
    if type(packet) is not AGIEvaluationPacket:
        raise TypeError("packet must be exact AGIEvaluationPacket")
    defects: list[str] = []
    if not packet.held_out:
        defects.append("probe is not held out")
    if not packet.negative_results_preserved:
        defects.append("negative results were not preserved")
    if packet.post_disclosure_tuning:
        defects.append("post-disclosure tuning invalidates this held-out cut")
    if (
        any(state is DimensionState.PASS for state in packet.dimension_states.values())
        and packet.training_overlap != "NONE_KNOWN"
    ):
        defects.append("training overlap is not NONE_KNOWN for a PASS claim")
    if (
        packet.curator_independence != "DEVELOPER_AUTHORED_HIDDEN_CUT"
        and packet.developer_item_access
    ):
        defects.append(
            "developer item access conflicts with independent curator classification"
        )
    return tuple(defects)


@dataclass(frozen=True, slots=True)
class AGIQualificationAssessment:
    subject_head: str
    dimension_states: Mapping[str, DimensionState]
    aggregate_state: AggregateQualificationState
    independent_review_state: IndependentReviewState
    claim_ceiling: str = "CURRENT_CONTRACT_RESEARCH_QUALIFICATION_ONLY_NOT_AGI"

    def __post_init__(self) -> None:
        _hex(self.subject_head, length=40, field="subject_head")
        object.__setattr__(
            self,
            "dimension_states",
            _dimension_map(self.dimension_states, allow_partial=False),
        )
        if type(self.aggregate_state) is not AggregateQualificationState:
            raise TypeError("aggregate_state must be exact AggregateQualificationState")
        if type(self.independent_review_state) is not IndependentReviewState:
            raise TypeError(
                "independent_review_state must be exact IndependentReviewState"
            )


def aggregate_qualification(
    *,
    subject_head: str,
    dimension_states: Mapping[str, DimensionState],
    independent_review_state: IndependentReviewState,
) -> AGIQualificationAssessment:
    _hex(subject_head, length=40, field="subject_head")
    if type(independent_review_state) is not IndependentReviewState:
        raise TypeError(
            "independent_review_state must be exact IndependentReviewState"
        )
    partial = _dimension_map(dimension_states, allow_partial=True)
    states = {
        dimension: partial.get(dimension, DimensionState.NOT_EVALUATED)
        for dimension in REQUIRED_AGI_DIMENSIONS
    }
    values = tuple(states.values())
    if all(state is DimensionState.NOT_EVALUATED for state in values):
        aggregate = AggregateQualificationState.NOT_EVALUATED
    elif any(state is DimensionState.FAIL for state in values):
        aggregate = AggregateQualificationState.FAILS_CURRENT_CONTRACT
    elif all(state is DimensionState.PASS for state in values):
        if (
            independent_review_state
            is IndependentReviewState.SURVIVES_INDEPENDENT_REVIEW
        ):
            aggregate = (
                AggregateQualificationState
                .SURVIVES_CURRENT_CONTRACT_INDEPENDENTLY_REVIEWED
            )
        else:
            aggregate = AggregateQualificationState.SURVIVES_CURRENT_CONTRACT
    else:
        aggregate = AggregateQualificationState.PARTIALLY_EVALUATED

    return AGIQualificationAssessment(
        subject_head=subject_head,
        dimension_states=states,
        aggregate_state=aggregate,
        independent_review_state=independent_review_state,
    )
