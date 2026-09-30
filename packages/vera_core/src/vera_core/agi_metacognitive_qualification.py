"""Evidence-bound metacognitive calibration measurement.

This module measures prequential confidence calibration against observed
outcomes. Raw confidence is the baseline. Successful measurement remains
PARTIAL until a separate live-current independent-review promotion route
binds the exact held-out cut and qualification artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable

from .agi_metacognitive_calibration import CalibrationObservation


_RUNTIME_BINDINGS = frozenset({
    "SOURCE_ONLY",
    "LOCAL_TEST_RUNTIME",
    "QUALIFIED_RUNTIME",
})


def _probability(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out) or not 0.0 <= out <= 1.0:
        raise ValueError(f"{field} must be finite and in [0, 1]")
    return out


def _non_negative(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out) or out < 0.0:
        raise ValueError(f"{field} must be finite and non-negative")
    return out


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


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@dataclass(frozen=True, slots=True)
class MetacognitiveCalibrationMetrics:
    observation_count: int
    raw_brier_mean: float
    calibrated_brier_mean: float
    brier_improvement: float
    failed_outcome_count: int
    raw_false_admission_rate: float
    calibrated_false_admission_rate: float
    false_admission_delta: float
    unknown_forecast_count: int
    empirical_forecast_count: int


@dataclass(frozen=True, slots=True)
class MetacognitiveCalibrationQualificationResult:
    metrics: MetacognitiveCalibrationMetrics
    packet: dict[str, object]
    qualification_artifact_json: str
    qualification_artifact_digest: str


def qualify_metacognitive_calibration(
    observations: Iterable[CalibrationObservation],
    *,
    admission_threshold: float,
    min_observations: int,
    min_brier_improvement: float,
    max_calibrated_false_admission_rate: float,
    min_false_admission_delta: float,
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
) -> MetacognitiveCalibrationQualificationResult:
    """Measure calibration without granting PASS or external authority."""

    rows = tuple(observations)
    if not rows:
        raise ValueError("observations must not be empty")
    if any(type(item) is not CalibrationObservation for item in rows):
        raise TypeError(
            "observations must contain exact CalibrationObservation values"
        )
    threshold = _probability(
        admission_threshold,
        "admission_threshold",
    )
    if type(min_observations) is not int or min_observations < 1:
        raise ValueError("min_observations must be an exact positive int")
    min_brier = _non_negative(
        min_brier_improvement,
        "min_brier_improvement",
    )
    max_false = _probability(
        max_calibrated_false_admission_rate,
        "max_calibrated_false_admission_rate",
    )
    min_delta = _probability(
        min_false_admission_delta,
        "min_false_admission_delta",
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

    seen_ids: set[str] = set()
    seen_per_bin: dict[int, int] = {}
    raw_brier_total = 0.0
    calibrated_brier_total = 0.0
    failed_outcomes = 0
    raw_false_admissions = 0
    calibrated_false_admissions = 0
    unknown_forecasts = 0
    empirical_forecasts = 0
    artifact_rows: list[dict[str, object]] = []

    for index, observation in enumerate(rows):
        forecast = observation.forecast
        if forecast.forecast_id in seen_ids:
            raise ValueError("forecast IDs must be unique")
        seen_ids.add(forecast.forecast_id)

        expected_sample_count = seen_per_bin.get(forecast.bin_index, 0)
        if forecast.sample_count != expected_sample_count:
            raise ValueError(
                "forecast sample_count is not prequentially aligned "
                "within its confidence bin"
            )
        seen_per_bin[forecast.bin_index] = expected_sample_count + 1

        raw = _probability(
            forecast.raw_confidence,
            f"observations[{index}].raw_confidence",
        )
        calibrated = _probability(
            forecast.calibrated_confidence,
            f"observations[{index}].calibrated_confidence",
        )
        target = 1.0 if observation.outcome_success else 0.0
        expected_raw_brier = (raw - target) ** 2
        expected_calibrated_brier = (calibrated - target) ** 2
        if not math.isclose(
            observation.raw_brier,
            expected_raw_brier,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("raw Brier score does not match bound outcome")
        if not math.isclose(
            observation.calibrated_brier,
            expected_calibrated_brier,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "calibrated Brier score does not match bound outcome"
            )

        raw_admitted = raw >= threshold
        calibrated_admitted = (
            forecast.unknown is False and calibrated >= threshold
        )

        if forecast.unknown:
            unknown_forecasts += 1
        if forecast.evidence_class == "EMPIRICAL_OUTCOME_HISTORY":
            empirical_forecasts += 1

        if observation.outcome_success is False:
            failed_outcomes += 1
            raw_false_admissions += int(raw_admitted)
            calibrated_false_admissions += int(calibrated_admitted)

        raw_brier_total += expected_raw_brier
        calibrated_brier_total += expected_calibrated_brier
        artifact_rows.append(
            {
                "forecast_id": forecast.forecast_id,
                "raw_confidence": raw,
                "calibrated_confidence": calibrated,
                "bin_index": forecast.bin_index,
                "sample_count": forecast.sample_count,
                "evidence_class": forecast.evidence_class,
                "unknown": forecast.unknown,
                "outcome_success": observation.outcome_success,
                "raw_brier": expected_raw_brier,
                "calibrated_brier": expected_calibrated_brier,
                "raw_admitted": raw_admitted,
                "calibrated_admitted": calibrated_admitted,
            }
        )

    count = len(rows)
    raw_mean = raw_brier_total / count
    calibrated_mean = calibrated_brier_total / count
    improvement = raw_mean - calibrated_mean
    raw_false_rate = (
        0.0
        if failed_outcomes == 0
        else raw_false_admissions / failed_outcomes
    )
    calibrated_false_rate = (
        0.0
        if failed_outcomes == 0
        else calibrated_false_admissions / failed_outcomes
    )
    false_delta = raw_false_rate - calibrated_false_rate

    metrics = MetacognitiveCalibrationMetrics(
        observation_count=count,
        raw_brier_mean=raw_mean,
        calibrated_brier_mean=calibrated_mean,
        brier_improvement=improvement,
        failed_outcome_count=failed_outcomes,
        raw_false_admission_rate=raw_false_rate,
        calibrated_false_admission_rate=calibrated_false_rate,
        false_admission_delta=false_delta,
        unknown_forecast_count=unknown_forecasts,
        empirical_forecast_count=empirical_forecasts,
    )

    metrics_pass = (
        count >= min_observations
        and improvement >= min_brier
        and calibrated_false_rate <= max_false
        and false_delta >= min_delta
    )
    dimension_state = "PARTIAL" if metrics_pass else "FAIL"
    dimensions = {
        "METACOGNITIVE_CALIBRATION": dimension_state,
    }

    artifact = {
        "schema": "VERA_AGI_METACOGNITIVE_CALIBRATION_QUALIFICATION_V1",
        "probe_id": probe_id,
        "items_digest": items_digest,
        "family": "AMBIGUOUS_SPEC",
        "thresholds": {
            "admission_threshold": threshold,
            "min_observations": min_observations,
            "min_brier_improvement": min_brier,
            "max_calibrated_false_admission_rate": max_false,
            "min_false_admission_delta": min_delta,
        },
        "metrics": {
            "observation_count": metrics.observation_count,
            "raw_brier_mean": metrics.raw_brier_mean,
            "calibrated_brier_mean": metrics.calibrated_brier_mean,
            "brier_improvement": metrics.brier_improvement,
            "failed_outcome_count": metrics.failed_outcome_count,
            "raw_false_admission_rate": metrics.raw_false_admission_rate,
            "calibrated_false_admission_rate": (
                metrics.calibrated_false_admission_rate
            ),
            "false_admission_delta": metrics.false_admission_delta,
            "unknown_forecast_count": metrics.unknown_forecast_count,
            "empirical_forecast_count": metrics.empirical_forecast_count,
        },
        "observations": artifact_rows,
        "curator_independence": curator_independence,
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "measurement_only": True,
        "independent_review_required_for_pass": True,
        "dimension_states": dimensions,
    }
    artifact_json = _canonical_json(artifact)
    artifact_digest = hashlib.sha256(
        artifact_json.encode("utf-8")
    ).hexdigest()

    successes = sum(1 for item in rows if item.outcome_success)
    packet = {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": repository,
            "exact_head": exact_head,
            "runtime_binding": runtime_binding,
        },
        "probe": {
            "probe_id": probe_id,
            "family": "AMBIGUOUS_SPEC",
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
            "attempted": count,
            "passed": successes,
            "failed": count - successes,
            "raw_artifact_digest": artifact_digest,
            "negative_results_preserved": True,
        },
        "dimension_states": dimensions,
        "independent_review": None,
        "claim_ceiling": claim_ceiling,
    }
    return MetacognitiveCalibrationQualificationResult(
        metrics=metrics,
        packet=packet,
        qualification_artifact_json=artifact_json,
        qualification_artifact_digest=artifact_digest,
    )
