"""Bounded causal-hypothesis ambiguity assessment.

Adapted from Fuckup's ambiguity layer. The output only selects an evidence or
correction route. It does not authorize an external effect or establish a
causal hypothesis as truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class AmbiguityRoute(StrEnum):
    PROCEED_TO_CORRECTION = "PROCEED_TO_CORRECTION"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass(frozen=True, slots=True)
class CausalHypothesis:
    hypothesis_id: str
    proposition: str
    support: float
    evidence_refs: tuple[str, ...] = ()
    counterevidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.hypothesis_id) is not str or not self.hypothesis_id:
            raise ValueError(
                "hypothesis_id must be a non-empty exact string"
            )
        if type(self.proposition) is not str or not self.proposition:
            raise ValueError("proposition must be a non-empty exact string")
        if isinstance(self.support, bool) or not isinstance(
            self.support, (int, float)
        ):
            raise ValueError("support must be a finite number in [0, 1]")
        if not math.isfinite(float(self.support)) or not 0.0 <= float(
            self.support
        ) <= 1.0:
            raise ValueError("support must be a finite number in [0, 1]")
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(
            self,
            "counterevidence_refs",
            tuple(self.counterevidence_refs),
        )
        for label in ("evidence_refs", "counterevidence_refs"):
            values = getattr(self, label)
            if any(type(item) is not str or not item for item in values):
                raise ValueError(
                    f"{label} must contain non-empty exact strings"
                )
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class CausalAmbiguityAssessment:
    ranked: tuple[CausalHypothesis, ...]
    ambiguous: bool
    reason: str | None
    decision_margin: float | None
    missing_evidence: tuple[str, ...]
    authorization_effect: str = "NONE"

    @property
    def top(self) -> CausalHypothesis | None:
        return self.ranked[0] if self.ranked else None


def assess_causal_ambiguity(
    hypotheses: tuple[CausalHypothesis, ...],
    *,
    minimum_support: float = 0.70,
    minimum_margin: float = 0.15,
    missing_evidence: tuple[str, ...] = (),
) -> CausalAmbiguityAssessment:
    hypotheses = tuple(hypotheses)
    if any(type(item) is not CausalHypothesis for item in hypotheses):
        raise TypeError(
            "hypotheses must contain exact CausalHypothesis values"
        )
    for label, value in (
        ("minimum_support", minimum_support),
        ("minimum_margin", minimum_margin),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a finite number in [0, 1]")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{label} must be a finite number in [0, 1]")

    missing_evidence = tuple(missing_evidence)
    if any(
        type(item) is not str or not item for item in missing_evidence
    ):
        raise ValueError(
            "missing_evidence must contain non-empty exact strings"
        )
    if len(missing_evidence) != len(set(missing_evidence)):
        raise ValueError("missing_evidence must not contain duplicates")

    ranked = tuple(
        sorted(
            hypotheses,
            key=lambda item: (-float(item.support), item.hypothesis_id),
        )
    )
    if not ranked:
        return CausalAmbiguityAssessment(
            ranked=(),
            ambiguous=True,
            reason="no causal hypothesis is available",
            decision_margin=None,
            missing_evidence=missing_evidence,
        )

    top = ranked[0]
    margin = (
        None
        if len(ranked) == 1
        else round(float(top.support) - float(ranked[1].support), 12)
    )
    if float(top.support) < float(minimum_support):
        return CausalAmbiguityAssessment(
            ranked=ranked,
            ambiguous=True,
            reason="top hypothesis is below minimum support",
            decision_margin=margin,
            missing_evidence=missing_evidence,
        )

    if margin is not None and margin < float(minimum_margin):
        return CausalAmbiguityAssessment(
            ranked=ranked,
            ambiguous=True,
            reason="competing hypotheses are too close to resolve safely",
            decision_margin=margin,
            missing_evidence=missing_evidence,
        )

    return CausalAmbiguityAssessment(
        ranked=ranked,
        ambiguous=False,
        reason=None,
        decision_margin=margin,
        missing_evidence=missing_evidence,
    )


def route_causal_ambiguity(
    assessment: CausalAmbiguityAssessment,
    *,
    human_review_when_missing_evidence: bool = False,
) -> AmbiguityRoute:
    if type(assessment) is not CausalAmbiguityAssessment:
        raise TypeError(
            "assessment must be exact CausalAmbiguityAssessment"
        )
    if type(human_review_when_missing_evidence) is not bool:
        raise TypeError(
            "human_review_when_missing_evidence must be an exact bool"
        )
    if assessment.ambiguous:
        if (
            human_review_when_missing_evidence
            and assessment.missing_evidence
        ):
            return AmbiguityRoute.HUMAN_REVIEW
        return AmbiguityRoute.COLLECT_EVIDENCE
    return AmbiguityRoute.PROCEED_TO_CORRECTION
