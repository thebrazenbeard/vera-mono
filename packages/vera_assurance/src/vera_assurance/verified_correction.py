"""Evidence-bound, non-authoritative shadow correction assessment.

Reuses vera_assurance.evaluation_commitment's immutable pre-outcome
prediction snapshots and comparison conditions. It evaluates *supplied*
outcome labels and evidence references, NOT their external authenticity.
It never executes a model, changes memory, promotes learned influence, or
grants permission to use a correction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .evaluation_commitment import (
    CommittedComparison,
    PredictionCommitment,
    compare_committed_predictions,
)


class EvidenceSplit(StrEnum):
    CALIBRATION = "CALIBRATION"
    QUALIFICATION = "QUALIFICATION"


class CorrectionEvidenceState(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PROVISIONAL_REVIEW_ONLY = "PROVISIONAL_REVIEW_ONLY"
    NO_MEASURED_GAIN = "NO_MEASURED_GAIN"
    NEGATIVE_TRANSFER = "NEGATIVE_TRANSFER"


@dataclass(frozen=True, slots=True)
class PairedOutcome:
    comparison: CommittedComparison
    learner: PredictionCommitment
    frozen: PredictionCommitment
    case_id: str
    expected_label: str
    evaluator_ref: str
    split: EvidenceSplit


@dataclass(frozen=True, slots=True)
class CorrectionEvidenceAssessment:
    correction_id: str
    state: CorrectionEvidenceState
    calibration_cases: int
    qualification_cases: int
    learner_correct: int
    frozen_correct: int
    negative_transfer_cases: int
    eligible_for_review: bool
    authorization_effect: str = "NONE"


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError(f"{name} must be a bounded non-empty exact string")
    return value


def _prediction_label(ticket: PredictionCommitment, case_id: str) -> str:
    prediction = ticket.prediction
    if set(prediction) != {"case_id", "label"}:
        raise ValueError("prediction must bind exact case_id and label only")
    if prediction["case_id"] != case_id:
        raise ValueError("prediction case_id does not match evaluator case")
    return _text(prediction["label"], "prediction label")


def assess_correction_evidence(
    *,
    correction_id: str,
    observations: tuple[PairedOutcome, ...],
    minimum_qualification_cases: int = 2,
) -> CorrectionEvidenceAssessment:
    """Assess one correction against frozen-control predictions for new cases.

    Must be called with observations issued BEFORE feedback; hashes confirm
    internal integrity only, not clock ordering or evaluator independence.
    A positive result licenses human/independent review of the experiment,
    never installation, memory admission or learned influence.
    """
    _text(correction_id, "correction_id")
    if type(observations) is not tuple:
        raise TypeError("observations must be an exact tuple")
    if type(minimum_qualification_cases) is not int or minimum_qualification_cases < 1:
        raise ValueError("minimum_qualification_cases must be a positive exact integer")

    cases: set[str] = set()
    refs: set[str] = set()
    steps: set[int] = set()
    opportunities: set[str] = set()
    consistent_candidates: tuple[str, str] | None = None
    consistent_resources: tuple[str, str] | None = None
    calibration_count = 0
    qualification_count = 0
    calibration_wins = 0
    learner_correct = 0
    frozen_correct = 0
    negative_transfer = 0

    for row in observations:
        if type(row) is not PairedOutcome:
            raise TypeError("observations must contain exact PairedOutcome values")
        if (type(row.comparison) is not CommittedComparison
                or type(row.learner) is not PredictionCommitment
                or type(row.frozen) is not PredictionCommitment
                or type(row.split) is not EvidenceSplit):
            raise TypeError("observation has incorrect prediction, comparison, or split type")

        case_id = _text(row.case_id, "case_id")
        truth = _text(row.expected_label, "expected label")
        evaluator_ref = _text(row.evaluator_ref, "evaluator reference")
        if case_id in cases:
            raise ValueError("duplicate case across calibration/qualification")
        if evaluator_ref in refs:
            raise ValueError("duplicate evaluator reference")
        if row.learner.step in steps:
            raise ValueError("duplicate prediction step across cases")
        opportunity = row.comparison.conditions.opportunity_condition_id
        if opportunity in opportunities:
            raise ValueError("duplicate opportunity across cases")
        cases.add(case_id)
        refs.add(evaluator_ref)
        steps.add(row.learner.step)
        opportunities.add(opportunity)

        verified = compare_committed_predictions(
            row.learner, row.frozen, conditions=row.comparison.conditions,
        )
        if verified != row.comparison:
            raise ValueError("comparison differs from bound pre-outcome tickets")
        names = (row.learner.candidate_id, row.frozen.candidate_id)
        if consistent_candidates is None:
            consistent_candidates = names
        elif names != consistent_candidates:
            raise ValueError("candidate identity changed during evaluation")
        resources = (row.comparison.conditions.resource_condition_id,
                     row.comparison.conditions.representation_version)
        if consistent_resources is None:
            consistent_resources = resources
        elif resources != consistent_resources:
            raise ValueError("resource/representation conditions changed across cases")

        learned = _prediction_label(row.learner, case_id) == truth
        frozen = _prediction_label(row.frozen, case_id) == truth
        if row.split is EvidenceSplit.CALIBRATION:
            calibration_count += 1
            calibration_wins += learned and not frozen
        else:
            qualification_count += 1
            learner_correct += learned
            frozen_correct += frozen
            negative_transfer += frozen and not learned

    if calibration_count == 0 or qualification_count < minimum_qualification_cases:
        state = CorrectionEvidenceState.INSUFFICIENT_EVIDENCE
    elif negative_transfer:
        state = CorrectionEvidenceState.NEGATIVE_TRANSFER
    elif calibration_wins > 0 and learner_correct > frozen_correct:
        state = CorrectionEvidenceState.PROVISIONAL_REVIEW_ONLY
    else:
        state = CorrectionEvidenceState.NO_MEASURED_GAIN

    return CorrectionEvidenceAssessment(
        correction_id=correction_id,
        state=state,
        calibration_cases=calibration_count,
        qualification_cases=qualification_count,
        learner_correct=learner_correct,
        frozen_correct=frozen_correct,
        negative_transfer_cases=negative_transfer,
        eligible_for_review=(state is CorrectionEvidenceState.PROVISIONAL_REVIEW_ONLY),
    )
