import hashlib
import json

from vera_core import (
    AGIContaminationDisclosure,
    HeldOutCase,
    HeldOutProbe,
    run_held_out_probe,
)


def test_held_out_probe_hides_expected_and_evaluator_context_from_subject():
    seen = []

    probe = HeldOutProbe(
        probe_id="novel-map-1",
        family="NOVEL_MAPPING",
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        cases=(
            HeldOutCase(
                case_id="a",
                model_input={"x": 2},
                expected=6,
                evaluator_context={"hidden_rule": "times-three"},
            ),
        ),
    )

    result = run_held_out_probe(
        probe,
        subject=lambda model_input: seen.append(model_input) or 6,
        score=lambda prediction, expected: prediction == expected,
        contamination=AGIContaminationDisclosure(
            training_overlap="NONE_KNOWN",
            post_disclosure_tuning=False,
            developer_item_access=True,
            tool_access=(),
        ),
    )

    assert seen == [{"x": 2}]
    assert result.attempts[0].passed is True
    assert result.attempts[0].evaluator_context["hidden_rule"] == "times-three"


def test_held_out_probe_preserves_negative_results_and_stable_item_digest():
    probe = HeldOutProbe(
        probe_id="ambiguous-1",
        family="AMBIGUOUS_SPEC",
        curator_independence="INDEPENDENT_MODEL",
        cases=(
            HeldOutCase(case_id="a", model_input="clear", expected="answer"),
            HeldOutCase(case_id="b", model_input="ambiguous", expected="abstain"),
        ),
    )
    contamination = AGIContaminationDisclosure(
        training_overlap="UNKNOWN",
        post_disclosure_tuning=False,
        developer_item_access=False,
        tool_access=("semantic_store",),
    )

    result = run_held_out_probe(
        probe,
        subject=lambda value: "answer",
        score=lambda prediction, expected: prediction == expected,
        contamination=contamination,
    )

    assert [attempt.passed for attempt in result.attempts] == [True, False]
    assert result.attempted == 2
    assert result.passed == 1
    assert result.failed == 1
    assert result.negative_results_preserved is True
    assert len(result.items_digest) == 64
    assert len(result.raw_artifact_digest) == 64

    stable_payload = json.dumps(
        [
            {
                "case_id": "a",
                "model_input": "clear",
                "expected": "answer",
                "evaluator_context": {},
            },
            {
                "case_id": "b",
                "model_input": "ambiguous",
                "expected": "abstain",
                "evaluator_context": {},
            },
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert result.items_digest == hashlib.sha256(stable_payload).hexdigest()


def test_held_out_probe_rejects_post_disclosure_tuning():
    probe = HeldOutProbe(
        probe_id="novel-map-2",
        family="NOVEL_MAPPING",
        curator_independence="EXTERNAL_BENCHMARK",
        cases=(HeldOutCase(case_id="a", model_input=1, expected=2),),
    )

    contamination = AGIContaminationDisclosure(
        training_overlap="POSSIBLE",
        post_disclosure_tuning=True,
        developer_item_access=False,
        tool_access=(),
    )

    try:
        run_held_out_probe(
            probe,
            subject=lambda value: value,
            score=lambda prediction, expected: prediction == expected,
            contamination=contamination,
        )
    except ValueError as exc:
        assert "post-disclosure tuning" in str(exc)
    else:
        raise AssertionError("contaminated held-out cut was evaluated as admissible")



def test_prequential_held_out_scores_before_revealing_answer_to_update():
    from vera_core import run_prequential_held_out_probe

    calls = []
    state = {"factor": 0}

    probe = HeldOutProbe(
        probe_id="novel-map-prequential",
        family="NOVEL_MAPPING",
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        cases=(
            HeldOutCase(case_id="a", model_input=2, expected=6),
            HeldOutCase(case_id="b", model_input=3, expected=9),
        ),
    )

    def predict(model_input):
        calls.append(("predict", model_input, state["factor"]))
        return model_input * state["factor"]

    def update(model_input, expected):
        calls.append(("update", model_input, expected))
        state["factor"] = expected // model_input

    result = run_prequential_held_out_probe(
        probe,
        predict=predict,
        score=lambda prediction, expected: prediction == expected,
        update=update,
        contamination=AGIContaminationDisclosure(
            training_overlap="NONE_KNOWN",
            post_disclosure_tuning=False,
            developer_item_access=True,
            tool_access=(),
        ),
    )

    assert calls == [
        ("predict", 2, 0),
        ("update", 2, 6),
        ("predict", 3, 3),
        ("update", 3, 9),
    ]
    assert [attempt.passed for attempt in result.attempts] == [False, True]
    assert result.attempted == 2
    assert result.failed == 1
    assert result.negative_results_preserved is True



def test_held_out_result_retains_exact_raw_artifact_bound_by_digest():
    result = run_held_out_probe(
        HeldOutProbe(
            probe_id="raw-preservation",
            family="AMBIGUOUS_SPEC",
            curator_independence="INDEPENDENT_MODEL",
            cases=(
                HeldOutCase(
                    case_id="fail",
                    model_input="ambiguous",
                    expected="abstain",
                ),
            ),
        ),
        subject=lambda value: "answer",
        score=lambda prediction, expected: prediction == expected,
        contamination=AGIContaminationDisclosure(
            training_overlap="UNKNOWN",
            post_disclosure_tuning=False,
            developer_item_access=False,
            tool_access=(),
        ),
    )

    raw = json.loads(result.raw_artifact_json)
    assert raw["attempts"][0]["case_id"] == "fail"
    assert raw["attempts"][0]["expected"] == "abstain"
    assert raw["attempts"][0]["passed"] is False
    assert (
        hashlib.sha256(result.raw_artifact_json.encode("utf-8")).hexdigest()
        == result.raw_artifact_digest
    )
