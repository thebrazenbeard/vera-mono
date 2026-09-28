from vera_core.adaptive_linear import (
    ContextualOnlineLinearPredictor,
    OnlineLinearPredictor,
    squared_error,
)
from vera_core.prequential_evaluation import PrequentialCase, evaluate_prequential


def _cases(coefficient: float, *, start: int, count: int):
    return [
        PrequentialCase(
            case_id=f"regime-{start + index}",
            model_input=(1.0 if index % 2 == 0 else -1.0,),
            expected=coefficient * (1.0 if index % 2 == 0 else -1.0),
        )
        for index in range(count)
    ]


def _run(learner, coefficient: float, *, start: int, count: int):
    return evaluate_prequential(
        _cases(coefficient, start=start, count=count),
        predict=learner.predict,
        score=squared_error,
        update=learner.update,
    )


def _train_regime_sequence(learner):
    original = _run(learner, 0.8, start=0, count=24)
    for offset, coefficient in enumerate((-0.4, 1.3, -1.1), start=1):
        _run(
            learner,
            coefficient,
            start=offset * 24,
            count=24,
        )
    returned = _run(learner, 0.8, start=96, count=3)
    return original, returned


def test_regime_return_uses_three_intervening_regimes_without_regime_labels():
    learner = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )

    original, returned = _train_regime_sequence(learner)

    # The first return is allowed to be surprising; the retained expert should
    # be selected after that scored exposure and recover on the next step.
    assert returned.steps[0].score > 0.25
    assert returned.steps[1].score < 0.05

    original_late = sum(step.score for step in original.steps[-4:]) / 4
    assert returned.steps[1].score <= max(0.05, original_late * 50.0)


def test_context_bank_beats_single_context_on_second_return_step():
    contextual = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    baseline = OnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )

    _, contextual_return = _train_regime_sequence(contextual)
    _, baseline_return = _train_regime_sequence(baseline)

    assert contextual_return.steps[1].score < baseline_return.steps[1].score * 0.25


def test_contextual_regime_return_does_not_hide_first_return_failure():
    learner = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    _, returned = _train_regime_sequence(learner)

    assert returned.steps[0].score > returned.steps[1].score
    assert returned.steps[0].score > 0.25
