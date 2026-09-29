from vera_core.prequential_evaluation import (
    PrequentialCase,
    evaluate_prequential,
)


def test_prequential_evaluation_scores_before_learning_and_hides_evaluator_context():
    state = {"value": 0.0}
    calls = []

    def predict(model_input):
        calls.append(("predict", state["value"], model_input))
        return state["value"]

    def score(prediction, expected):
        return (expected - prediction) ** 2

    def update(model_input, expected):
        calls.append(("update", state["value"], model_input))
        state["value"] = expected

    trace = evaluate_prequential(
        (
            PrequentialCase(
                case_id="a",
                model_input="input-a",
                expected=0.5,
                evaluator_context={"regime": "A"},
            ),
            PrequentialCase(
                case_id="b",
                model_input="input-b",
                expected=0.25,
                evaluator_context={"regime": "B"},
            ),
        ),
        predict=predict,
        score=score,
        update=update,
    )

    assert calls == [
        ("predict", 0.0, "input-a"),
        ("update", 0.0, "input-a"),
        ("predict", 0.5, "input-b"),
        ("update", 0.5, "input-b"),
    ]
    assert [step.score for step in trace.steps] == [0.25, 0.0625]
    assert [step.evaluator_context["regime"] for step in trace.steps] == ["A", "B"]
