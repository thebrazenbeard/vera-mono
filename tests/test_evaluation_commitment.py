import pytest

from vera_assurance.evaluation_commitment import (
    ComparisonConditions,
    commit_prediction,
    compare_committed_predictions,
    verify_prediction_commitment,
)


def test_prediction_comparison_binds_preoutcome_commitments_and_conditions():
    left = commit_prediction(
        candidate_id="candidate-a",
        step=4,
        prediction={"mean": [0.0], "variance": [1.0]},
    )
    right = commit_prediction(
        candidate_id="candidate-b",
        step=4,
        prediction={"variance": [1.0], "mean": [0.1]},
    )
    conditions = ComparisonConditions(
        information_condition_id="info-1",
        opportunity_condition_id="opp-1",
        resource_condition_id="resource-envelope-1",
        representation_version="rep-1",
    )

    record = compare_committed_predictions(left, right, conditions=conditions)

    assert record.left_commitment == left.commitment
    assert record.right_commitment == right.commitment
    assert record.step == 4
    assert record.conditions == conditions
    assert record.authorization_effect == "NONE"


def test_prediction_commitment_is_canonical_and_cross_step_comparison_fails():
    first = commit_prediction(
        candidate_id="candidate-a",
        step=1,
        prediction={"a": 1, "b": [2, 3]},
    )
    same = commit_prediction(
        candidate_id="candidate-a",
        step=1,
        prediction={"b": [2, 3], "a": 1},
    )
    later = commit_prediction(
        candidate_id="candidate-b",
        step=2,
        prediction={"a": 1, "b": [2, 3]},
    )

    assert first.commitment == same.commitment

    with pytest.raises(ValueError, match="same step"):
        compare_committed_predictions(
            first,
            later,
            conditions=ComparisonConditions(
                information_condition_id="info",
                opportunity_condition_id="opp",
                resource_condition_id="res",
                representation_version="rep",
            ),
        )


def test_prediction_ticket_preserves_immutable_verifiable_snapshot():
    ticket = commit_prediction(
        candidate_id="candidate-a",
        step=3,
        prediction={"mean": [0.25], "variance": [0.5]},
    )

    assert verify_prediction_commitment(ticket) is True
    assert ticket.prediction["mean"] == (0.25,)

    with pytest.raises(TypeError):
        ticket.prediction["mean"] = (9.0,)
