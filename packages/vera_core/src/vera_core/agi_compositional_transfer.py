"""Narrow compositional-transfer research frontier.

This module demonstrates one falsifiable capability only: infer simple affine
primitive transforms from singleton examples and compose those learned
primitives in unseen multi-step programs.

It does not establish cross-domain breadth by itself. Even independently
curated single-domain evidence is capped at PARTIAL for CROSS_DOMAIN_BREADTH.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


class AffinePrimitiveLearner:
    """Learn y = a*x + b primitives from observed singleton examples."""

    def __init__(self) -> None:
        self._observations: dict[str, list[tuple[float, float]]] = {}
        self._parameters: dict[str, tuple[float, float]] = {}

    @property
    def seen_programs(self) -> frozenset[tuple[str, ...]]:
        # This learner never trains on composed programs in this frontier.
        return frozenset()

    def observe(self, primitive: str, *, x: float, y: float) -> None:
        if type(primitive) is not str or not primitive:
            raise ValueError("primitive must be a non-empty exact string")
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("primitive observations must be finite")

        observations = self._observations.setdefault(primitive, [])
        observations.append((float(x), float(y)))

        # Find the first identifiable pair with distinct x values.
        pair: tuple[tuple[float, float], tuple[float, float]] | None = None
        for left_index, left in enumerate(observations):
            for right in observations[left_index + 1 :]:
                if left[0] != right[0]:
                    pair = (left, right)
                    break
            if pair is not None:
                break

        if pair is None:
            self._parameters.pop(primitive, None)
            return

        (x1, y1), (x2, y2) = pair
        slope = (y2 - y1) / (x2 - x1)
        intercept = y1 - slope * x1

        # Reject contradictory later evidence rather than silently fitting it.
        for ox, oy in observations:
            predicted = slope * ox + intercept
            if not math.isclose(predicted, oy, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(
                    f"primitive {primitive!r} observations are not affine-consistent"
                )

        self._parameters[primitive] = (slope, intercept)

    def predict(self, program: tuple[str, ...], x: float) -> float:
        if type(program) is not tuple or not program:
            raise ValueError("program must be a non-empty exact tuple")
        if any(type(item) is not str or not item for item in program):
            raise ValueError("program primitives must be non-empty exact strings")
        if not math.isfinite(x):
            raise ValueError("input must be finite")

        value = float(x)
        for primitive in program:
            parameters = self._parameters.get(primitive)
            if parameters is None:
                raise ValueError(f"primitive {primitive!r} is not identified")
            slope, intercept = parameters
            value = slope * value + intercept
        return value


class PrimitiveProgramMemorizer:
    """Exact-example memorizer baseline with no compositional ability."""

    def __init__(self) -> None:
        self._examples: dict[tuple[tuple[str, ...], float], float] = {}

    def observe(self, program: tuple[str, ...], *, x: float, y: float) -> None:
        if type(program) is not tuple or not program:
            raise ValueError("program must be a non-empty exact tuple")
        if any(type(item) is not str or not item for item in program):
            raise ValueError("program primitives must be non-empty exact strings")
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("memorizer observations must be finite")
        self._examples[(program, float(x))] = float(y)

    def predict(self, program: tuple[str, ...], x: float) -> float | None:
        return self._examples.get((program, float(x)))


@dataclass(frozen=True, slots=True)
class CompositionalTransferQualification:
    unseen_composition_success_rate: float
    baseline_success_rate: float
    ablation_delta: float
    error_taxonomy: dict[str, int]
    dimension_states: dict[str, str]
    claim_ceiling: str = "COMPOSITIONAL_TRANSFER_DIMENSION_EVIDENCE_ONLY_NOT_AGI"
    authorization_effect: str = "NONE"


def _is_correct(
    prediction: float | None,
    expected: float,
    *,
    absolute_tolerance: float,
) -> bool:
    return (
        prediction is not None
        and math.isfinite(prediction)
        and math.isfinite(expected)
        and abs(prediction - expected) <= absolute_tolerance
    )


def qualify_compositional_transfer(
    *,
    learner_predictions: Iterable[float | None],
    expected: Iterable[float],
    baseline_predictions: Iterable[float | None],
    absolute_tolerance: float,
    min_unseen_success_rate: float,
    min_ablation_delta: float,
    curator_independence: str,
    developer_item_access: bool,
) -> CompositionalTransferQualification:
    learner = tuple(learner_predictions)
    targets = tuple(expected)
    baseline = tuple(baseline_predictions)

    if not learner or len(learner) != len(targets) or len(baseline) != len(targets):
        raise ValueError("prediction/expected lengths must match and be non-empty")
    if not math.isfinite(absolute_tolerance) or absolute_tolerance < 0.0:
        raise ValueError("absolute_tolerance must be finite and non-negative")
    if not 0.0 <= min_unseen_success_rate <= 1.0:
        raise ValueError("min_unseen_success_rate must be in [0, 1]")
    if not 0.0 <= min_ablation_delta <= 1.0:
        raise ValueError("min_ablation_delta must be in [0, 1]")
    if type(curator_independence) is not str or not curator_independence:
        raise ValueError("curator_independence must be a non-empty exact string")
    if type(developer_item_access) is not bool:
        raise TypeError("developer_item_access must be bool")
    if any(not math.isfinite(value) for value in targets):
        raise ValueError("expected values must be finite")

    taxonomy = {"CORRECT": 0, "UNRESOLVED": 0, "WRONG": 0}
    learner_correct = 0
    baseline_correct = 0

    for prediction, target in zip(learner, targets, strict=True):
        if prediction is None:
            taxonomy["UNRESOLVED"] += 1
        elif _is_correct(
            prediction,
            target,
            absolute_tolerance=absolute_tolerance,
        ):
            taxonomy["CORRECT"] += 1
            learner_correct += 1
        else:
            if not math.isfinite(prediction):
                raise ValueError("learner predictions must be finite or None")
            taxonomy["WRONG"] += 1

    for prediction, target in zip(baseline, targets, strict=True):
        if prediction is not None and not math.isfinite(prediction):
            raise ValueError("baseline predictions must be finite or None")
        if _is_correct(
            prediction,
            target,
            absolute_tolerance=absolute_tolerance,
        ):
            baseline_correct += 1

    count = len(targets)
    learner_rate = learner_correct / count
    baseline_rate = baseline_correct / count
    delta = learner_rate - baseline_rate
    metrics_clear = (
        learner_rate >= min_unseen_success_rate
        and delta >= min_ablation_delta
    )

    if not metrics_clear:
        states = {
            "NOVEL_TASK_TRANSFER": "FAIL",
            "CROSS_DOMAIN_BREADTH": "FAIL",
        }
    else:
        independently_curated = (
            curator_independence
            in {"INDEPENDENT_MODEL", "INDEPENDENT_HUMAN", "EXTERNAL_BENCHMARK"}
            and developer_item_access is False
        )
        states = {
            "NOVEL_TASK_TRANSFER": (
                "PASS" if independently_curated else "PARTIAL"
            ),
            # This frontier is intentionally single-domain.
            "CROSS_DOMAIN_BREADTH": "PARTIAL",
        }

    return CompositionalTransferQualification(
        unseen_composition_success_rate=learner_rate,
        baseline_success_rate=baseline_rate,
        ablation_delta=delta,
        error_taxonomy=taxonomy,
        dimension_states=states,
    )
