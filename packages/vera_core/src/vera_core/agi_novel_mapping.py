"""Dimension-specific NOVEL_MAPPING qualification.

This adapter is the only path in this module that may emit PASS. It derives
dimension states from bound learner/baseline raw evidence and explicit
thresholds. Generic evaluation packets remain unable to self-award PASS.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any

from .agi_evaluation import HeldOutProbeResult


_INDEPENDENT_CURATORS = frozenset({
    "INDEPENDENT_MODEL",
    "INDEPENDENT_HUMAN",
    "EXTERNAL_BENCHMARK",
})

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


@dataclass(frozen=True, slots=True)
class NovelMappingThresholds:
    late_window: int
    max_late_mse: float
    threshold_mse: float
    max_samples_to_threshold: int
    min_baseline_delta: float
    min_baseline_ratio: float

    def __post_init__(self) -> None:
        if type(self.late_window) is not int or self.late_window < 1:
            raise ValueError("late_window must be a positive exact int")
        if (
            type(self.max_samples_to_threshold) is not int
            or self.max_samples_to_threshold < 1
        ):
            raise ValueError(
                "max_samples_to_threshold must be a positive exact int"
            )
        for name in (
            "max_late_mse",
            "threshold_mse",
            "min_baseline_delta",
            "min_baseline_ratio",
        ):
            value = _finite_number(getattr(self, name), field=name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if self.min_baseline_ratio < 1.0:
            raise ValueError("min_baseline_ratio must be at least 1")


@dataclass(frozen=True, slots=True)
class NovelMappingMetrics:
    learner_mse_curve: tuple[float, ...]
    baseline_mse_curve: tuple[float, ...]
    late_mse: float
    baseline_late_mse: float
    samples_to_threshold: int | None
    baseline_delta: float
    baseline_ratio: float


@dataclass(frozen=True, slots=True)
class NovelMappingQualificationResult:
    metrics: NovelMappingMetrics
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


def _mse_curve(raw: dict[str, Any]) -> tuple[float, ...]:
    attempts = raw.get("attempts")
    if type(attempts) is not list or not attempts:
        raise ValueError("held-out raw artifact has no attempts")
    curve: list[float] = []
    for index, attempt in enumerate(attempts):
        if type(attempt) is not dict:
            raise TypeError("held-out attempt must be an object")
        prediction = _finite_number(
            attempt.get("prediction"),
            field=f"attempt[{index}].prediction",
        )
        expected = _finite_number(
            attempt.get("expected"),
            field=f"attempt[{index}].expected",
        )
        curve.append((prediction - expected) ** 2)
    return tuple(curve)


def _state(*, metrics_pass: bool, independent: bool) -> str:
    if not metrics_pass:
        return "FAIL"
    if independent:
        return "PASS"
    return "PARTIAL"


def qualify_novel_mapping(
    learned: HeldOutProbeResult,
    *,
    baseline: HeldOutProbeResult,
    thresholds: NovelMappingThresholds,
    repository: str,
    exact_head: str,
    runtime_binding: str,
    claim_ceiling: str,
) -> NovelMappingQualificationResult:
    """Qualify adaptation on one bound held-out NOVEL_MAPPING cut."""

    if type(learned) is not HeldOutProbeResult:
        raise TypeError("learned must be exact HeldOutProbeResult")
    if type(baseline) is not HeldOutProbeResult:
        raise TypeError("baseline must be exact HeldOutProbeResult")
    if type(thresholds) is not NovelMappingThresholds:
        raise TypeError("thresholds must be exact NovelMappingThresholds")
    if learned.family != "NOVEL_MAPPING" or baseline.family != "NOVEL_MAPPING":
        raise ValueError("NOVEL_MAPPING qualification requires NOVEL_MAPPING results")
    if (
        learned.probe_id != baseline.probe_id
        or learned.items_digest != baseline.items_digest
        or learned.attempted != baseline.attempted
    ):
        raise ValueError("learner and baseline must use the same held-out cut")
    if learned.curator_independence != baseline.curator_independence:
        raise ValueError("learner and baseline curator classifications differ")
    if learned.contamination != baseline.contamination:
        raise ValueError("learner and baseline contamination disclosures differ")
    if type(repository) is not str or not repository:
        raise ValueError("repository must be a non-empty exact string")
    _exact_head(exact_head)
    if runtime_binding not in _RUNTIME_BINDINGS:
        raise ValueError("unsupported runtime_binding")
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    learned_raw = _raw(learned)
    baseline_raw = _raw(baseline)
    if learned_raw.get("evaluation_order") != "PREDICT_SCORE_THEN_UPDATE":
        raise ValueError(
            "NOVEL_MAPPING learner evidence must be prequential "
            "PREDICT_SCORE_THEN_UPDATE"
        )
    if learned.attempted < thresholds.late_window:
        raise ValueError("held-out cut is shorter than late_window")

    learner_curve = _mse_curve(learned_raw)
    baseline_curve = _mse_curve(baseline_raw)
    if len(learner_curve) != len(baseline_curve):
        raise ValueError("learner and baseline attempt counts differ")

    late = learner_curve[-thresholds.late_window :]
    baseline_late = baseline_curve[-thresholds.late_window :]
    late_mse = sum(late) / len(late)
    baseline_late_mse = sum(baseline_late) / len(baseline_late)
    samples_to_threshold = next(
        (
            index
            for index, mse in enumerate(learner_curve, start=1)
            if mse <= thresholds.threshold_mse
        ),
        None,
    )
    baseline_delta = baseline_late_mse - late_mse
    baseline_ratio = baseline_late_mse / max(late_mse, 1e-15)

    metrics = NovelMappingMetrics(
        learner_mse_curve=learner_curve,
        baseline_mse_curve=baseline_curve,
        late_mse=late_mse,
        baseline_late_mse=baseline_late_mse,
        samples_to_threshold=samples_to_threshold,
        baseline_delta=baseline_delta,
        baseline_ratio=baseline_ratio,
    )

    disclosure = learned.contamination
    independent = (
        learned.curator_independence in _INDEPENDENT_CURATORS
        and disclosure.training_overlap == "NONE_KNOWN"
        and disclosure.post_disclosure_tuning is False
        and disclosure.developer_item_access is False
        and disclosure.tool_access == ()
        and learned.negative_results_preserved is True
        and baseline.negative_results_preserved is True
    )

    transfer_metrics_pass = (
        late_mse <= thresholds.max_late_mse
        and baseline_delta >= thresholds.min_baseline_delta
        and baseline_ratio >= thresholds.min_baseline_ratio
    )
    efficiency_metrics_pass = (
        late_mse <= thresholds.max_late_mse
        and samples_to_threshold is not None
        and samples_to_threshold <= thresholds.max_samples_to_threshold
    )
    dimension_states = {
        "NOVEL_TASK_TRANSFER": _state(
            metrics_pass=transfer_metrics_pass,
            independent=independent,
        ),
        "LEARNING_EFFICIENCY": _state(
            metrics_pass=efficiency_metrics_pass,
            independent=independent,
        ),
    }

    artifact = {
        "schema": "VERA_AGI_NOVEL_MAPPING_QUALIFICATION_V1",
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
        "independent_evidence_gate": independent,
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

    return NovelMappingQualificationResult(
        metrics=metrics,
        packet=packet,
        qualification_artifact_json=artifact_json,
        qualification_artifact_digest=artifact_digest,
    )
