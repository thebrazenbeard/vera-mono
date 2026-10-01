"""Evidence-bound rival-hypothesis resolution.

Adapted from thebrazenbeard/voss@36a623d3a158e5aef521d42e378bafacd67d3de5.
The mechanism keeps multiple live explanations explicit, deduplicates support
by independence group, allows contradiction to eliminate a declared rival, and
returns a concrete discrimination requirement instead of manufacturing closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RivalHypothesisError(ValueError):
    pass


class RivalResolutionState(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"


def _text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise RivalHypothesisError(f"{label} must be a non-empty exact string")
    return value


@dataclass(frozen=True, slots=True)
class RivalHypothesis:
    hypothesis_id: str
    proposition: str

    def __post_init__(self) -> None:
        _text(self.hypothesis_id, "hypothesis_id")
        _text(self.proposition, "proposition")


@dataclass(frozen=True, slots=True)
class RivalEvidence:
    evidence_id: str
    independence_key: str
    supports: frozenset[str] = frozenset()
    contradicts: frozenset[str] = frozenset()
    admissible: bool = True

    def __post_init__(self) -> None:
        _text(self.evidence_id, "evidence_id")
        _text(self.independence_key, "independence_key")
        if type(self.supports) is not frozenset:
            raise RivalHypothesisError("supports must be a frozenset")
        if type(self.contradicts) is not frozenset:
            raise RivalHypothesisError("contradicts must be a frozenset")
        for item in self.supports:
            _text(item, "supports hypothesis id")
        for item in self.contradicts:
            _text(item, "contradicts hypothesis id")
        if type(self.admissible) is not bool:
            raise RivalHypothesisError("admissible must be bool")


@dataclass(frozen=True, slots=True)
class RivalHypothesisAssessment:
    hypothesis_id: str
    support_groups: tuple[str, ...]
    contradiction_groups: tuple[str, ...]
    eliminated: bool


@dataclass(frozen=True, slots=True)
class RivalResolution:
    state: RivalResolutionState
    winner: str | None
    live_hypotheses: tuple[str, ...]
    assessments: tuple[RivalHypothesisAssessment, ...]
    discriminating_need: tuple[str, ...]


def resolve_rival_hypotheses(
    hypotheses: tuple[RivalHypothesis, ...],
    evidence: tuple[RivalEvidence, ...],
) -> RivalResolution:
    if not hypotheses:
        raise RivalHypothesisError("at least one hypothesis is required")

    hypothesis_ids = [item.hypothesis_id for item in hypotheses]
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        raise RivalHypothesisError("hypothesis ids must be unique")

    evidence_ids = [item.evidence_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise RivalHypothesisError("evidence ids must be unique")

    known = set(hypothesis_ids)
    for item in evidence:
        unknown = (item.supports | item.contradicts) - known
        if unknown:
            raise RivalHypothesisError(
                "evidence references unknown hypotheses: "
                + ", ".join(sorted(unknown))
            )

    assessments: list[RivalHypothesisAssessment] = []
    for hypothesis in hypotheses:
        support_groups = {
            item.independence_key
            for item in evidence
            if item.admissible
            and hypothesis.hypothesis_id in item.supports
        }
        contradiction_groups = {
            item.independence_key
            for item in evidence
            if item.admissible
            and hypothesis.hypothesis_id in item.contradicts
        }
        assessments.append(
            RivalHypothesisAssessment(
                hypothesis_id=hypothesis.hypothesis_id,
                support_groups=tuple(sorted(support_groups)),
                contradiction_groups=tuple(sorted(contradiction_groups)),
                eliminated=bool(contradiction_groups),
            )
        )

    live = tuple(item for item in assessments if not item.eliminated)
    if not live:
        return RivalResolution(
            state=RivalResolutionState.CONFLICT,
            winner=None,
            live_hypotheses=(),
            assessments=tuple(assessments),
            discriminating_need=(
                "expand_or_repair_hypothesis_set",
            ),
        )

    supported_live = tuple(item for item in live if item.support_groups)
    if len(live) == 1 and len(supported_live) == 1:
        return RivalResolution(
            state=RivalResolutionState.SUPPORTED,
            winner=live[0].hypothesis_id,
            live_hypotheses=(live[0].hypothesis_id,),
            assessments=tuple(assessments),
            discriminating_need=(),
        )

    live_ids = tuple(item.hypothesis_id for item in live)
    return RivalResolution(
        state=RivalResolutionState.UNRESOLVED,
        winner=None,
        live_hypotheses=live_ids,
        assessments=tuple(assessments),
        discriminating_need=live_ids,
    )
