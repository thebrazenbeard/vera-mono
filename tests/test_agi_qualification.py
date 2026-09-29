from __future__ import annotations

from vera_core.agi_qualification import (
    AGIEvaluationPacket,
    AggregateQualificationState,
    DimensionState,
    IndependentReviewState,
    aggregate_qualification,
    evaluation_packet_defects,
)


REQUIRED = (
    "CROSS_DOMAIN_BREADTH",
    "NOVEL_TASK_TRANSFER",
    "LEARNING_EFFICIENCY",
    "RETENTION_AND_INTERFERENCE",
    "LONG_HORIZON_AGENCY",
    "METACOGNITIVE_CALIBRATION",
    "ROBUSTNESS_AND_ANTI_GAMING",
    "EXTERNAL_GENERALIZATION",
)


def _states(value: DimensionState) -> dict[str, DimensionState]:
    return {dimension: value for dimension in REQUIRED}
def _packet(
    packet_id: str,
    *,
    dimensions: dict[str, DimensionState],
    overlap: str = "NONE_KNOWN",
    post_tuning: bool = False,
    held_out: bool = True,
    negative_results_preserved: bool = True,
    curator: str = "DEVELOPER_AUTHORED_HIDDEN_CUT",
    developer_item_access: bool = True,
) -> AGIEvaluationPacket:
    return AGIEvaluationPacket(
        packet_id=packet_id,
        subject_head="a" * 40,
        family="NOVEL_MAPPING",
        held_out=held_out,
        curator_independence=curator,
        training_overlap=overlap,
        post_disclosure_tuning=post_tuning,
        developer_item_access=developer_item_access,
        tool_access=("pytest",),
        attempted=4,
        passed=3,
        failed=1,
        raw_artifact_digest="b" * 64,
        negative_results_preserved=negative_results_preserved,
        dimension_states=dimensions,
    )
def test_aggregate_is_weakest_link_across_required_dimensions():
    states = _states(DimensionState.PASS)
    states["RETENTION_AND_INTERFERENCE"] = DimensionState.FAIL
    result = aggregate_qualification(
        subject_head="a" * 40,
        dimension_states=states,
        independent_review_state=IndependentReviewState.NOT_REVIEWED,
    )
    assert result.aggregate_state is AggregateQualificationState.FAILS_CURRENT_CONTRACT
    assert result.dimension_states["RETENTION_AND_INTERFERENCE"] is DimensionState.FAIL
    assert result.claim_ceiling == "CURRENT_CONTRACT_RESEARCH_QUALIFICATION_ONLY_NOT_AGI"


def test_all_pass_is_not_independently_reviewed_without_independent_review():
    result = aggregate_qualification(
        subject_head="a" * 40,
        dimension_states=_states(DimensionState.PASS),
        independent_review_state=IndependentReviewState.NOT_REVIEWED,
    )
    assert result.aggregate_state is AggregateQualificationState.SURVIVES_CURRENT_CONTRACT


def test_all_pass_can_reach_independently_reviewed_state_only_with_review():
    result = aggregate_qualification(
        subject_head="a" * 40,
        dimension_states=_states(DimensionState.PASS),
        independent_review_state=IndependentReviewState.SURVIVES_INDEPENDENT_REVIEW,
    )
    assert (
        result.aggregate_state
        is AggregateQualificationState.SURVIVES_CURRENT_CONTRACT_INDEPENDENTLY_REVIEWED
    )


def test_partial_or_missing_dimensions_cannot_be_promoted():
    states = _states(DimensionState.PASS)
    states["EXTERNAL_GENERALIZATION"] = DimensionState.NOT_EVALUATED
    result = aggregate_qualification(
        subject_head="a" * 40,
        dimension_states=states,
        independent_review_state=IndependentReviewState.SURVIVES_INDEPENDENT_REVIEW,
    )
    assert result.aggregate_state is AggregateQualificationState.PARTIALLY_EVALUATED


def test_contaminated_or_post_tuned_packet_cannot_establish_pass():
    packet = _packet(
        "contaminated",
        dimensions={"NOVEL_TASK_TRANSFER": DimensionState.PASS},
        overlap="CONFIRMED",
        post_tuning=True,
    )
    defects = evaluation_packet_defects(packet)
    assert "training overlap is not NONE_KNOWN for a PASS claim" in defects
    assert "post-disclosure tuning invalidates this held-out cut" in defects


def test_unpreserved_negative_results_and_nonheldout_probe_are_defects():
    packet = _packet(
        "bad-boundary",
        dimensions={"NOVEL_TASK_TRANSFER": DimensionState.PARTIAL},
        held_out=False,
        negative_results_preserved=False,
    )
    defects = evaluation_packet_defects(packet)
    assert "probe is not held out" in defects
    assert "negative results were not preserved" in defects


def test_developer_authored_packet_is_not_independent_evidence():
    packet = _packet(
        "developer-cut",
        dimensions={"NOVEL_TASK_TRANSFER": DimensionState.PASS},
        curator="DEVELOPER_AUTHORED_HIDDEN_CUT",
        developer_item_access=True,
    )
    assert evaluation_packet_defects(packet) == ()
    assert packet.independent_evidence_eligible is False
