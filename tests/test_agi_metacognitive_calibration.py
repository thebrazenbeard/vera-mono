import math

import pytest

from vera_core import (
    CalibrationForecast,
    CalibrationObservation,
    OnlineConfidenceCalibrator,
)


def test_unseen_confidence_region_is_explicitly_unknown():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )

    forecast = tracker.forecast(0.9)

    assert forecast.raw_confidence == 0.9
    assert forecast.calibrated_confidence == 0.5
    assert forecast.unknown is True
    assert forecast.evidence_class == "UNSEEN_BIN_PRIOR"
    assert forecast.sample_count == 0
    assert forecast.authorization_effect == "NONE"


def test_forecast_is_scored_before_outcome_updates_reliability():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )

    forecast = tracker.forecast(0.9)
    assert forecast.sample_count == 0

    observation = tracker.observe(
        forecast.forecast_id,
        outcome_success=False,
    )

    assert isinstance(observation, CalibrationObservation)
    assert observation.forecast == forecast
    assert observation.outcome_success is False
    assert observation.raw_brier == pytest.approx(0.81)
    assert observation.calibrated_brier == pytest.approx(0.25)

    next_forecast = tracker.forecast(0.9)
    assert next_forecast.sample_count == 1

    with pytest.raises(ValueError, match="already observed"):
        tracker.observe(forecast.forecast_id, outcome_success=True)


def test_repeated_overconfidence_is_corrected_toward_observed_outcomes():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )

    for success in (False, True, False, True, False, True):
        forecast = tracker.forecast(0.9)
        tracker.observe(forecast.forecast_id, outcome_success=success)

    calibrated = tracker.forecast(0.9)

    assert calibrated.unknown is False
    assert calibrated.evidence_class == "EMPIRICAL_OUTCOME_HISTORY"
    assert calibrated.sample_count == 6
    assert calibrated.calibrated_confidence == pytest.approx(0.5)
    assert abs(calibrated.calibrated_confidence - 0.5) < abs(0.9 - 0.5)


def test_calibration_can_change_a_decision_after_outcomes_disconfirm_raw_support():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )

    for _ in range(4):
        forecast = tracker.forecast(0.9)
        tracker.observe(forecast.forecast_id, outcome_success=False)

    forecast = tracker.forecast(0.9)
    admission = tracker.admit(
        forecast,
        min_calibrated_confidence=0.8,
    )

    assert forecast.raw_confidence >= 0.8
    assert forecast.calibrated_confidence < 0.8
    assert admission.admitted is False
    assert admission.reason == "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD"
    assert admission.authorization_effect == "NONE"


def test_empirically_reliable_confidence_can_be_admitted():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )

    for _ in range(8):
        forecast = tracker.forecast(0.9)
        tracker.observe(forecast.forecast_id, outcome_success=True)

    forecast = tracker.forecast(0.9)
    admission = tracker.admit(
        forecast,
        min_calibrated_confidence=0.8,
    )

    assert forecast.evidence_class == "EMPIRICAL_OUTCOME_HISTORY"
    assert forecast.calibrated_confidence >= 0.8
    assert admission.admitted is True
    assert admission.reason == "CALIBRATED_CONFIDENCE_MEETS_THRESHOLD"


def test_unseen_region_cannot_be_admitted_as_if_empirically_calibrated():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )

    forecast = tracker.forecast(0.7)
    admission = tracker.admit(
        forecast,
        min_calibrated_confidence=0.4,
    )

    assert forecast.calibrated_confidence >= 0.4
    assert forecast.unknown is True
    assert admission.admitted is False
    assert admission.reason == "CALIBRATION_EVIDENCE_UNKNOWN"


def test_forecast_objects_cannot_be_forged_to_bypass_tracker_state():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )
    issued = tracker.forecast(0.9)
    forged = CalibrationForecast(
        forecast_id=issued.forecast_id,
        raw_confidence=0.9,
        calibrated_confidence=1.0,
        bin_index=issued.bin_index,
        sample_count=99,
        evidence_class="EMPIRICAL_OUTCOME_HISTORY",
        unknown=False,
    )

    with pytest.raises(ValueError, match="does not match"):
        tracker.admit(forged, min_calibrated_confidence=0.8)


def test_invalid_confidence_and_bin_configuration_fail_closed():
    with pytest.raises(ValueError):
        OnlineConfidenceCalibrator(
            bin_edges=(0.0, 0.75, 0.5, 1.0),
            prior_mean=0.5,
            prior_strength=2.0,
            min_empirical_observations=2,
        )

    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )
    with pytest.raises(ValueError):
        tracker.forecast(float("nan"))
