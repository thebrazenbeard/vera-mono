import base64
import hashlib
import tempfile
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from research.goal1_evaluator.causal_trial import (
    ARMS, CausalTrialController, digest,
)
from research.goal1_evaluator.dispatch_attestation import (
    Ed25519DispatchEvidenceVerifier, canonical_attestation_bytes,
)


_invocation_counter = 0


def controller():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    db = tempfile.mktemp(suffix=".sqlite", prefix="goal1-dispatch-test-")
    verifier = Ed25519DispatchEvidenceVerifier(
        trusted_public_key=public, trusted_gateway_id="test-gateway",
        replay_db=db, expected_model_identity="synthetic-test-model",
        expected_model_artifact_sha256="a" * 64,
    )
    c = CausalTrialController(
        "GOAL1-LIVE-20261023-02", dispatch_evidence_verifier=verifier,
        expected_model_identity="synthetic-test-model",
        expected_model_artifact_sha256="a" * 64,
    )
    c._test_private_key = private
    return c


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def commit(c, arm, case, prediction="A", prompt=None, response="model response", budget=1, challenge_view_digest=None, dispatch_evidence=None):
    global _invocation_counter
    prompt_text = prompt if prompt is not None else f"QVR prompt for {arm}: {case}"
    prompt_hash = sha256(prompt_text)
    response_hash = sha256(response)
    challenge_hash = challenge_view_digest or digest(case)
    _invocation_counter += 1
    if budget != 1 or prediction not in ("A", "B", "ABSTAIN"):
        return c.commit_prediction(
            arm=arm, challenge_id=case["challenge_id"], prediction=prediction,
            challenge_view_digest=challenge_hash, model_prompt_sha256=prompt_hash,
            model_response_sha256=response_hash, budget_units=budget,
            dispatch_evidence=None,
        )
    if getattr(c, "_closed", False) or (arm, case["challenge_id"]) in c._predictions:
        return c.commit_prediction(
            arm=arm, challenge_id=case["challenge_id"], prediction=prediction,
            challenge_view_digest=challenge_hash, model_prompt_sha256=prompt_hash,
            model_response_sha256=response_hash, budget_units=budget,
            dispatch_evidence=None,
        )
    if dispatch_evidence is None:
        reservation_id = f"test-reservation-{uuid.uuid4().hex}"
        reservation = c.reserve_invocation(
            arm=arm, challenge_id=case["challenge_id"],
            challenge_view_digest=challenge_hash, model_prompt_sha256=prompt_hash,
        )
        evidence = {
            "witness_kind": "independent_dispatch_gateway",
            "gateway_id": "test-gateway",
            "attestation_id": f"test-attestation-{_invocation_counter}-{uuid.uuid4().hex}",
            "invocation_id": f"test-invocation-{_invocation_counter}-{uuid.uuid4().hex}",
            "reservation_id": reservation["reservation_id"],
            "run_id": reservation["run_id"],
            "arm": arm,
            "challenge_id": case["challenge_id"],
            "challenge_view_digest": challenge_hash,
            "model_prompt_sha256": prompt_hash,
            "model_response_sha256": response_hash,
            "model_identity": "synthetic-test-model",
            "model_artifact_sha256": "a" * 64,
            "dispatch_monotonic_ns": 100,
            "response_monotonic_ns": 200,
            "outcome_status": "COMPLETED",
            "resource_usage": {"input_tokens": 8, "output_tokens": 2, "wall_time_ms": 100},
        }
        evidence["signature"] = base64.b64encode(
            c._test_private_key.sign(canonical_attestation_bytes(evidence))
        ).decode()
    else:
        evidence = dispatch_evidence
    return c.commit_prediction(
        arm=arm, challenge_id=case["challenge_id"], prediction=prediction,
        challenge_view_digest=challenge_hash, model_prompt_sha256=prompt_hash,
        model_response_sha256=response_hash, budget_units=budget,
        dispatch_evidence=evidence,
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


def test_matching_hashes_without_independent_dispatch_evidence_rejected():
    c = CausalTrialController("no-witness")
    case = c.issue("train")[0]
    with pytest.raises(ValueError, match="independently verified dispatch evidence"):
        c.commit_prediction(arm="LEARNED", challenge_id=case["challenge_id"], prediction="A",
            challenge_view_digest=digest(case), model_prompt_sha256=sha256("p"),
            model_response_sha256=sha256("r"), budget_units=1)


def test_replayed_invocation_or_attestation_rejected():
    c = controller()
    first, second = c.issue("train")[:2]
    prompt = f"QVR prompt for LEARNED: {first}"
    evidence = {"witness_kind":"independent_dispatch_gateway", "attestation_id":"same-att",
        "invocation_id":"same-inv", "run_id":"test-run", "arm":"LEARNED",
        "challenge_id":first["challenge_id"], "challenge_view_digest":digest(first),
        "model_prompt_sha256":sha256(prompt), "model_response_sha256":sha256("model response"),
        "model_identity":"synthetic-test-model", "model_artifact_sha256":"a"*64,
        "dispatch_monotonic_ns":100, "response_monotonic_ns":200, "outcome_status":"COMPLETED"}
    with pytest.raises(ValueError, match="dispatch evidence fields missing"):
        commit(c, "LEARNED", first, prompt=prompt, dispatch_evidence=evidence)


@pytest.mark.parametrize("field,value,match", [
    ("challenge_id", "wrong-challenge", "binding mismatch"),
    ("dispatch_monotonic_ns", 300, "timestamp ordering"),
    ("model_identity", "fabricated-model", "model identity mismatch"),
    ("outcome_status", "OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN"),
])
def test_invalid_dispatch_evidence_rejected(field, value, match):
    c = controller()
    case = c.issue("train")[0]
    prompt = f"QVR prompt for LEARNED: {case}"
    evidence = {"witness_kind":"independent_dispatch_gateway", "attestation_id":f"att-{field}",
        "invocation_id":f"inv-{field}", "run_id":"test-run", "arm":"LEARNED",
        "challenge_id":case["challenge_id"], "challenge_view_digest":digest(case),
        "model_prompt_sha256":sha256(prompt), "model_response_sha256":sha256("model response"),
        "model_identity":"synthetic-test-model", "model_artifact_sha256":"a"*64,
        "dispatch_monotonic_ns":100, "response_monotonic_ns":200, "outcome_status":"COMPLETED"}
    evidence[field] = value
    with pytest.raises(ValueError, match="dispatch evidence fields missing"):
        commit(c, "LEARNED", case, prompt=prompt, dispatch_evidence=evidence)


def test_same_host_self_report_is_not_independent_dispatch_evidence():
    c = controller()
    case = c.issue("train")[0]
    evidence = {"witness_kind":"same_host_self_report", "attestation_id":"self-att",
        "invocation_id":"self-inv", "run_id":"test-run", "arm":"LEARNED",
        "challenge_id":case["challenge_id"], "challenge_view_digest":digest(case),
        "model_prompt_sha256":sha256("p"), "model_response_sha256":sha256("model response"),
        "model_identity":"synthetic-test-model", "model_artifact_sha256":"a"*64,
        "dispatch_monotonic_ns":100, "response_monotonic_ns":200, "outcome_status":"COMPLETED"}
    with pytest.raises(ValueError, match="dispatch evidence fields missing"):
        commit(c, "LEARNED", case, prompt="p", dispatch_evidence=evidence)


def test_synthetic_scores_and_nominal_budget_never_claim_measured_learning():
    c = controller()
    for arm in ARMS:
        for case in c.issue("holdout"):
            commit(c, arm, case, prediction="A")
    scores = c.score()
    assert all(row["budget_kind"] == "protocol_counter_not_measured_usage" for row in scores.values())
    assert all(row["resource_usage_measured"] is False for row in scores.values())
    assert all("learning_claim" not in row for row in scores.values())


def test_boolean_fake_verifier_cannot_be_injected_as_dispatch_authority():
    class FakeVerifier:
        def verify(self, evidence):
            return True

    with pytest.raises(TypeError, match="boolean verifier stubs are forbidden"):
        CausalTrialController("fake-verifier", dispatch_evidence_verifier=FakeVerifier())


def test_controller_issues_unique_pre_dispatch_reservation_bound_to_run_and_prompt():
    c = controller()
    case = c.issue("train")[0]
    prompt_hash = sha256("the exact candidate prompt")
    reservation = c.reserve_invocation(
        arm="LEARNED", challenge_id=case["challenge_id"],
        challenge_view_digest=digest(case), model_prompt_sha256=prompt_hash,
    )
    assert reservation["run_id"] == c.run_id
    assert reservation["arm"] == "LEARNED"
    assert reservation["challenge_id"] == case["challenge_id"]
    assert reservation["challenge_view_digest"] == digest(case)
    assert reservation["model_prompt_sha256"] == prompt_hash
    assert "answer" not in reservation and "label" not in reservation
    with pytest.raises(ValueError, match="duplicate attempt"):
        c.reserve_invocation(
            arm="LEARNED", challenge_id=case["challenge_id"],
            challenge_view_digest=digest(case), model_prompt_sha256=prompt_hash,
        )


def test_signed_receipt_cannot_substitute_another_run_after_reservation():
    c = controller()
    case = c.issue("train")[0]
    prompt = "exact candidate prompt"
    prompt_hash = sha256(prompt)
    response_hash = sha256("model response")
    reservation = c.reserve_invocation(
        arm="LEARNED", challenge_id=case["challenge_id"],
        challenge_view_digest=digest(case), model_prompt_sha256=prompt_hash,
    )
    fields = {
        "witness_kind": "independent_dispatch_gateway",
        "gateway_id": "test-gateway",
        "attestation_id": "wrong-run-attestation",
        "invocation_id": "wrong-run-invocation",
        "reservation_id": reservation["reservation_id"],
        "run_id": "substituted-run",
        "arm": "LEARNED",
        "challenge_id": case["challenge_id"],
        "challenge_view_digest": digest(case),
        "model_prompt_sha256": prompt_hash,
        "model_response_sha256": response_hash,
        "model_identity": "synthetic-test-model",
        "model_artifact_sha256": "a" * 64,
        "dispatch_monotonic_ns": 100,
        "response_monotonic_ns": 200,
        "outcome_status": "COMPLETED",
        "resource_usage": {"input_tokens": 8, "output_tokens": 2, "wall_time_ms": 100},
    }
    fields["signature"] = base64.b64encode(
        c._test_private_key.sign(canonical_attestation_bytes(fields))
    ).decode()
    with pytest.raises(ValueError, match="dispatch evidence binding mismatch"):
        c.commit_prediction(
            arm="LEARNED", challenge_id=case["challenge_id"], prediction="A",
            challenge_view_digest=digest(case), model_prompt_sha256=prompt_hash,
            model_response_sha256=response_hash, budget_units=1, dispatch_evidence=fields,
        )
