"""Behavioral negatives for non-authoritative verified-correction evidence."""
from dataclasses import replace
import pytest

from vera_assurance.evaluation_commitment import (
    ComparisonConditions, commit_prediction, compare_committed_predictions,
)
from vera_assurance.verified_correction import (
    EvidenceSplit, PairedOutcome, CorrectionEvidenceState,
    assess_correction_evidence,
)


def pair(case_id, step, split, *, truth="B", learner="B", frozen="A",
         evaluator_ref=None, resource="equal-resource"):
    left = commit_prediction(
        candidate_id="correction-v1", step=step,
        prediction={"case_id": case_id, "label": learner},
    )
    right = commit_prediction(
        candidate_id="frozen-v1", step=step,
        prediction={"case_id": case_id, "label": frozen},
    )
    conditions = ComparisonConditions(
        information_condition_id="info-" + case_id,
        opportunity_condition_id="opp-" + case_id,
        resource_condition_id=resource,
        representation_version="binary-v1",
    )
    return PairedOutcome(
        comparison=compare_committed_predictions(left, right, conditions=conditions),
        issued_conditions=conditions,
        learner=left, frozen=right, case_id=case_id, expected_label=truth,
        evaluator_ref=evaluator_ref or ("eval-" + case_id),
        split=split,
    )


def assess(*rows, **kwargs):
    return assess_correction_evidence(
        correction_id="corr-synthetic-1", observations=tuple(rows), **kwargs,
    )


def calibration():
    return pair("cal-1", 0, EvidenceSplit.CALIBRATION)


def qualification(n, **kwargs):
    return pair("heldout-" + str(n), n, EvidenceSplit.QUALIFICATION, **kwargs)


def test_heldout_gain_is_only_provisional_not_automatic_lesson_or_authority():
    report = assess(calibration(), qualification(1), qualification(2), qualification(3))
    assert report.state is CorrectionEvidenceState.PROVISIONAL_REVIEW_ONLY
    assert report.calibration_cases == 1
    assert report.qualification_cases == 3
    assert report.learner_correct == 3
    assert report.frozen_correct == 0
    assert report.negative_transfer_cases == 0
    assert report.eligible_for_review is True
    assert report.authorization_effect == "NONE"
    assert "ADMITTED" not in str(report)


def test_without_calibration_or_fresh_qualification_there_is_no_learning_evidence():
    assert assess(qualification(1), qualification(2)).state is CorrectionEvidenceState.INSUFFICIENT_EVIDENCE
    assert assess(calibration()).state is CorrectionEvidenceState.INSUFFICIENT_EVIDENCE
    assert assess(calibration(), qualification(1)).state is CorrectionEvidenceState.INSUFFICIENT_EVIDENCE


def test_no_gain_does_not_suggest_retention():
    report = assess(calibration(), qualification(1, learner="A", frozen="A", truth="A"),
                    qualification(2, learner="B", frozen="B", truth="B"))
    assert report.state is CorrectionEvidenceState.NO_MEASURED_GAIN
    assert report.eligible_for_review is False


def test_negative_transfer_preempts_apparent_aggregate_gain():
    report = assess(
        calibration(),
        qualification(1), qualification(2),
        qualification(3, learner="B", frozen="A", truth="A"),
    )
    assert report.learner_correct == 2 and report.frozen_correct == 1
    assert report.negative_transfer_cases == 1
    assert report.state is CorrectionEvidenceState.NEGATIVE_TRANSFER
    assert report.eligible_for_review is False


def test_tampered_prediction_commitment_is_rejected():
    row = qualification(1)
    forged = replace(row.learner, commitment="0" * 64)
    with pytest.raises(ValueError, match="commitment|comparison"):
        assess(calibration(), replace(row, learner=forged), qualification(2))


def test_wrong_comparison_conditions_or_swapped_tickets_are_rejected():
    row = qualification(1)
    with pytest.raises(ValueError, match="comparison"):
        assess(calibration(), replace(row, learner=row.frozen), qualification(2))
    other = compare_committed_predictions(
        row.learner, row.frozen,
        conditions=ComparisonConditions("other-info", "other-opp", "equal-resource", "binary-v1"),
    )
    with pytest.raises(ValueError, match="comparison"):
        assess(calibration(), replace(row, comparison=other), qualification(2))


def test_substituted_issued_conditions_are_rejected():
    row = qualification(1)
    forged_conditions = ComparisonConditions(
        information_condition_id="wrong-information",
        opportunity_condition_id="wrong-opportunity",
        resource_condition_id="equal-resource",
        representation_version="binary-v1",
    )
    with pytest.raises(ValueError, match="comparison conditions"):
        assess(calibration(), replace(row, issued_conditions=forged_conditions), qualification(2))


def test_issued_conditions_must_be_exact_type():
    row = qualification(1)
    with pytest.raises(TypeError, match="split type"):
        assess(calibration(), replace(row, issued_conditions="not-issued-conditions"), qualification(2))


def test_duplicate_task_in_calibration_and_qualification_rejected():
    row = calibration()
    with pytest.raises(ValueError, match="duplicate|overlap|case"):
        assess(row, replace(row, split=EvidenceSplit.QUALIFICATION), qualification(2))


def test_duplicate_evaluator_receipt_id_rejected():
    with pytest.raises(ValueError, match="evaluator|duplicate"):
        assess(calibration(), qualification(1), qualification(2, evaluator_ref="eval-heldout-1"))


def test_hidden_case_id_mismatch_with_committed_prediction_rejected():
    with pytest.raises(ValueError, match="case"):
        assess(calibration(), replace(qualification(1), case_id="another-case"), qualification(2))


def test_malformed_model_predictions_or_truth_types_fail_closed():
    row = qualification(1)
    empty_label = commit_prediction(candidate_id="correction-v1", step=1,
                                   prediction={"case_id": "heldout-1", "label": ""})
    with pytest.raises(ValueError, match="prediction|label|comparison"):
        assess(calibration(), replace(row, learner=empty_label), qualification(2))
    with pytest.raises(ValueError, match="label"):
        assess(calibration(), replace(row, expected_label=True), qualification(2))


def test_cross_case_resource_mismatch_must_not_fake_comparable_gain():
    with pytest.raises(ValueError, match="resource"):
        assess(calibration(), qualification(1, resource="extra-tokens"), qualification(2))


def test_same_trial_step_cannot_be_reused_as_fresh_evidence():
    with pytest.raises(ValueError, match="step|duplicate"):
        assess(calibration(), qualification(1), qualification(2).replace if False else
               pair("heldout-2", 1, EvidenceSplit.QUALIFICATION))


def test_missing_or_invalid_provenance_and_improper_evidence_types_fail_closed():
    with pytest.raises(ValueError, match="evaluator"):
        assess(calibration(), replace(qualification(1), evaluator_ref=""), qualification(2))
    with pytest.raises(TypeError):
        assess(calibration(), "not-an-observation", qualification(2))


def test_assessment_is_pure_and_invariant_under_safe_input_order():
    rows=(calibration(), qualification(1), qualification(2))
    first=assess(*rows)
    second=assess(rows[2], rows[0], rows[1])
    assert first == second
    assert first.eligible_for_review is True
