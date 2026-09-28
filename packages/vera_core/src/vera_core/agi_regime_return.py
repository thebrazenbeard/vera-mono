"""Bound REGIME_RETURN measurement for retention/interference research.

The measurement consumes case-bound prequential phase evidence. It preserves
first-return surprise, second-step recovery, baseline advantage, and
degradation relative to the original regime. Successful measurement remains
PARTIAL pending live independent review.

The three-plus intervening-regime control is evidence-bearing: callers must
provide the actual cases and traces for every intervening phase. Relabeling
one target function under multiple regime IDs does not satisfy the control.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Any, Iterable

from .prequential_evaluation import (
    PrequentialCase,
    PrequentialTrace,
)


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


def _case_dict(case: PrequentialCase) -> dict[str, object]:
    if type(case) is not PrequentialCase:
        raise TypeError("cases must contain exact PrequentialCase values")
    return {
        "case_id": case.case_id,
        "model_input": case.model_input,
        "expected": case.expected,
        "evaluator_context": dict(case.evaluator_context),
    }


def _target_digest(cases: tuple[PrequentialCase, ...]) -> str:
    # Ignore case IDs and repetition count; bind the actual input->target
    # relation represented by the phase.
    pairs = sorted(
        {
            _canonical_json(
                {
                    "model_input": case.model_input,
                    "expected": case.expected,
                }
            )
            for case in cases
        }
    )
    return hashlib.sha256(
        _canonical_json(pairs).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class RegimeReturnPhaseEvidence:
    regime_id: str
    cases: tuple[PrequentialCase, ...]
    trace: PrequentialTrace

    def __post_init__(self) -> None:
        if type(self.regime_id) is not str or not self.regime_id:
            raise ValueError("regime_id must be a non-empty exact string")
        object.__setattr__(self, "cases", tuple(self.cases))
        if not self.cases:
            raise ValueError("phase cases must not be empty")
        if any(type(case) is not PrequentialCase for case in self.cases):
            raise TypeError(
                "phase cases must contain exact PrequentialCase values"
            )
        if type(self.trace) is not PrequentialTrace:
            raise TypeError("phase trace must be exact PrequentialTrace")
        if self.trace.evaluation_order != "PREDICT_SCORE_THEN_UPDATE":
            raise ValueError("REGIME_RETURN requires prequential evaluation")
        if self.trace.authorization_effect != "NONE":
            raise ValueError("REGIME_RETURN phase authorization effect must be NONE")
        if len(self.cases) != len(self.trace.steps):
            raise ValueError("phase cases and trace steps must align exactly")

        for index, (case, step) in enumerate(
            zip(self.cases, self.trace.steps, strict=True)
        ):
            if step.case_id != case.case_id:
                raise ValueError(
                    "phase case IDs and trace case IDs must align exactly"
                )
            prediction = _finite(
                step.prediction,
                f"phase[{index}].prediction",
            )
            expected = _finite(
                case.expected,
                f"phase[{index}].expected",
            )
            score = _finite(
                step.score,
                f"phase[{index}].score",
            )
            expected_score = (prediction - expected) ** 2
            if not math.isclose(
                score,
                expected_score,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "phase trace score does not match bound case evidence"
                )

    @property
    def target_digest(self) -> str:
        return _target_digest(self.cases)

    def as_dict(self) -> dict[str, object]:
        return {
            "regime_id": self.regime_id,
            "target_digest": self.target_digest,
            "cases": [_case_dict(case) for case in self.cases],
            "trace": _trace_dict(self.trace),
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
    original: RegimeReturnPhaseEvidence,
    *,
    intervening_regimes: Iterable[RegimeReturnPhaseEvidence],
    returned: RegimeReturnPhaseEvidence,
    baseline_returned: RegimeReturnPhaseEvidence,
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
    if type(original) is not RegimeReturnPhaseEvidence:
        raise TypeError(
            "original must be exact RegimeReturnPhaseEvidence"
        )
    if type(returned) is not RegimeReturnPhaseEvidence:
        raise TypeError(
            "returned must be exact RegimeReturnPhaseEvidence"
        )
    if type(baseline_returned) is not RegimeReturnPhaseEvidence:
        raise TypeError(
            "baseline_returned must be exact RegimeReturnPhaseEvidence"
        )
    if type(thresholds) is not RegimeReturnThresholds:
        raise TypeError("thresholds must be exact RegimeReturnThresholds")
    if len(original.trace.steps) < 4:
        raise ValueError("original phase requires at least four scored steps")
    if (
        len(returned.trace.steps) < 2
        or len(baseline_returned.trace.steps) < 2
    ):
        raise ValueError("return phases require at least two scored steps")

    phases = tuple(intervening_regimes)
    if any(type(item) is not RegimeReturnPhaseEvidence for item in phases):
        raise TypeError(
            "intervening_regimes must contain exact "
            "RegimeReturnPhaseEvidence values"
        )
    if len(phases) < thresholds.min_intervening_regimes:
        raise ValueError(
            "REGIME_RETURN requires at least three intervening regimes"
        )

    regime_ids = tuple(phase.regime_id for phase in phases)
    if len(set(regime_ids)) != len(regime_ids):
        raise ValueError("intervening regimes must have distinct IDs")

    target_digests = tuple(phase.target_digest for phase in phases)
    if len(set(target_digests)) != len(target_digests):
        raise ValueError(
            "intervening regimes must have distinct target functions"
        )
    if original.target_digest in target_digests:
        raise ValueError(
            "intervening regime target must differ from original target"
        )
    if returned.target_digest != original.target_digest:
        raise ValueError(
            "return target function must match original target function"
        )
    if baseline_returned.target_digest != original.target_digest:
        raise ValueError(
            "baseline return target function must match original target function"
        )

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

    first_return = _finite(
        returned.trace.steps[0].score,
        "first_return_surprise",
    )
    second_step = _finite(
        returned.trace.steps[1].score,
        "second_step_mse",
    )
    baseline_second = _finite(
        baseline_returned.trace.steps[1].score,
        "baseline_second_step_mse",
    )
    original_late = sum(
        _finite(step.score, "original_late_score")
        for step in original.trace.steps[-4:]
    ) / 4.0
    baseline_advantage = baseline_second - second_step
    degradation = max(0.0, second_step - original_late)

    metrics = RegimeReturnMetrics(
        intervening_regime_count=len(phases),
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
        "schema": "VERA_AGI_REGIME_RETURN_QUALIFICATION_V2",
        "probe_id": probe_id,
        "items_digest": items_digest,
        "original_regime": original.as_dict(),
        "intervening_regimes": [phase.as_dict() for phase in phases],
        "returned_regime": returned.as_dict(),
        "baseline_returned_regime": baseline_returned.as_dict(),
        "thresholds": asdict(thresholds),
        "metrics": asdict(metrics),
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
        for step in returned.trace.steps
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
            "attempted": len(returned.trace.steps),
            "passed": passed,
            "failed": len(returned.trace.steps) - passed,
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
