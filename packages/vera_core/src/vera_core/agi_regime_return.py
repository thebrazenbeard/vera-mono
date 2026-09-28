"""Bound REGIME_RETURN measurement for retention/interference research.

The measurement consumes prequential traces only. It preserves first-return
surprise, second-step recovery, baseline advantage, and degradation relative
to the original regime. Successful measurement remains PARTIAL pending live
independent review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable

from .prequential_evaluation import PrequentialTrace


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


def _digest(value: str, field: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{field} must be an exact SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _finite(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{field} must be finite")
    return out


def _trace_dict(trace: PrequentialTrace) -> dict[str, object]:
    if type(trace) is not PrequentialTrace:
        raise TypeError("trace must be exact PrequentialTrace")
    return {
        "evaluation_order": trace.evaluation_order,
        "authorization_effect": trace.authorization_effect,
        "steps": [
            {
                "case_id": step.case_id,
                "prediction": step.prediction,
                "score": step.score,
                "evaluator_context": dict(step.evaluator_context),
            }
            for step in trace.steps
        ],
    }


@dataclass(frozen=True, slots=True)
class RegimeReturnThresholds:
    min_first_return_surprise: float
    max_second_step_mse: float
    min_second_step_baseline_advantage: float
    max_old_task_degradation: float
    min_intervening_regimes: int = 3

    def __post_init__(self) -> None:
        if (
            type(self.min_intervening_regimes) is not int
            or self.min_intervening_regimes < 3
        ):
            raise ValueError(
                "min_intervening_regimes must be an exact int of at least 3"
            )
        for name in (
            "min_first_return_surprise",
            "max_second_step_mse",
            "min_second_step_baseline_advantage",
            "max_old_task_degradation",
        ):
            value = _finite(getattr(self, name), name)
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class RegimeReturnMetrics:
    intervening_regime_count: int
    first_return_surprise: float
    second_step_mse: float
    baseline_second_step_mse: float
    second_step_baseline_advantage: float
    original_late_mse: float
    old_task_degradation: float


@dataclass(frozen=True, slots=True)
class RegimeReturnQualificationResult:
    metrics: RegimeReturnMetrics
    packet: dict[str, object]
    qualification_artifact_json: str
    qualification_artifact_digest: str


def qualify_regime_return(
    original: PrequentialTrace,
    *,
    returned: PrequentialTrace,
    baseline_returned: PrequentialTrace,
    intervening_regime_ids: Iterable[str],
    thresholds: RegimeReturnThresholds,
    repository: str,
    exact_head: str,
    runtime_binding: str,
    probe_id: str,
    items_digest: str,
    curator_independence: str,
    training_overlap: str,
    developer_item_access: bool,
    tool_access: Iterable[str],
    claim_ceiling: str,
) -> RegimeReturnQualificationResult:
    if type(original) is not PrequentialTrace:
        raise TypeError("original must be exact PrequentialTrace")
    if type(returned) is not PrequentialTrace:
        raise TypeError("returned must be exact PrequentialTrace")
    if type(baseline_returned) is not PrequentialTrace:
        raise TypeError("baseline_returned must be exact PrequentialTrace")
    if type(thresholds) is not RegimeReturnThresholds:
        raise TypeError("thresholds must be exact RegimeReturnThresholds")
    if len(original.steps) < 4:
        raise ValueError("original trace requires at least four scored steps")
    if len(returned.steps) < 2 or len(baseline_returned.steps) < 2:
        raise ValueError("return traces require at least two scored steps")
    for trace in (original, returned, baseline_returned):
        if trace.evaluation_order != "PREDICT_SCORE_THEN_UPDATE":
            raise ValueError("REGIME_RETURN requires prequential evaluation")

    regime_ids = tuple(intervening_regime_ids)
    if any(type(item) is not str or not item for item in regime_ids):
        raise ValueError(
            "intervening regimes must be non-empty exact strings"
        )
    if len(regime_ids) < thresholds.min_intervening_regimes:
        raise ValueError(
            "REGIME_RETURN requires at least three intervening regimes"
        )
    if len(set(regime_ids)) != len(regime_ids):
        raise ValueError("intervening regimes must be distinct")

    if type(repository) is not str or not repository:
        raise ValueError("repository must be a non-empty exact string")
    _exact_head(exact_head)
    if runtime_binding not in _RUNTIME_BINDINGS:
        raise ValueError("unsupported runtime_binding")
    if type(probe_id) is not str or not probe_id:
        raise ValueError("probe_id must be a non-empty exact string")
    items_digest = _digest(items_digest, "items_digest")
    if type(curator_independence) is not str or not curator_independence:
        raise ValueError(
            "curator_independence must be a non-empty exact string"
        )
    if type(training_overlap) is not str or not training_overlap:
        raise ValueError("training_overlap must be a non-empty exact string")
    if type(developer_item_access) is not bool:
        raise TypeError("developer_item_access must be bool")
    tools = tuple(tool_access)
    if any(type(item) is not str or not item for item in tools):
        raise ValueError("tool_access must contain non-empty exact strings")
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    first_return = _finite(returned.steps[0].score, "first_return_surprise")
    second_step = _finite(returned.steps[1].score, "second_step_mse")
    baseline_second = _finite(
        baseline_returned.steps[1].score,
        "baseline_second_step_mse",
    )
    original_late = sum(
        _finite(step.score, "original_late_score")
        for step in original.steps[-4:]
    ) / 4.0
    baseline_advantage = baseline_second - second_step
    degradation = max(0.0, second_step - original_late)

    metrics = RegimeReturnMetrics(
        intervening_regime_count=len(regime_ids),
        first_return_surprise=first_return,
        second_step_mse=second_step,
        baseline_second_step_mse=baseline_second,
        second_step_baseline_advantage=baseline_advantage,
        original_late_mse=original_late,
        old_task_degradation=degradation,
    )

    metrics_pass = (
        first_return >= thresholds.min_first_return_surprise
        and second_step <= thresholds.max_second_step_mse
        and baseline_advantage
        >= thresholds.min_second_step_baseline_advantage
        and degradation <= thresholds.max_old_task_degradation
    )
    dimension_state = "PARTIAL" if metrics_pass else "FAIL"

    artifact = {
        "schema": "VERA_AGI_REGIME_RETURN_QUALIFICATION_V1",
        "probe_id": probe_id,
        "items_digest": items_digest,
        "intervening_regime_ids": list(regime_ids),
        "thresholds": asdict(thresholds),
        "metrics": asdict(metrics),
        "original_trace": _trace_dict(original),
        "returned_trace": _trace_dict(returned),
        "baseline_returned_trace": _trace_dict(baseline_returned),
        "curator_independence": curator_independence,
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "measurement_only": True,
        "independent_review_required_for_pass": True,
        "dimension_states": {
            "RETENTION_AND_INTERFERENCE": dimension_state,
        },
    }
    artifact_json = _canonical_json(artifact)
    artifact_digest = hashlib.sha256(
        artifact_json.encode("utf-8")
    ).hexdigest()

    passed = sum(
        1
        for step in returned.steps
        if _finite(step.score, "returned_score")
        <= thresholds.max_second_step_mse
    )
    packet = {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": repository,
            "exact_head": exact_head,
            "runtime_binding": runtime_binding,
        },
        "probe": {
            "probe_id": probe_id,
            "family": "REGIME_RETURN",
            "held_out": True,
            "curator_independence": curator_independence,
            "items_digest": items_digest,
        },
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "results": {
            "attempted": len(returned.steps),
            "passed": passed,
            "failed": len(returned.steps) - passed,
            "raw_artifact_digest": artifact_digest,
            "negative_results_preserved": True,
        },
        "dimension_states": {
            "RETENTION_AND_INTERFERENCE": dimension_state,
        },
        "independent_review": None,
        "claim_ceiling": claim_ceiling,
    }
    return RegimeReturnQualificationResult(
        metrics=metrics,
        packet=packet,
        qualification_artifact_json=artifact_json,
        qualification_artifact_digest=artifact_digest,
    )
