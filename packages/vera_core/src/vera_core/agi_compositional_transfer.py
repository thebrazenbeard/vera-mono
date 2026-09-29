"""Narrow compositional-transfer research frontier.

This module demonstrates one falsifiable capability only: infer simple affine
primitive transforms from singleton examples and compose those learned
primitives in unseen multi-step programs.

Measurement is deliberately capped below PASS. A later runtime-bound
independent-review adapter is required to promote any qualifying evidence.
Single-domain composition does not establish cross-domain breadth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

from .agi_evaluation import HeldOutProbeResult


_RUNTIME_BINDINGS = frozenset({
    "SOURCE_ONLY",
    "LOCAL_TEST_RUNTIME",
    "QUALIFIED_RUNTIME",
})


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _exact_head(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            "exact_head must be 40 lowercase hexadecimal characters"
        )


def _finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


class AffinePrimitiveLearner:
    """Learn y = a*x + b primitives from singleton examples."""

    def __init__(self) -> None:
        self._observations: dict[str, list[tuple[float, float]]] = {}
        self._parameters: dict[str, tuple[float, float]] = {}

    @property
    def seen_programs(self) -> frozenset[tuple[str, ...]]:
        # Composed programs are never training inputs in this frontier.
        return frozenset()

    def observe(self, primitive: str, *, x: float, y: float) -> None:
        if type(primitive) is not str or not primitive:
            raise ValueError("primitive must be a non-empty exact string")
        x = _finite_number(x, field="x")
        y = _finite_number(y, field="y")

        observations = self._observations.setdefault(primitive, [])
        observations.append((x, y))

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

        for ox, oy in observations:
            predicted = slope * ox + intercept
            if not math.isclose(
                predicted,
                oy,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    f"primitive {primitive!r} observations are not "
                    "affine-consistent"
                )

        self._parameters[primitive] = (slope, intercept)

    def predict(self, program: tuple[str, ...], x: float) -> float:
        if type(program) is not tuple or not program:
            raise ValueError("program must be a non-empty exact tuple")
        if any(type(item) is not str or not item for item in program):
            raise ValueError(
                "program primitives must be non-empty exact strings"
            )
        value = _finite_number(x, field="input")

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

    def observe(
        self,
        program: tuple[str, ...],
        *,
        x: float,
        y: float,
    ) -> None:
        if type(program) is not tuple or not program:
            raise ValueError("program must be a non-empty exact tuple")
        if any(type(item) is not str or not item for item in program):
            raise ValueError(
                "program primitives must be non-empty exact strings"
            )
        x = _finite_number(x, field="x")
        y = _finite_number(y, field="y")
        self._examples[(program, x)] = y

    def predict(
        self,
        program: tuple[str, ...],
        x: float,
    ) -> float | None:
        x = _finite_number(x, field="input")
        return self._examples.get((program, x))


@dataclass(frozen=True, slots=True)
class CompositionalTransferThresholds:
    absolute_tolerance: float
    min_unseen_success_rate: float
    min_ablation_delta: float

    def __post_init__(self) -> None:
        tolerance = _finite_number(
            self.absolute_tolerance,
            field="absolute_tolerance",
        )
        if tolerance < 0.0:
            raise ValueError("absolute_tolerance must be non-negative")
        for name in (
            "min_unseen_success_rate",
            "min_ablation_delta",
        ):
            value = _finite_number(getattr(self, name), field=name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CompositionalTransferMetrics:
    unseen_composition_success_rate: float
    baseline_success_rate: float
    ablation_delta: float
    error_taxonomy: dict[str, int]


@dataclass(frozen=True, slots=True)
class CompositionalTransferQualificationResult:
    metrics: CompositionalTransferMetrics
    packet: dict[str, object]
    qualification_artifact_json: str
    qualification_artifact_digest: str


def _raw(result: HeldOutProbeResult) -> dict[str, Any]:
    try:
        value = json.loads(result.raw_artifact_json)
    except json.JSONDecodeError as exc:
        raise ValueError("held-out raw artifact is not valid JSON") from exc
    if type(value) is not dict:
        raise TypeError("held-out raw artifact must decode to an object")
    return value


def _prediction_correct(
    prediction: Any,
    expected: Any,
    *,
    absolute_tolerance: float,
) -> bool:
    if prediction is None:
        return False
    predicted = _finite_number(prediction, field="prediction")
    target = _finite_number(expected, field="expected")
    return abs(predicted - target) <= absolute_tolerance


def _measurement_state(*, metrics_pass: bool) -> str:
    return "PARTIAL" if metrics_pass else "FAIL"


def qualify_compositional_transfer(
    learned: HeldOutProbeResult,
    *,
    baseline: HeldOutProbeResult,
    thresholds: CompositionalTransferThresholds,
    repository: str,
    exact_head: str,
    runtime_binding: str,
    claim_ceiling: str,
) -> CompositionalTransferQualificationResult:
    """Measure unseen composition against an exact-example baseline."""

    if type(learned) is not HeldOutProbeResult:
        raise TypeError("learned must be exact HeldOutProbeResult")
    if type(baseline) is not HeldOutProbeResult:
        raise TypeError("baseline must be exact HeldOutProbeResult")
    if type(thresholds) is not CompositionalTransferThresholds:
        raise TypeError(
            "thresholds must be exact CompositionalTransferThresholds"
        )
    if (
        learned.family != "COMPOSITIONAL_TRANSFER"
        or baseline.family != "COMPOSITIONAL_TRANSFER"
    ):
        raise ValueError(
            "compositional qualification requires COMPOSITIONAL_TRANSFER "
            "results"
        )
    if (
        learned.probe_id != baseline.probe_id
        or learned.items_digest != baseline.items_digest
        or learned.attempted != baseline.attempted
    ):
        raise ValueError(
            "learner and baseline must use the same held-out cut"
        )
    if learned.curator_independence != baseline.curator_independence:
        raise ValueError(
            "learner and baseline curator classifications differ"
        )
    if learned.contamination != baseline.contamination:
        raise ValueError(
            "learner and baseline contamination disclosures differ"
        )
    if type(repository) is not str or not repository:
        raise ValueError("repository must be a non-empty exact string")
    _exact_head(exact_head)
    if runtime_binding not in _RUNTIME_BINDINGS:
        raise ValueError("unsupported runtime_binding")
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    learned_raw = _raw(learned)
    baseline_raw = _raw(baseline)
    learned_attempts = learned_raw.get("attempts")
    baseline_attempts = baseline_raw.get("attempts")
    if (
        type(learned_attempts) is not list
        or type(baseline_attempts) is not list
        or not learned_attempts
        or len(learned_attempts) != len(baseline_attempts)
    ):
        raise ValueError(
            "learner and baseline raw attempts must match in length"
        )

    taxonomy = {
        "CORRECT": 0,
        "UNRESOLVED": 0,
        "WRONG": 0,
    }
    learner_correct = 0
    baseline_correct = 0

    for index, (learner_attempt, baseline_attempt) in enumerate(
        zip(learned_attempts, baseline_attempts, strict=True)
    ):
        if type(learner_attempt) is not dict:
            raise TypeError("learner attempt must be an object")
        if type(baseline_attempt) is not dict:
            raise TypeError("baseline attempt must be an object")
        if (
            learner_attempt.get("case_id")
            != baseline_attempt.get("case_id")
        ):
            raise ValueError(
                "learner and baseline raw attempts are misaligned"
            )

        prediction = learner_attempt.get("prediction")
        expected = learner_attempt.get("expected")
        if prediction is None:
            taxonomy["UNRESOLVED"] += 1
        elif _prediction_correct(
            prediction,
            expected,
            absolute_tolerance=thresholds.absolute_tolerance,
        ):
            taxonomy["CORRECT"] += 1
            learner_correct += 1
        else:
            _finite_number(
                prediction,
                field=f"learner[{index}].prediction",
            )
            _finite_number(
                expected,
                field=f"learner[{index}].expected",
            )
            taxonomy["WRONG"] += 1

        baseline_prediction = baseline_attempt.get("prediction")
        baseline_expected = baseline_attempt.get("expected")
        if baseline_prediction is not None and _prediction_correct(
            baseline_prediction,
            baseline_expected,
            absolute_tolerance=thresholds.absolute_tolerance,
        ):
            baseline_correct += 1

    attempted = len(learned_attempts)
    learner_rate = learner_correct / attempted
    baseline_rate = baseline_correct / attempted
    delta = learner_rate - baseline_rate
    metrics = CompositionalTransferMetrics(
        unseen_composition_success_rate=learner_rate,
        baseline_success_rate=baseline_rate,
        ablation_delta=delta,
        error_taxonomy=taxonomy,
    )

    metrics_pass = (
        learner_rate >= thresholds.min_unseen_success_rate
        and delta >= thresholds.min_ablation_delta
    )
    dimension_states = {
        "NOVEL_TASK_TRANSFER": _measurement_state(
            metrics_pass=metrics_pass,
        ),
        "CROSS_DOMAIN_BREADTH": _measurement_state(
            metrics_pass=metrics_pass,
        ),
    }

    disclosure = learned.contamination
    artifact = {
        "schema": "VERA_AGI_COMPOSITIONAL_TRANSFER_QUALIFICATION_V1",
        "probe_id": learned.probe_id,
        "items_digest": learned.items_digest,
        "curator_independence": learned.curator_independence,
        "contamination": {
            "training_overlap": disclosure.training_overlap,
            "post_disclosure_tuning": disclosure.post_disclosure_tuning,
            "developer_item_access": disclosure.developer_item_access,
            "tool_access": list(disclosure.tool_access),
        },
        "thresholds": asdict(thresholds),
        "metrics": asdict(metrics),
        "learner_raw_artifact_digest": learned.raw_artifact_digest,
        "baseline_raw_artifact_digest": baseline.raw_artifact_digest,
        "learner_raw_artifact": learned_raw,
        "baseline_raw_artifact": baseline_raw,
        "measurement_only": True,
        "independent_review_required_for_pass": True,
        "single_domain_breadth_ceiling": True,
        "dimension_states": dimension_states,
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
            "probe_id": learned.probe_id,
            "family": learned.family,
            "held_out": True,
            "curator_independence": learned.curator_independence,
            "items_digest": learned.items_digest,
        },
        "contamination": {
            "training_overlap": disclosure.training_overlap,
            "post_disclosure_tuning": disclosure.post_disclosure_tuning,
            "developer_item_access": disclosure.developer_item_access,
            "tool_access": list(disclosure.tool_access),
        },
        "results": {
            "attempted": learned.attempted,
            "passed": learned.passed,
            "failed": learned.failed,
            "raw_artifact_digest": artifact_digest,
            "negative_results_preserved": True,
        },
        "dimension_states": dimension_states,
        "independent_review": None,
        "claim_ceiling": claim_ceiling,
    }

    return CompositionalTransferQualificationResult(
        metrics=metrics,
        packet=packet,
        qualification_artifact_json=artifact_json,
        qualification_artifact_digest=artifact_digest,
    )
