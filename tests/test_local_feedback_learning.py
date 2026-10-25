"""Synthetic-only probes for the opt-in local retrieval adaptation gate."""

from dataclasses import replace

import pytest

from vera_memory.local_feedback_learning import (
    FeedbackSample,
    HeldoutCase,
    LocalFeedbackLearner,
    LearningBlocked,
)


def sample(*, cue="color of a ripe banana", answer="yellow", source="training-source"):
    return FeedbackSample(
        sample_id="feedback-1",
        source_id=source,
        cue=cue,
        answer=answer,
        consent_ref="owner-opt-in:synthetic-1",
        privacy_review_ref="local-redaction-review:synthetic-1",
        provenance_ref="synthetic-fixture:training-1",
    )


def holdout(*, expected="yellow", cue="color of a ripe banana", source="heldout-source"):
    return HeldoutCase(
        case_id="holdout-1",
        source_id=source,
        cue=cue,
        expected=expected,
    )


def test_review_gated_learning_and_rollback():
    learner = LocalFeedbackLearner()
    genesis = learner.active_revision
    candidate = learner.stage((sample(),))
    assert learner.lookup("color of a ripe banana") is None

    evidence = learner.evaluate(candidate, (holdout(),))
    assert evidence.qualified is True
    assert (evidence.baseline_passes, evidence.candidate_passes) == (0, 1)
    assert evidence.regressions == ()
    learner.approve(evidence, approval_ref="operator-review:synthetic-1")
    assert learner.lookup("color of a ripe banana") == "yellow"
    assert learner.active_revision != genesis

    learner.rollback(genesis, approval_ref="operator-review:rollback-1")
    assert learner.lookup("color of a ripe banana") is None


def test_no_private_feedback_without_consent_privacy_and_provenance_refs():
    for field in ("consent_ref", "privacy_review_ref", "provenance_ref"):
        learner = LocalFeedbackLearner()
        with pytest.raises((ValueError, LearningBlocked)):
            learner.stage((replace(sample(), **{field: ""}),))
        assert learner.lookup("color of a ripe banana") is None


def test_holdout_must_be_disjoint_from_training_source_and_identity():
    learner = LocalFeedbackLearner()
    candidate = learner.stage((sample(),))
    with pytest.raises(LearningBlocked):
        learner.evaluate(candidate, (holdout(source="training-source"),))
    with pytest.raises(LearningBlocked):
        learner.evaluate(candidate, (replace(holdout(), case_id="feedback-1"),))


def test_repeated_holdout_source_or_content_does_not_inflate_independent_cases():
    learner = LocalFeedbackLearner()
    candidate = learner.stage((sample(),))
    repeated_source = tuple(replace(holdout(), case_id=f"repeated-{index}") for index in range(128))
    with pytest.raises(LearningBlocked):
        learner.evaluate(candidate, repeated_source)
    repeated_content = (
        holdout(),
        replace(holdout(), case_id="holdout-2", source_id="heldout-source-2"),
    )
    with pytest.raises(LearningBlocked):
        learner.evaluate(candidate, repeated_content)
    contradictory_content = (
        holdout(expected="yellow"),
        replace(holdout(), case_id="holdout-opposite", source_id="opposite-source", expected="orange"),
    )
    with pytest.raises(LearningBlocked):
        learner.evaluate(candidate, contradictory_content)


def test_previous_approved_holdout_canaries_are_immutable_regression_gates():
    learner = LocalFeedbackLearner()
    first = learner.stage((sample(),))
    learner.approve(learner.evaluate(first, (holdout(),)), approval_ref="review:known")
    known_revision = learner.active_revision

    changed = learner.stage((
        replace(sample(), sample_id="feedback-wrong", answer="orange"),
        replace(sample(), sample_id="feedback-new", cue="new cue", answer="new answer"),
    ))
    only_new_case = HeldoutCase(
        case_id="new-heldout", source_id="new-source", cue="new cue", expected="new answer",
    )
    evidence = learner.evaluate(changed, (only_new_case,))
    assert evidence.heldout_cases == 2  # includes retained, approved canary
    assert evidence.regressions == ("holdout-1",)
    assert not evidence.qualified
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:new-only")
    assert learner.active_revision == known_revision
    assert learner.lookup("color of a ripe banana") == "yellow"


def test_partial_pass_never_approves_a_failing_case_as_permanent_canary():
    learner = LocalFeedbackLearner()
    candidate = learner.stage((sample(),))
    suite = (
        holdout(),
        HeldoutCase(case_id="other-case", source_id="other-source", cue="another cue", expected="missing"),
    )
    evidence = learner.evaluate(candidate, suite)
    assert evidence.candidate_passes == 1 and evidence.heldout_cases == 2
    assert not evidence.qualified
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:incomplete-suite")
    assert learner.lookup("color of a ripe banana") is None


