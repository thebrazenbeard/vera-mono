import hashlib

import pytest

from research.goal1_evaluator.causal_trial import (
    ARMS, CausalTrialController, digest,
)


def controller():
    return CausalTrialController("GOAL1-LIVE-20261023-02")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def commit(c, arm, case, prediction="A", prompt=None, response="model response", budget=1, challenge_view_digest=None):
    # Prompt and response hashes describe actual submitted/returned bytes. The
    # challenge-view digest is a separate controller-issued-case identity.
    return c.commit_prediction(
        arm=arm,
        challenge_id=case["challenge_id"],
        prediction=prediction,
        challenge_view_digest=challenge_view_digest or digest(case),
        model_prompt_sha256=sha256(prompt if prompt is not None else f"QVR prompt for {arm}: {case}"),
        model_response_sha256=sha256(response),
        budget_units=budget,
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


def test_different_honest_arm_prompts_are_accepted_for_same_public_challenge():
    c = controller()
    case = c.issue("train")[0]
    learned_prompt = f"Use revised rule context. Case={case['features']}"
    frozen_prompt = f"Use frozen baseline only. Case={case['features']}"
    learned = commit(c, "LEARNED", case, "A", prompt=learned_prompt, response="A")
    frozen = commit(c, "FROZEN", case, "B", prompt=frozen_prompt, response="B")
    assert learned["challenge_view_digest"] == frozen["challenge_view_digest"] == digest(case)
    assert learned["model_prompt_sha256"] == sha256(learned_prompt)
    assert frozen["model_prompt_sha256"] == sha256(frozen_prompt)
    assert learned["model_prompt_sha256"] != frozen["model_prompt_sha256"]
    assert learned["model_response_sha256"] == sha256("A")
    assert frozen["model_response_sha256"] == sha256("B")
    assert learned["sequence"] < frozen["sequence"]


def test_incorrect_challenge_binding_rejected():
    c = controller()
    case, other = c.issue("train")[:2]
    with pytest.raises(ValueError, match="challenge view digest mismatch"):
        commit(c, "LEARNED", case, challenge_view_digest=digest(other))


def test_duplicate_attempt_and_reused_arm_case_rejected():
    c = controller()
    case = c.issue("train")[0]
    first = commit(c, "LEARNED", case, "A")
    assert first["prediction"] == "A"
    with pytest.raises(ValueError, match="duplicate attempt"):
        commit(c, "LEARNED", case, "B")


def test_prediction_and_receipt_fields_are_immutable_after_commit():
    c = controller()
    case = c.issue("train")[0]
    receipt = commit(c, "LEARNED", case, "A", response="first response")
    before = c.audit_receipts()
    # A later alternate answer cannot overwrite the first committed prediction.
    with pytest.raises(ValueError, match="duplicate attempt"):
        commit(c, "LEARNED", case, "B", response="changed response")
    assert c.audit_receipts() == before
    assert receipt["prediction"] == "A"


def test_budget_mismatch_and_invalid_prediction_rejected():
    c = controller()
    case = c.issue("train")[0]
    with pytest.raises(ValueError, match="budget mismatch"):
        commit(c, "LEARNED", case, budget=2)
    with pytest.raises(ValueError, match="invalid prediction"):
        commit(c, "LEARNED", case, prediction="C")


def test_nominal_budget_is_not_measured_resource_usage():
    c = controller()
    case = c.issue("train")[0]
    receipt = commit(c, "LEARNED", case)
    assert receipt["budget_units"] == 1
    assert receipt["budget_kind"] == "protocol_counter_not_measured_usage"
    assert receipt["resource_usage_measured"] is False


def test_forged_order_not_accepted_as_client_input():
    c = controller()
    case = c.issue("train")[0]
    with pytest.raises(TypeError):
        c.commit_prediction(
            arm="LEARNED", challenge_id=case["challenge_id"], prediction="A",
            challenge_view_digest=digest(case),
            model_prompt_sha256=sha256("prompt"), model_response_sha256=sha256("response"),
            budget_units=1, sequence=999,
        )
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
    assert all(row["resource_usage_measured"] is False for row in scores.values())
    with pytest.raises(ValueError, match="closed"):
        commit(c, "LEARNED", holdout[0], "B")


def test_heldout_truth_is_never_released_as_feedback():
    c = controller()
    case = c.issue("holdout")[0]
    # No receipt is needed to establish the split restriction; even after a
    # valid held-out prediction, feedback remains forbidden.
    with pytest.raises(ValueError, match="training cases"):
        c.release_feedback(arm="LEARNED", challenge_id=case["challenge_id"])
    commit(c, "LEARNED", case, "A")
    with pytest.raises(ValueError, match="training cases"):
        c.release_feedback(arm="LEARNED", challenge_id=case["challenge_id"])
