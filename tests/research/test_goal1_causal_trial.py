import pytest

from research.goal1_evaluator.causal_trial import (
    ARMS, CausalTrialController, digest,
)


def controller():
    return CausalTrialController("GOAL1-LIVE-20261023-02")


def commit(c, arm, case, prediction="A", budget=1):
    return c.commit_prediction(
        arm=arm, challenge_id=case["challenge_id"], prediction=prediction,
        prompt_digest=digest(case), budget_units=budget,
    )


def test_labels_are_withheld_and_protocol_is_frozen_before_predictions():
    c = controller()
    train = c.issue("train")
    holdout = c.issue("holdout")
    assert len(c.challenge_ids_frozen) == 8
    assert len(train) == 4 and len(holdout) == 4
    assert all(set(case) == {"challenge_id", "features"} for case in train + holdout)
    assert c.scoring_method_frozen.startswith("exact-match accuracy")
    assert c.budgets_frozen == {"units_per_prediction": 1, "max_attempts_per_arm_case": 1}
    assert "stop after all 4 holdout cases" in c.stopping_rule_frozen


def test_feedback_requires_committed_prediction_and_is_one_use():
    c = controller()
    case = c.issue("train")[0]
    with pytest.raises(ValueError, match="before feedback"):
        c.release_feedback(arm="LEARNED", challenge_id=case["challenge_id"])
    commit(c, "LEARNED", case, "B")
    label = c.release_feedback(arm="LEARNED", challenge_id=case["challenge_id"])
    assert label in ("A", "B")
    with pytest.raises(ValueError, match="one-use"):
        c.release_feedback(arm="LEARNED", challenge_id=case["challenge_id"])


def test_four_arms_have_distinct_feedback_policies():
    c = controller()
    cases = c.issue("train")
    for arm in ARMS:
        for case in cases:
            commit(c, arm, case, "A")
    assert all(c.release_feedback(arm="LEARNED", challenge_id=case["challenge_id"]) in ("A", "B") for case in cases)
    assert all(c.release_feedback(arm="PLACEBO", challenge_id=case["challenge_id"]) == "A" for case in cases)
    assert all(c.release_feedback(arm="SHUFFLED", challenge_id=case["challenge_id"]) in ("A", "B") for case in cases)
    with pytest.raises(ValueError, match="no feedback"):
        c.release_feedback(arm="FROZEN", challenge_id=cases[0]["challenge_id"])


def test_duplicate_attempt_reused_case_and_prompt_mismatch_rejected():
    c = controller()
    case = c.issue("train")[0]
    commit(c, "LEARNED", case)
    with pytest.raises(ValueError, match="duplicate attempt"):
        commit(c, "LEARNED", case, "B")
    with pytest.raises(ValueError, match="duplicate attempt"):
        commit(c, "LEARNED", c.issue("train")[0])
    with pytest.raises(ValueError, match="prompt digest"):
        c.commit_prediction(arm="FROZEN", challenge_id=case["challenge_id"], prediction="A",
                            prompt_digest="0" * 64, budget_units=1)


def test_budget_mismatch_and_invalid_prediction_rejected():
    c = controller()
    case = c.issue("train")[0]
    with pytest.raises(ValueError, match="budget mismatch"):
        commit(c, "LEARNED", case, budget=2)
    with pytest.raises(ValueError, match="invalid prediction"):
        commit(c, "LEARNED", case, prediction="C")


def test_forged_order_not_accepted_as_client_input():
    c = controller()
    case = c.issue("train")[0]
    with pytest.raises(TypeError):
        c.commit_prediction(arm="LEARNED", challenge_id=case["challenge_id"], prediction="A",
                            prompt_digest=digest(case), budget_units=1, sequence=999)
    receipt = commit(c, "LEARNED", case)
    assert receipt["sequence"] == 1


def test_changed_prompt_or_stored_correction_is_not_learning_evidence():
    c = controller()
    case = c.issue("train")[0]
    before = c.audit_receipts()
    c.record_correction_context(arm="LEARNED", challenge_id=case["challenge_id"], text="Always answer B")
    after = c.audit_receipts()
    assert before == after
    assert c.correction_context_is_learning_evidence("LEARNED") is False


def test_all_four_arms_score_only_after_complete_holdout_batch():
    c = controller()
    holdout = c.issue("holdout")
    with pytest.raises(ValueError, match="all holdout predictions"):
        c.score()
    for arm in ARMS:
        for case in holdout:
            commit(c, arm, case, "A")
    scores = c.score()
    assert set(scores) == set(ARMS)
    assert all(row["scored_cases"] == 4 and row["budget_units"] == 4 for row in scores.values())
    with pytest.raises(ValueError, match="closed"):
        commit(c, "LEARNED", holdout[0], "B")
