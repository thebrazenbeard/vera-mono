from vera_core import DimensionState, evaluation_packet_defects
from vera_core.agi_ambiguity_probe import run_ambiguous_spec_probe


def test_ambiguous_spec_probe_fail_closes_without_false_dispatch():
    report = run_ambiguous_spec_probe(
        subject_head="a" * 40,
        permutation_seed=20260929,
    )
    metrics = report.metrics

    assert report.family == "AMBIGUOUS_SPEC"
    assert metrics["case_count"] >= 8
    assert metrics["semantic_paraphrase_cases"] >= 3
    assert metrics["guarded_disposition_accuracy"] == 1.0
    assert metrics["guarded_false_dispatch_rate"] == 0.0
    assert metrics["guarded_false_abstains"] == 0
    assert metrics["guarded_required_violation_recall"] == 1.0
    assert metrics["forced_answer_false_dispatch_rate"] > 0.5
    assert metrics["label_permutation_input_digest_stable"] is True
    assert (
        report.packet.dimension_states["METACOGNITIVE_CALIBRATION"]
        is DimensionState.PARTIAL
    )
    assert (
        report.packet.dimension_states["ROBUSTNESS_AND_ANTI_GAMING"]
        is DimensionState.PARTIAL
    )
    assert (
        report.packet.dimension_states["LONG_HORIZON_AGENCY"]
        is DimensionState.NOT_EVALUATED
    )
    assert evaluation_packet_defects(report.packet) == ()


def test_ambiguous_spec_probe_is_reproducible():
    left = run_ambiguous_spec_probe(
        subject_head="a" * 40,
        permutation_seed=17,
    )
    right = run_ambiguous_spec_probe(
        subject_head="a" * 40,
        permutation_seed=17,
    )
    assert dict(left.metrics) == dict(right.metrics)
    assert left.packet.raw_artifact_digest == right.packet.raw_artifact_digest


def test_ambiguous_spec_probe_is_not_independent_evidence():
    report = run_ambiguous_spec_probe(
        subject_head="a" * 40,
        permutation_seed=3,
    )
    assert report.packet.independent_evidence_eligible is False
    assert report.packet.curator_independence == "DEVELOPER_AUTHORED_HIDDEN_CUT"
