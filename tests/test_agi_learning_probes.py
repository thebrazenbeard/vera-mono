from vera_core import DimensionState, evaluation_packet_defects
from vera_core.agi_learning_probes import (
    run_compositional_transfer_probe,
    run_novel_mapping_probe,
    run_regime_return_probe,
)


def test_regime_return_probe_measures_retention_against_naive_baseline():
    report = run_regime_return_probe(seed=20260929, subject_head="a" * 40)
    metrics = report.metrics

    assert report.family == "REGIME_RETURN"
    assert metrics["intervening_regimes"] >= 3
    assert metrics["context_count"] >= 4
    assert metrics["candidate_second_return_error"] < 0.05
    assert (
        metrics["candidate_second_return_error"]
        < metrics["naive_second_return_error"]
    )
    assert (
        report.packet.dimension_states["RETENTION_AND_INTERFERENCE"]
        is DimensionState.PARTIAL
    )
    assert evaluation_packet_defects(report.packet) == ()


def test_regime_return_probe_is_reproducible_for_exact_seed():
    left = run_regime_return_probe(seed=17, subject_head="a" * 40)
    right = run_regime_return_probe(seed=17, subject_head="a" * 40)
    assert dict(left.metrics) == dict(right.metrics)
    assert left.packet.raw_artifact_digest == right.packet.raw_artifact_digest


def test_compositional_probe_reuses_primitives_on_unseen_compositions():
    report = run_compositional_transfer_probe(seed=20260929, subject_head="a" * 40)
    metrics = report.metrics

    assert report.family == "COMPOSITIONAL_TRANSFER"
    assert metrics["all_holdouts_unseen"] is True
    assert metrics["candidate_mse"] < 0.01
    assert metrics["candidate_mse"] < metrics["memorizer_mse"] * 0.1
    assert (
        report.packet.dimension_states["NOVEL_TASK_TRANSFER"]
        is DimensionState.PARTIAL
    )
    assert (
        report.packet.dimension_states["CROSS_DOMAIN_BREADTH"]
        is DimensionState.NOT_EVALUATED
    )
    assert evaluation_packet_defects(report.packet) == ()


def test_synthetic_probe_packets_do_not_masquerade_as_independent_evidence():
    retention = run_regime_return_probe(seed=3, subject_head="a" * 40)
    composition = run_compositional_transfer_probe(seed=3, subject_head="a" * 40)

    assert retention.packet.independent_evidence_eligible is False
    assert composition.packet.independent_evidence_eligible is False
    assert retention.packet.curator_independence == "DEVELOPER_AUTHORED_HIDDEN_CUT"
    assert composition.packet.developer_item_access is True


def test_novel_mapping_probe_measures_bounded_adaptation():
    report = run_novel_mapping_probe(seed=20260929, subject_head="a" * 40)
    metrics = report.metrics

    assert report.family == "NOVEL_MAPPING"
    assert metrics["first_exposure_scored_before_update"] is True
    assert metrics["samples_to_threshold"] <= 12
    assert metrics["candidate_tail_mse"] < 0.01
    assert metrics["candidate_tail_mse"] < metrics["frozen_tail_mse"] * 0.1
    assert (
        report.packet.dimension_states["LEARNING_EFFICIENCY"]
        is DimensionState.PARTIAL
    )
    assert (
        report.packet.dimension_states["NOVEL_TASK_TRANSFER"]
        is DimensionState.PARTIAL
    )
    assert evaluation_packet_defects(report.packet) == ()


def test_novel_mapping_probe_exact_seed_is_reproducible():
    left = run_novel_mapping_probe(seed=811, subject_head="a" * 40)
    right = run_novel_mapping_probe(seed=811, subject_head="a" * 40)
    assert dict(left.metrics) == dict(right.metrics)
    assert left.packet.raw_artifact_digest == right.packet.raw_artifact_digest
