from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ReasoningRequest:
    prompt: str
    unresolved: tuple[str, ...] = ("answer",)
    prior_answer: str | None = None
    iteration: int = 0


@dataclass(frozen=True)
class LayerResult:
    answer: str | None
    unresolved: tuple[str, ...]
    confidence: float
    evidence: tuple[str, ...] = ()
    changed_dimensions: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return bool(self.answer) and not self.unresolved


LayerCallable = Callable[[ReasoningRequest], LayerResult]


@dataclass(frozen=True)
class LayerSpec:
    name: str
    run: LayerCallable
    min_confidence: float = 0.70
    max_iterations: int = 1

    def validate(self) -> None:
        if not self.name:
            raise ValueError("layer name cannot be empty")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")


@dataclass(frozen=True)
class CascadeOutcome:
    answer: str | None
    resolved: bool
    confidence: float
    unresolved: tuple[str, ...]
    layers_used: tuple[str, ...]
    iterations: int
    stop_reason: str
    evidence: tuple[str, ...] = ()


class CascadeEngine:
    """Bounded progressive-depth reasoning with recursive delta refinement.

    Lower-cost layers run first. A layer receives the unresolved dimensions and
    best prior answer, then may refine only while it is making measurable
    progress. Failure to resolve or clear the confidence gate escalates to the
    next layer. "Gradient" here means an explicit error/delta signal over
    unresolved reasoning dimensions; it is not model backpropagation.
    """

    def __init__(self, layers: tuple[LayerSpec, ...], max_total_iterations: int = 8):
        if not layers:
            raise ValueError("at least one reasoning layer is required")
        if max_total_iterations < 1:
            raise ValueError("max_total_iterations must be positive")
        for layer in layers:
            layer.validate()
        self._layers = layers
        self._max_total_iterations = max_total_iterations

    def resolve(self, prompt: str) -> CascadeOutcome:
        if type(prompt) is not str or not prompt.strip():
            raise ValueError("prompt must be a non-empty exact string")

        request = ReasoningRequest(prompt=prompt)
        best: LayerResult | None = None
        used: list[str] = []
        evidence: list[str] = []
        total_iterations = 0

        for layer in self._layers:
            used.append(layer.name)
            previous_unresolved = request.unresolved

            for _ in range(layer.max_iterations):
                if total_iterations >= self._max_total_iterations:
                    return self._finish(
                        best, used, evidence, total_iterations, "iteration_budget_exhausted"
                    )

                result = layer.run(request)
                self._validate_result(result)
                total_iterations += 1
                evidence.extend(item for item in result.evidence if item not in evidence)

                if best is None or self._is_better(result, best):
                    best = result

                if result.resolved and result.confidence >= layer.min_confidence:
                    return self._finish(
                        result, used, evidence, total_iterations, "resolved"
                    )

                progress = self._progress(previous_unresolved, result)
                request = ReasoningRequest(
                    prompt=prompt,
                    unresolved=result.unresolved or previous_unresolved,
                    prior_answer=result.answer or request.prior_answer,
                    iteration=request.iteration + 1,
                )
                previous_unresolved = request.unresolved

                if not progress:
                    break

        return self._finish(best, used, evidence, total_iterations, "layers_exhausted")

    @staticmethod
    def _progress(previous: tuple[str, ...], result: LayerResult) -> bool:
        if result.changed_dimensions:
            return True
        return set(result.unresolved) < set(previous)

    @staticmethod
    def _is_better(candidate: LayerResult, incumbent: LayerResult) -> bool:
        if len(candidate.unresolved) != len(incumbent.unresolved):
            return len(candidate.unresolved) < len(incumbent.unresolved)
        return candidate.confidence > incumbent.confidence

    @staticmethod
    def _validate_result(result: LayerResult) -> None:
        if type(result) is not LayerResult:
            raise TypeError("reasoning layer must return exact LayerResult")
        if not 0.0 <= result.confidence <= 1.0:
            raise ValueError("layer confidence must be in [0, 1]")
        if type(result.unresolved) is not tuple or any(
            type(item) is not str or not item for item in result.unresolved
        ):
            raise ValueError("unresolved must be a tuple of non-empty exact strings")
        if type(result.evidence) is not tuple or any(
            type(item) is not str or not item for item in result.evidence
        ):
            raise ValueError("evidence must be a tuple of non-empty exact strings")
        if type(result.changed_dimensions) is not tuple or any(
            type(item) is not str or not item for item in result.changed_dimensions
        ):
            raise ValueError(
                "changed_dimensions must be a tuple of non-empty exact strings"
            )

    @staticmethod
    def _finish(
        result: LayerResult | None,
        used: list[str],
        evidence: list[str],
        iterations: int,
        reason: str,
    ) -> CascadeOutcome:
        if result is None:
            return CascadeOutcome(
                answer=None,
                resolved=False,
                confidence=0.0,
                unresolved=("answer",),
                layers_used=tuple(used),
                iterations=iterations,
                stop_reason=reason,
                evidence=tuple(evidence),
            )
        return CascadeOutcome(
            answer=result.answer,
            resolved=result.resolved,
            confidence=result.confidence,
            unresolved=result.unresolved,
            layers_used=tuple(used),
            iterations=iterations,
            stop_reason=reason,
            evidence=tuple(evidence),
        )
