import hashlib
import json
from pathlib import Path

import jsonschema

from vera_core import (
    ContextualOnlineLinearPredictor,
    OnlineLinearPredictor,
    RegimeReturnThresholds,
    qualify_regime_return,
)
from vera_core.adaptive_linear import squared_error
from vera_core.prequential_evaluation import PrequentialCase, evaluate_prequential


def _cases(coefficient: float, *, prefix: str, count: int):
    return [
        PrequentialCase(
            case_id=f"{prefix}-{index}",
            model_input=(1.0 if index % 2 == 0 else -1.0,),
            expected=coefficient * (1.0 if index % 2 == 0 else -1.0),
        )
        for index in range(count)
    ]


def _run(learner, coefficient: float, *, prefix: str, count: int):
    return evaluate_prequential(
        _cases(coefficient, prefix=prefix, count=count),
        predict=learner.predict,
        score=squared_error,
        update=learner.update,
    )


def _experiment():
    contextual = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    baseline = OnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )

    original_contextual = _run(
        contextual,
        0.8,
        prefix="A-original-contextual",
        count=24,
    )
    _run(baseline, 0.8, prefix="A-original-baseline", count=24)

    for label, coefficient in (
        ("B", -0.4),
        ("C", 1.3),
        ("D", -1.1),
    ):
        _run(
            contextual,
            coefficient,
            prefix=f"{label}-contextual",
            count=24,
        )
        _run(
            baseline,
            coefficient,
            prefix=f"{label}-baseline",
            count=24,
        )

    contextual_return = _run(
        contextual,
        0.8,
        prefix="A-return-contextual",
        count=3,
    )
    baseline_return = _run(
        baseline,
        0.8,
        prefix="A-return-baseline",
        count=3,
    )
    return original_contextual, contextual_return, baseline_return


def _thresholds():
    return RegimeReturnThresholds(
        min_first_return_surprise=0.25,
        max_second_step_mse=0.05,
        min_second_step_baseline_advantage=0.20,
        max_old_task_degradation=0.05,
        min_intervening_regimes=3,
    )


def test_regime_return_measurement_binds_required_metrics_and_stays_partial():
    original, returned, baseline_returned = _experiment()

    result = qualify_regime_return(
        original,
        returned=returned,
        baseline_returned=baseline_returned,
        intervening_regime_ids=("B", "C", "D"),
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        probe_id="regime-return-hidden-1",
        items_digest="a" * 64,
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        training_overlap="NONE_KNOWN",
        developer_item_access=True,
        tool_access=(),
        claim_ceiling="REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
    )

    assert result.metrics.intervening_regime_count == 3
    assert result.metrics.first_return_surprise > 0.25
    assert result.metrics.second_step_mse < 0.05
    assert result.metrics.second_step_baseline_advantage > 0.20
    assert result.metrics.old_task_degradation < 0.05
    assert result.packet["dimension_states"] == {
        "RETENTION_AND_INTERFERENCE": "PARTIAL",
    }
    assert result.packet["independent_review"] is None

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result.packet, schema)


def test_regime_return_requires_three_distinct_intervening_regimes():
    original, returned, baseline_returned = _experiment()

    try:
        qualify_regime_return(
            original,
            returned=returned,
            baseline_returned=baseline_returned,
            intervening_regime_ids=("B", "C"),
            thresholds=_thresholds(),
            repository="thebrazenbeard/vera-mono",
            exact_head="2" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            probe_id="regime-return-hidden-2",
            items_digest="b" * 64,
            curator_independence="INDEPENDENT_MODEL",
            training_overlap="NONE_KNOWN",
            developer_item_access=False,
            tool_access=(),
            claim_ceiling="REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
        )
    except ValueError as exc:
        assert "intervening regimes" in str(exc)
    else:
        raise AssertionError("two-regime return was accepted")


def test_regime_return_rejects_duplicate_intervening_regime_ids():
    original, returned, baseline_returned = _experiment()

    try:
        qualify_regime_return(
            original,
            returned=returned,
            baseline_returned=baseline_returned,
            intervening_regime_ids=("B", "B", "D"),
            thresholds=_thresholds(),
            repository="thebrazenbeard/vera-mono",
            exact_head="3" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            probe_id="regime-return-hidden-3",
            items_digest="c" * 64,
            curator_independence="INDEPENDENT_MODEL",
            training_overlap="NONE_KNOWN",
            developer_item_access=False,
            tool_access=(),
            claim_ceiling="REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
        )
    except ValueError as exc:
        assert "distinct" in str(exc)
    else:
        raise AssertionError("duplicate regimes were accepted")


def test_regime_return_failure_is_not_promoted_by_metadata():
    original, returned, baseline_returned = _experiment()

    result = qualify_regime_return(
        original,
        returned=returned,
        baseline_returned=baseline_returned,
        intervening_regime_ids=("B", "C", "D"),
        thresholds=RegimeReturnThresholds(
            min_first_return_surprise=0.25,
            max_second_step_mse=1e-12,
            min_second_step_baseline_advantage=10.0,
            max_old_task_degradation=1e-12,
            min_intervening_regimes=3,
        ),
        repository="thebrazenbeard/vera-mono",
        exact_head="4" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        probe_id="regime-return-hidden-4",
        items_digest="d" * 64,
        curator_independence="INDEPENDENT_MODEL",
        training_overlap="NONE_KNOWN",
        developer_item_access=False,
        tool_access=(),
        claim_ceiling="REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
    )

    assert result.packet["dimension_states"] == {
        "RETENTION_AND_INTERFERENCE": "FAIL",
    }


def test_regime_return_artifact_digest_binds_traces_and_regime_sequence():
    original, returned, baseline_returned = _experiment()

    result = qualify_regime_return(
        original,
        returned=returned,
        baseline_returned=baseline_returned,
        intervening_regime_ids=("B", "C", "D"),
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="5" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        probe_id="regime-return-hidden-5",
        items_digest="e" * 64,
        curator_independence="INDEPENDENT_MODEL",
        training_overlap="NONE_KNOWN",
        developer_item_access=False,
        tool_access=(),
        claim_ceiling="REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
    )

    artifact = json.loads(result.qualification_artifact_json)
    assert artifact["intervening_regime_ids"] == ["B", "C", "D"]
    assert artifact["measurement_only"] is True
    assert artifact["independent_review_required_for_pass"] is True
    assert (
        hashlib.sha256(
            result.qualification_artifact_json.encode("utf-8")
        ).hexdigest()
        == result.qualification_artifact_digest
    )
    assert (
        result.packet["results"]["raw_artifact_digest"]
        == result.qualification_artifact_digest
    )
