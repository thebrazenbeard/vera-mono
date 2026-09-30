import json
from pathlib import Path

import jsonschema
import vera_core
from vera_core import OnlineConfidenceCalibrator


def _observations():
    tracker = OnlineConfidenceCalibrator(
        bin_edges=(0.0, 0.5, 0.75, 1.0),
        prior_mean=0.5,
        prior_strength=2.0,
        min_empirical_observations=2,
    )
    out = []
    for success in (False, True, False, True, False, True, False, True):
        forecast = tracker.forecast(0.9)
        out.append(
            tracker.observe(
                forecast.forecast_id,
                outcome_success=success,
            )
        )
    return tuple(out)


def test_metacognitive_measurement_improves_prequential_calibration_but_stays_partial():
    qualify = getattr(
        vera_core,
        "qualify_metacognitive_calibration",
        None,
    )
    assert callable(qualify), (
        "metacognitive qualification API is not implemented"
    )

    result = qualify(
        _observations(),
        admission_threshold=0.8,
        min_observations=8,
        min_brier_improvement=0.10,
        max_calibrated_false_admission_rate=0.25,
        min_false_admission_delta=0.50,
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        probe_id="metacognitive-hidden-1",
        items_digest="a" * 64,
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        training_overlap="NONE_KNOWN",
        developer_item_access=True,
        tool_access=(),
        claim_ceiling="METACOGNITIVE_CALIBRATION_MEASUREMENT_ONLY_NOT_AGI",
    )

    assert result.metrics.observation_count == 8
    assert result.metrics.raw_brier_mean > result.metrics.calibrated_brier_mean
    assert result.metrics.brier_improvement >= 0.10
    assert result.metrics.raw_false_admission_rate == 1.0
    assert result.metrics.calibrated_false_admission_rate == 0.0
    assert result.metrics.false_admission_delta == 1.0
    assert result.metrics.unknown_forecast_count == 2
    assert result.packet["probe"]["family"] == "AMBIGUOUS_SPEC"
    assert result.packet["dimension_states"] == {
        "METACOGNITIVE_CALIBRATION": "PARTIAL",
    }
    assert result.packet["independent_review"] is None

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result.packet, schema)
