"""Minimal online learner for falsifiable adaptation/retention experiments.

Adapted from the learning question exercised by Noema's recurrent Gaussian
candidate, not copied as a runtime dependency. Vera's existing prequential
evaluator remains the authority for predict-score-update ordering.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class OnlineLinearPredictor:
    """One-output linear predictor updated only after scoring."""

    dimension: int
    learning_rate: float
    weights: list[float]

    @classmethod
    def zeros(cls, *, dimension: int, learning_rate: float) -> "OnlineLinearPredictor":
        if dimension < 1:
            raise ValueError("dimension must be at least 1")
        if not math.isfinite(learning_rate) or not 0.0 < learning_rate <= 1.0:
            raise ValueError("learning_rate must be in (0, 1]")
        return cls(dimension, learning_rate, [0.0] * dimension)

    def predict(self, features: tuple[float, ...]) -> float:
        self._check_features(features)
        return sum(w * x for w, x in zip(self.weights, features, strict=True))

    def update(self, features: tuple[float, ...], expected: float) -> None:
        self._check_features(features)
        if not math.isfinite(expected):
            raise ValueError("expected must be finite")
        error = expected - self.predict(features)
        for index, value in enumerate(features):
            self.weights[index] += self.learning_rate * error * value

    def snapshot(self) -> tuple[float, ...]:
        return tuple(self.weights)

    def _check_features(self, features: tuple[float, ...]) -> None:
        if len(features) != self.dimension:
            raise ValueError("feature dimension mismatch")
        if not all(math.isfinite(value) for value in features):
            raise ValueError("features must be finite")


def squared_error(prediction: float, expected: float) -> float:
    if not math.isfinite(prediction) or not math.isfinite(expected):
        raise ValueError("score inputs must be finite")
    return (prediction - expected) ** 2


class ContextualOnlineLinearPredictor(OnlineLinearPredictor):
    """Small context-bank learner adapted from LGCM's expert-switching mechanism."""

    def __init__(self, dimension: int, learning_rate: float, weights: list[float]):
        super().__init__(dimension, learning_rate, weights)
        self._experts: list[list[float]] = [list(weights)]
        self._evidence: list[int] = [0]
        self._active = 0
        self._warmup = 8
        self._mismatch = 0.25
        self._switch_margin = 0.05
        self._max_contexts = 8

    def predict(self, features: tuple[float, ...]) -> float:
        self._check_features(features)
        weights = self._experts[self._active]
        return sum(w * x for w, x in zip(weights, features, strict=True))

    def update(self, features: tuple[float, ...], expected: float) -> None:
        self._check_features(features)
        if not math.isfinite(expected):
            raise ValueError("expected must be finite")
        errors = [
            abs(expected - sum(w * x for w, x in zip(ws, features, strict=True)))
            for ws in self._experts
        ]
        active_error = errors[self._active]
        if self._evidence[self._active] >= self._warmup and active_error > self._mismatch:
            alternatives = [
                (error, index)
                for index, error in enumerate(errors)
                if index != self._active and self._evidence[index] >= self._warmup
            ]
            if alternatives:
                best_error, best = min(alternatives)
                if best_error + self._switch_margin < active_error:
                    self._active = best
            if self._active == len(errors) - 1 and len(self._experts) == 1:
                self._spawn_context()
            elif self._active == errors.index(active_error) and len(self._experts) < self._max_contexts:
                self._spawn_context()

        weights = self._experts[self._active]
        prediction = sum(w * x for w, x in zip(weights, features, strict=True))
        error = expected - prediction
        for index, value in enumerate(features):
            weights[index] += self.learning_rate * error * value
        self._evidence[self._active] += 1
        self.weights = weights

    def _spawn_context(self) -> None:
        self._experts.append([0.0] * self.dimension)
        self._evidence.append(0)
        self._active = len(self._experts) - 1

    @property
    def context_count(self) -> int:
        return len(self._experts)

    def snapshot(self) -> tuple[float, ...]:
        return tuple(self._experts[self._active])
