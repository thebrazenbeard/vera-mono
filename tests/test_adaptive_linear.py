from vera_core.adaptive_linear import OnlineLinearPredictor, squared_error
from vera_core.prequential_evaluation import PrequentialCase, evaluate_prequential


def _cases(coefficient: float, *, start: int, count: int) -> list[PrequentialCase]:
    return [
        PrequentialCase(
            case_id=f"c-{index}",
            model_input=(1.0 if index % 2 == 0 else -1.0,),
            expected=coefficient * (1.0 if index % 2 == 0 else -1.0),
            evaluator_context={"coefficient": coefficient},
        )
        for index in range(start, start + count)
    ]


def _run(learner: OnlineLinearPredictor, cases: list[PrequentialCase]):
    return evaluate_prequential(
        cases,
        predict=learner.predict,
        score=squared_error,
        update=learner.update,
    )


def test_online_learner_improves_prequentially_without_same_case_leakage():
    learner = OnlineLinearPredictor.zeros(dimension=1, learning_rate=0.25)
    trace = _run(learner, _cases(0.8, start=0, count=24))
    early = sum(step.score for step in trace.steps[:4]) / 4
    late = sum(step.score for step in trace.steps[-4:]) / 4
    assert trace.steps[0].prediction == 0.0
    assert late < early * 0.05


def test_regime_change_adapts_while_exposing_retention_loss():
    learner = OnlineLinearPredictor.zeros(dimension=1, learning_rate=0.25)
    _run(learner, _cases(0.8, start=0, count=24))
    before = learner.snapshot()
    changed = _run(learner, _cases(-0.4, start=24, count=24))
    after = learner.snapshot()
    assert sum(s.score for s in changed.steps[-4:]) < sum(s.score for s in changed.steps[:4])
    assert before[0] > 0.7
    assert after[0] < -0.3


def test_retention_probe_detects_catastrophic_loss_of_prior_mapping():
    learner = OnlineLinearPredictor.zeros(dimension=1, learning_rate=0.25)
    original = _cases(0.8, start=0, count=24)
    _run(learner, original)
    retained_before = squared_error(learner.predict((1.0,)), 0.8)
    _run(learner, _cases(-0.4, start=24, count=24))
    retained_after = squared_error(learner.predict((1.0,)), 0.8)
    assert retained_before < 0.001
    assert retained_after > 1.0


def test_evaluator_context_cannot_enter_learner_callbacks():
    learner = OnlineLinearPredictor.zeros(dimension=1, learning_rate=0.25)
    trace = _run(learner, _cases(0.5, start=0, count=2))
    assert trace.steps[0].evaluator_context["coefficient"] == 0.5
    assert learner.dimension == 1
