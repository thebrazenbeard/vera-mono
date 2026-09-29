import hashlib
import json
from pathlib import Path

import jsonschema

from vera_core import (
    AGIContaminationDisclosure,
    HeldOutCase,
    HeldOutProbe,
    NovelMappingThresholds,
    qualify_novel_mapping,
    run_held_out_probe,
    run_prequential_held_out_probe,
)
from vera_core.adaptive_linear import OnlineLinearPredictor


def _probe(curator: str = "INDEPENDENT_MODEL") -> HeldOutProbe:
    return HeldOutProbe(
        probe_id="novel-linear-hidden-1",
        family="NOVEL_MAPPING",
        curator_independence=curator,
        cases=tuple(
            HeldOutCase(
                case_id=f"case-{index}",
                model_input=(1.0 if index % 2 == 0 else -1.0,),
                expected=0.8 * (1.0 if index % 2 == 0 else -1.0),
            )
            for index in range(24)
        ),
    )


def _contamination(*, developer_item_access: bool = False):
    return AGIContaminationDisclosure(
        training_overlap="NONE_KNOWN",
        post_disclosure_tuning=False,
        developer_item_access=developer_item_access,
        tool_access=(),
    )


def _run_pair(
    curator: str = "INDEPENDENT_MODEL",
    *,
    developer_item_access: bool = False,
):
    probe = _probe(curator)
    disclosure = _contamination(
        developer_item_access=developer_item_access
    )
    learner = OnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )
    learned = run_prequential_held_out_probe(
        probe,
        predict=learner.predict,
        score=lambda prediction, expected: abs(
            prediction - expected
        ) <= 0.1,
        update=learner.update,
        contamination=disclosure,
    )
    baseline = run_held_out_probe(
        probe,
        subject=lambda model_input: 0.0,
        score=lambda prediction, expected: abs(
            prediction - expected
        ) <= 0.1,
        contamination=disclosure,
    )
    return learned, baseline


def _thresholds() -> NovelMappingThresholds:
    return NovelMappingThresholds(
        late_window=4,
        max_late_mse=0.001,
        threshold_mse=0.01,
        max_samples_to_threshold=12,
        min_baseline_delta=0.5,
        min_baseline_ratio=10.0,
    )


def test_novel_mapping_measurement_stays_partial_pending_independent_review():
    learned, baseline = _run_pair()
    result = qualify_novel_mapping(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="a" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="NOVEL_MAPPING_DIMENSION_EVIDENCE_ONLY_NOT_AGI",
    )

    assert result.metrics.late_mse <= 0.001
    assert result.metrics.samples_to_threshold == 9
    assert result.metrics.baseline_delta > 0.5
    assert result.metrics.baseline_ratio > 10.0
    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "PARTIAL",
        "LEARNING_EFFICIENCY": "PARTIAL",
    }

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result.packet, schema)


def test_developer_authored_cut_cannot_promote_dimension_to_pass():
    learned, baseline = _run_pair(
        "DEVELOPER_AUTHORED_HIDDEN_CUT",
        developer_item_access=True,
    )
    result = qualify_novel_mapping(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="b" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="DEVELOPER_CUT_MECHANICS_ONLY",
    )

    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "PARTIAL",
        "LEARNING_EFFICIENCY": "PARTIAL",
    }


def test_novel_mapping_failure_is_dimension_specific_and_fail_closed():
    learned, baseline = _run_pair()
    result = qualify_novel_mapping(
        learned,
        baseline=baseline,
        thresholds=NovelMappingThresholds(
            late_window=4,
            max_late_mse=0.001,
            threshold_mse=1e-8,
            max_samples_to_threshold=4,
            min_baseline_delta=0.7,
            min_baseline_ratio=10.0,
        ),
        repository="thebrazenbeard/vera-mono",
        exact_head="c" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="NOVEL_MAPPING_DIMENSION_EVIDENCE_ONLY_NOT_AGI",
    )

    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "FAIL",
        "LEARNING_EFFICIENCY": "FAIL",
    }


def test_novel_mapping_qualification_binds_baseline_and_learner_raw_evidence():
    learned, baseline = _run_pair()
    result = qualify_novel_mapping(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="d" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="NOVEL_MAPPING_DIMENSION_EVIDENCE_ONLY_NOT_AGI",
    )

    artifact = json.loads(result.qualification_artifact_json)
    assert artifact["learner_raw_artifact_digest"] == learned.raw_artifact_digest
    assert artifact["baseline_raw_artifact_digest"] == baseline.raw_artifact_digest
    assert artifact["thresholds"]["threshold_mse"] == 0.01
    assert artifact["metrics"]["samples_to_threshold"] == 9
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


def test_novel_mapping_rejects_mismatched_hidden_cuts():
    learned, _ = _run_pair()
    other_probe = HeldOutProbe(
        probe_id="different-cut",
        family="NOVEL_MAPPING",
        curator_independence="INDEPENDENT_MODEL",
        cases=(
            HeldOutCase(
                case_id="other",
                model_input=(1.0,),
                expected=1.0,
            ),
        ),
    )
    other_baseline = run_held_out_probe(
        other_probe,
        subject=lambda model_input: 0.0,
        score=lambda prediction, expected: False,
        contamination=_contamination(),
    )

    try:
        qualify_novel_mapping(
            learned,
            baseline=other_baseline,
            thresholds=_thresholds(),
            repository="thebrazenbeard/vera-mono",
            exact_head="e" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "same held-out cut" in str(exc)
    else:
        raise AssertionError("mismatched baseline cut was accepted")



def test_independence_metadata_alone_cannot_unlock_pass():
    learned, baseline = _run_pair()
    result = qualify_novel_mapping(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="f" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="NOVEL_MAPPING_MEASUREMENT_ONLY",
    )

    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "PARTIAL",
        "LEARNING_EFFICIENCY": "PARTIAL",
    }


def test_novel_mapping_rejects_caller_manipulated_nonzero_baseline():
    learned, _ = _run_pair()
    probe = _probe()
    manipulated = run_held_out_probe(
        probe,
        subject=lambda model_input: 0.79 * model_input[0],
        score=lambda prediction, expected: abs(
            prediction - expected
        ) <= 0.1,
        contamination=_contamination(),
    )

    try:
        qualify_novel_mapping(
            learned,
            baseline=manipulated,
            thresholds=_thresholds(),
            repository="thebrazenbeard/vera-mono",
            exact_head="1" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "canonical zero predictor" in str(exc)
    else:
        raise AssertionError("caller-manipulated baseline was accepted")


def test_novel_mapping_measurement_cannot_promote_global_contract():
    from vera_core import aggregate_agi_qualification

    learned, baseline = _run_pair()
    result = qualify_novel_mapping(
        learned,
        baseline=baseline,
        thresholds=_thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="2" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        claim_ceiling="NOVEL_MAPPING_MEASUREMENT_ONLY",
    )
    aggregate = aggregate_agi_qualification(
        [result.packet],
        subject_head="2" * 40,
        independent_review_state="NOT_REVIEWED",
        claim_ceiling="AGGREGATE_RESEARCH_ONLY_NOT_AGI",
    )

    assert aggregate["aggregate_state"] == "PARTIALLY_EVALUATED"
    assert aggregate["dimension_states"]["CROSS_DOMAIN_BREADTH"] == "NOT_EVALUATED"
    assert aggregate["dimension_states"]["EXTERNAL_GENERALIZATION"] == "NOT_EVALUATED"
