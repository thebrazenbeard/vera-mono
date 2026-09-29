import json

import pytest

from vera_core import (
    ContextualOnlineLinearPredictor,
    OnlineLinearPredictor,
    RegimeReturnPhaseEvidence,
    RegimeReturnThresholds,
    qualify_regime_return,
)
from vera_core.adaptive_linear import squared_error
from vera_core.prequential_evaluation import (
    PrequentialCase,
    PrequentialStep,
    PrequentialTrace,
    evaluate_prequential,
)


def _cases(coefficient: float, *, prefix: str, count: int):
    return tuple(
        PrequentialCase(
            case_id=f"{prefix}-{index}",
            model_input=(1.0 if index % 2 == 0 else -1.0,),
            expected=coefficient * (1.0 if index % 2 == 0 else -1.0),
        )
        for index in range(count)
    )


def _phase(learner, regime_id: str, coefficient: float, *, count: int = 24):
    cases = _cases(coefficient, prefix=regime_id, count=count)
    trace = evaluate_prequential(
        cases,
        predict=learner.predict,
        score=squared_error,
        update=learner.update,
    )
    return RegimeReturnPhaseEvidence(
        regime_id=regime_id,
        cases=cases,
        trace=trace,
    )


def _thresholds():
    return RegimeReturnThresholds(
        min_first_return_surprise=0.25,
        max_second_step_mse=0.05,
        min_second_step_baseline_advantage=0.20,
        max_old_task_degradation=0.05,
        min_intervening_regimes=3,
    )


def _qualify(original, intervening, returned, baseline_returned):
    return qualify_regime_return(
        original,
        intervening_regimes=intervening,
        returned=returned,
        baseline_returned=baseline_returned,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        probe_id="regime-return-bound-1",
        items_digest="a" * 64,
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        training_overlap="NONE_KNOWN",
        developer_item_access=True,
        tool_access=(),
        claim_ceiling="REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
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

    original = _phase(contextual, "A", 0.8)
    _phase(baseline, "A-baseline", 0.8)

    intervening = tuple(
        _phase(contextual, label, coefficient)
        for label, coefficient in (
            ("B", -0.4),
            ("C", 1.3),
            ("D", -1.1),
        )
    )
    for label, coefficient in (
        ("B", -0.4),
        ("C", 1.3),
        ("D", -1.1),
    ):
        _phase(baseline, f"{label}-baseline", coefficient)

    returned = _phase(contextual, "A-return", 0.8, count=3)
    baseline_returned = _phase(
        baseline,
        "A-return-baseline",
        0.8,
        count=3,
    )
    return original, intervening, returned, baseline_returned


def test_regime_return_binds_actual_intervening_phase_evidence():
    original, intervening, returned, baseline_returned = _experiment()

    result = _qualify(
        original,
        intervening,
        returned,
        baseline_returned,
    )

    artifact = json.loads(result.qualification_artifact_json)
    bound = artifact["intervening_regimes"]
    assert [item["regime_id"] for item in bound] == ["B", "C", "D"]
    assert len({item["target_digest"] for item in bound}) == 3
    assert all(item["trace"]["steps"] for item in bound)
    assert result.metrics.intervening_regime_count == 3


def test_relabeling_one_regime_three_times_does_not_satisfy_control():
    contextual = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    baseline = OnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )

    original = _phase(contextual, "A", 0.8)
    _phase(baseline, "A-baseline", 0.8)

    same_target = tuple(
        _phase(contextual, label, -0.4)
        for label in ("B", "C", "D")
    )
    for label in ("B", "C", "D"):
        _phase(baseline, f"{label}-baseline", -0.4)

    returned = _phase(contextual, "A-return", 0.8, count=3)
    baseline_returned = _phase(
        baseline,
        "A-return-baseline",
        0.8,
        count=3,
    )

    with pytest.raises(ValueError, match="distinct target"):
        _qualify(
            original,
            same_target,
            returned,
            baseline_returned,
        )


def test_intervening_regime_must_be_distinct_from_original_target():
    contextual = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    baseline = OnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )

    original = _phase(contextual, "A", 0.8)
    _phase(baseline, "A-baseline", 0.8)
    intervening = (
        _phase(contextual, "B", 0.8),
        _phase(contextual, "C", 1.3),
        _phase(contextual, "D", -1.1),
    )
    for label, coefficient in (
        ("B", 0.8),
        ("C", 1.3),
        ("D", -1.1),
    ):
        _phase(baseline, f"{label}-baseline", coefficient)

    returned = _phase(contextual, "A-return", 0.8, count=3)
    baseline_returned = _phase(
        baseline,
        "A-return-baseline",
        0.8,
        count=3,
    )

    with pytest.raises(ValueError, match="original target"):
        _qualify(
            original,
            intervening,
            returned,
            baseline_returned,
        )


def test_return_phase_must_match_original_target_function():
    original, intervening, returned, baseline_returned = _experiment()

    contextual = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    wrong_return = _phase(
        contextual,
        "wrong-return",
        0.7,
        count=3,
    )

    with pytest.raises(ValueError, match="return target"):
        _qualify(
            original,
            intervening,
            wrong_return,
            baseline_returned,
        )


def test_phase_trace_score_tampering_is_rejected():
    original, intervening, returned, baseline_returned = _experiment()
    victim = intervening[0]
    first = victim.trace.steps[0]
    tampered_steps = (
        PrequentialStep(
            case_id=first.case_id,
            prediction=first.prediction,
            score=first.score + 1.0,
            evaluator_context=first.evaluator_context,
        ),
        *victim.trace.steps[1:],
    )
    with pytest.raises(ValueError, match="score"):
        RegimeReturnPhaseEvidence(
            regime_id=victim.regime_id,
            cases=victim.cases,
            trace=PrequentialTrace(steps=tampered_steps),
        )