def test_rollback_does_not_erase_historical_approved_canaries():
    learner = LocalFeedbackLearner()
    genesis = learner.active_revision
    first = learner.stage((sample(),))
    learner.approve(learner.evaluate(first, (holdout(),)), approval_ref="review:first")
    second = learner.stage((replace(
        sample(), sample_id="feedback-new", cue="new cue", answer="new answer",
    ),))
    extra = HeldoutCase(
        case_id="extra-holdout", source_id="extra-source", cue="new cue", expected="new answer",
    )
    second_evidence = learner.evaluate(second, (extra,))
    assert second_evidence.heldout_cases == 2 and second_evidence.qualified
    learner.approve(second_evidence, approval_ref="review:second")

    learner.rollback(genesis, approval_ref="review:rollback")
    regressive = learner.stage((sample(),))
    evidence = learner.evaluate(regressive, ())
    assert evidence.candidate_passes == 1 and evidence.baseline_passes == 0
    assert evidence.regressions == ("extra-holdout",)
    assert not evidence.qualified
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:incomplete")


def test_failed_holdout_never_activates_and_cannot_be_approved():
    learner = LocalFeedbackLearner()
    candidate = learner.stage((sample(answer="orange"),))
    evaluation = learner.evaluate(candidate, (holdout(),))
    assert not evaluation.qualified
    with pytest.raises(LearningBlocked):
        learner.approve(evaluation, approval_ref="operator-review:synthetic-2")
    assert learner.lookup("color of a ripe banana") is None


def test_regression_against_approved_revision_fails_closed():
    learner = LocalFeedbackLearner()
    first = learner.stage((sample(),))
    learner.approve(
        learner.evaluate(first, (holdout(),)),
        approval_ref="operator-review:synthetic-1",
    )
    active = learner.active_revision
    second = learner.stage((replace(sample(), sample_id="feedback-2", answer="orange"),))
    evidence = learner.evaluate(second, ())  # approved canary is retained automatically
    assert evidence.regressions == ("holdout-1",)
    assert not evidence.qualified
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="operator-review:synthetic-2")
    assert learner.active_revision == active
    assert learner.lookup("color of a ripe banana") == "yellow"


def test_stale_or_forged_evaluation_does_not_activate():
    learner = LocalFeedbackLearner()
    first = learner.stage((sample(),))
    evidence = learner.evaluate(first, (holdout(),))
    with pytest.raises(LearningBlocked):
        learner.approve(replace(evidence, candidate_passes=999), approval_ref="review:forged")

    learner.stage((replace(sample(), sample_id="feedback-2", cue="new cue"),))
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:stale")


def test_invalid_second_evaluation_revokes_previous_qualification():
    learner = LocalFeedbackLearner()
    candidate = learner.stage((sample(),))
    evidence = learner.evaluate(candidate, (holdout(),))
    with pytest.raises(LearningBlocked):
        learner.evaluate(candidate, (holdout(source="training-source"),))
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:old-suite")


def test_failed_restaging_revokes_earlier_qualification():
    learner = LocalFeedbackLearner()
    candidate = learner.stage((sample(),))
    evidence = learner.evaluate(candidate, (holdout(),))
    with pytest.raises(LearningBlocked):
        learner.stage(())
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:old-stage")


def test_duplicate_conflicting_cues_rejected():
    learner = LocalFeedbackLearner()
    with pytest.raises(LearningBlocked):
        learner.stage((sample(), replace(sample(), sample_id="feedback-2", answer="orange")))


def test_sample_id_rebind_across_approved_cues_rejected():
    learner = LocalFeedbackLearner()
    first = learner.stage((sample(),))
    learner.approve(learner.evaluate(first, (holdout(),)), approval_ref="review:first")
    with pytest.raises(LearningBlocked):
        learner.stage((replace(sample(), cue="new cue"),))


def test_rollback_requires_exact_reviewed_revision():
    learner = LocalFeedbackLearner()
    with pytest.raises(LearningBlocked):
        learner.rollback("unknown", approval_ref="review:rollback")
    with pytest.raises(ValueError):
        learner.rollback(learner.active_revision, approval_ref="")


def test_review_reference_cannot_be_replayed_across_versions_or_rollback():
    learner = LocalFeedbackLearner()
    genesis = learner.active_revision
    first = learner.stage((sample(),))
    learner.approve(learner.evaluate(first, (holdout(),)), approval_ref="review:once")
    before = learner.active_revision
    second = learner.stage((replace(sample(), sample_id="feedback-2", cue="new cue", answer="new answer"),))
    evidence = learner.evaluate(second, (HeldoutCase(
        case_id="case-new", source_id="heldout-new", cue="new cue", expected="new answer",
    ),))
    with pytest.raises(LearningBlocked):
        learner.approve(evidence, approval_ref="review:once")
    assert learner.active_revision == before
    with pytest.raises(LearningBlocked):
        learner.rollback(genesis, approval_ref="review:once")
