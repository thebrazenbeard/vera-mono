from vera_core import DimensionState, evaluation_packet_defects
from vera_core.agi_long_horizon_probe import run_long_horizon_probe


def test_long_horizon_probe_recovers_corrects_and_finishes():
    report = run_long_horizon_probe(
        subject_head="a" * 40,
        workspace_dir=None,
    )
    m = report.metrics

    assert report.family == "LONG_HORIZON"
    assert m["step_count"] == 4
    assert m["restart_count"] == 1
    assert m["correction_count"] == 1
    assert m["duplicate_completed_steps"] == 0
    assert m["dependency_violations"] == 0
    assert m["stale_fence_rejected"] is True
    assert m["goal_completed"] is True
    assert (
        report.packet.dimension_states["LONG_HORIZON_AGENCY"]
        is DimensionState.PARTIAL
    )
    assert evaluation_packet_defects(report.packet) == ()


def test_long_horizon_probe_is_not_independent_or_general_agency():
    report = run_long_horizon_probe(
        subject_head="a" * 40,
        workspace_dir=None,
    )
    assert report.packet.independent_evidence_eligible is False
    assert "NOT_AGI" in report.claim_ceiling
