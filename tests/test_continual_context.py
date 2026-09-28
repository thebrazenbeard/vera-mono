import vera_core.adaptive_linear as adaptive


def test_contextual_learner_api_is_available():
    assert hasattr(adaptive, "ContextualOnlineLinearPredictor")


def _cases(coefficient: float, start: int, count: int):
    from vera_core.prequential_evaluation import PrequentialCase
    return [
        PrequentialCase(
            case_id=f"ctx-{i}",
            model_input=(1.0 if i % 2 == 0 else -1.0,),
            expected=coefficient * (1.0 if i % 2 == 0 else -1.0),
        )
        for i in range(start, start + count)
    ]


def _run(learner, cases):
    from vera_core.prequential_evaluation import evaluate_prequential
    return evaluate_prequential(
        cases,
        predict=learner.predict,
        score=adaptive.squared_error,
        update=learner.update,
    )


def test_contextual_learner_recalls_prior_regime_after_one_surprise():
    learner = adaptive.ContextualOnlineLinearPredictor.zeros(
        dimension=1, learning_rate=0.25
    )
    _run(learner, _cases(0.8, 0, 24))
    _run(learner, _cases(-0.4, 24, 24))
    assert learner.context_count == 2
    recalled = _run(learner, _cases(0.8, 48, 3))
    assert recalled.steps[0].score > 0.5
    assert recalled.steps[1].score < 0.05
