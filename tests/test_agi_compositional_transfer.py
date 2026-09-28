import hashlib
import json
from pathlib import Path

import jsonschema

from vera_core import (
    AGIContaminationDisclosure,
    AffinePrimitiveLearner,
    CompositionalTransferThresholds,
    HeldOutCase,
    HeldOutProbe,
    PrimitiveProgramMemorizer,
    qualify_compositional_transfer,
    run_held_out_probe,
)


def _trained_subjects():
    learner = AffinePrimitiveLearner()
    baseline = PrimitiveProgramMemorizer()
    examples = (
        ("double_plus_one", 0.0, 1.0),
        ("double_plus_one", 2.0, 5.0),
        ("minus_three", 0.0, -3.0),
        ("minus_three", 4.0, 1.0),
    )
    for primitive, x, y in examples:
        learner.observe(primitive, x=x, y=y)
        baseline.observe((primitive,), x=x, y=y)
    return learner, baseline


def _probe(probe_id="compose-hidden-1"):
    cases = (
        HeldOutCase(
            case_id="a",
            model_input={
                "program": ["double_plus_one", "minus_three"],
                "x": 5.0,
            },
            expected=8.0,
        ),
        HeldOutCase(
            case_id="b",
            model_input={
                "program": ["minus_three", "double_plus_one"],
                "x": 5.0,
            },
            expected=5.0,
        ),
        HeldOutCase(
            case_id="c",
            model_input={
                "program": ["double_plus_one", "minus_three"],
                "x": -1.0,
            },
            expected=-4.0,
        ),
        HeldOutCase(
            case_id="d",
            model_input={
                "program": ["minus_three", "double_plus_one"],
                "x": 4.0,
            },
            expected=3.0,
        ),
    )
    return HeldOutProbe(
        probe_id=probe_id,
        family="COMPOSITIONAL_TRANSFER",
        curator_independence="INDEPENDENT_MODEL",
        cases=cases,
    )


def _disclosure():
    return AGIContaminationDisclosure(
        training_overlap="NONE_KNOWN",
        post_disclosure_tuning=False,
        developer_item_access=False,
        tool_access=(),
    )


def _run_pair(probe=None):
    probe = probe or _probe()
    learner, baseline = _trained_subjects()

    learned = run_held_out_probe(
        probe,
        subject=lambda item: learner.predict(
            tuple(item["program"]),
            float(item["x"]),
        ),
        score=lambda prediction, expected: abs(prediction - expected) <= 1e-9,
        contamination=_disclosure(),
    )
    baseline_result = run_held_out_probe(
        probe,
        subject=lambda item: baseline.predict(
            tuple(item["program"]),
            float(item["x"]),
        ),
        score=lambda prediction, expected: (
            prediction is not None
            and abs(prediction - expected) <= 1e-9
        ),
        contamination=_disclosure(),
    )
    return learned, baseline_result


def _thresholds():
    return CompositionalTransferThresholds(
        absolute_tolerance=1e-9,
        min_unseen_success_rate=0.75,
        min_ablation_delta=0.50,
    )


def test_affine_primitive_learner_composes_unseen_programs():
    learner, _ = _trained_subjects()
    assert learner.seen_programs == frozenset()
    assert learner.predict(("double_plus_one", "minus_three"), 5.0) == 8.0
    assert learner.predict(("minus_three", "double_plus_one"), 5.0) == 5.0


def test_primitive_memorizer_gets_same_singleton_training_but_not_composition():
    _, baseline = _trained_subjects()
    assert baseline.predict(("double_plus_one",), 2.0) == 5.0
    assert baseline.predict(("minus_three",), 4.0) == 1.0
    assert baseline.predict(("double_plus_one", "minus_three"), 5.0) is None


def test_compositional_measurement_stays_partial_pending_independent_review():
    learned, baseline = _run_pair()
    result = qualify_compositional_transfer(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="COMPOSITIONAL_TRANSFER_MEASUREMENT_ONLY_NOT_AGI",
    )

    assert result.metrics.unseen_composition_success_rate == 1.0
    assert result.metrics.baseline_success_rate == 0.0
    assert result.metrics.ablation_delta == 1.0
    assert result.metrics.error_taxonomy == {
        "CORRECT": 4,
        "UNRESOLVED": 0,
        "WRONG": 0,
    }
    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "PARTIAL",
        "CROSS_DOMAIN_BREADTH": "PARTIAL",
    }

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result.packet, schema)


def test_compositional_measurement_binds_learner_and_baseline_raw_evidence():
    learned, baseline = _run_pair()
    result = qualify_compositional_transfer(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="2" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="COMPOSITIONAL_TRANSFER_MEASUREMENT_ONLY_NOT_AGI",
    )

    artifact = json.loads(result.qualification_artifact_json)
    assert artifact["learner_raw_artifact_digest"] == learned.raw_artifact_digest
    assert artifact["baseline_raw_artifact_digest"] == baseline.raw_artifact_digest
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


def test_compositional_failure_is_fail_closed_and_preserves_error_taxonomy():
    probe = _probe()
    _, baseline = _run_pair(probe)
    learned = run_held_out_probe(
        probe,
        subject=lambda item: None if item["x"] == 5.0 else 99.0,
        score=lambda prediction, expected: (
            prediction is not None
            and abs(prediction - expected) <= 1e-9
        ),
        contamination=_disclosure(),
    )
    result = qualify_compositional_transfer(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="3" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="COMPOSITIONAL_TRANSFER_MEASUREMENT_ONLY_NOT_AGI",
    )

    assert result.metrics.error_taxonomy == {
        "CORRECT": 0,
        "UNRESOLVED": 2,
        "WRONG": 2,
    }
    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "FAIL",
        "CROSS_DOMAIN_BREADTH": "FAIL",
    }


def test_compositional_qualification_rejects_mismatched_hidden_cuts():
    learned, _ = _run_pair()
    _, other_baseline = _run_pair(_probe("different-cut"))

    try:
        qualify_compositional_transfer(
            learned,
            baseline=other_baseline,
            thresholds=_thresholds(),
            repository="thebrazenbeard/vera-mono",
            exact_head="4" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "same held-out cut" in str(exc)
    else:
        raise AssertionError("mismatched compositional cut was accepted")


def test_independence_metadata_alone_cannot_unlock_compositional_pass():
    learned, baseline = _run_pair()
    result = qualify_compositional_transfer(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="5" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="COMPOSITIONAL_TRANSFER_MEASUREMENT_ONLY_NOT_AGI",
    )
    assert "PASS" not in result.packet["dimension_states"].values()


def test_affine_primitive_requires_identifiable_primitive_before_composition():
    learner = AffinePrimitiveLearner()
    learner.observe("double_plus_one", x=1.0, y=3.0)
    try:
        learner.predict(("double_plus_one",), 2.0)
    except ValueError as exc:
        assert "not identified" in str(exc)
    else:
        raise AssertionError("underidentified primitive was used")
