"""Prequential evaluation for adaptive or continually learned behavior.

Each case is predicted and scored before that case may update the learner.
Evaluator-only context is retained in the trace and is never supplied to the
predict/update callbacks by this mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class PrequentialCase:
    case_id: str
    model_input: Any
    expected: Any
    evaluator_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.case_id) is not str or not self.case_id:
            raise ValueError("case_id must be a non-empty exact string")
        object.__setattr__(
            self,
            "evaluator_context",
            MappingProxyType(dict(self.evaluator_context)),
        )


@dataclass(frozen=True, slots=True)
class PrequentialStep:
    case_id: str
    prediction: Any
    score: float
    evaluator_context: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evaluator_context",
            MappingProxyType(dict(self.evaluator_context)),
        )


@dataclass(frozen=True, slots=True)
class PrequentialTrace:
    steps: tuple[PrequentialStep, ...]
    evaluation_order: str = "PREDICT_SCORE_THEN_UPDATE"
    authorization_effect: str = "NONE"


def evaluate_prequential(
    cases: Sequence[PrequentialCase],
    *,
    predict: Callable[[Any], Any],
    score: Callable[[Any, Any], float],
    update: Callable[[Any, Any], Any],
) -> PrequentialTrace:
    """Evaluate online adaptation without training on the case before scoring it."""

    steps: list[PrequentialStep] = []
    for case in cases:
        if type(case) is not PrequentialCase:
            raise TypeError("cases must contain exact PrequentialCase values")
        prediction = predict(case.model_input)
        metric = float(score(prediction, case.expected))
        if not math.isfinite(metric):
            raise ValueError("prequential score must be finite")
        steps.append(
            PrequentialStep(
                case_id=case.case_id,
                prediction=prediction,
                score=metric,
                evaluator_context=case.evaluator_context,
            )
        )
        update(case.model_input, case.expected)
    return PrequentialTrace(steps=tuple(steps))
