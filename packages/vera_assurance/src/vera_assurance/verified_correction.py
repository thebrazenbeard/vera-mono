"""Source-only correction scoring boundary. Not a learning authority."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from .evaluation_commitment import CommittedComparison, PredictionCommitment


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


def assess_correction_evidence(*, correction_id: str, observations: tuple[PairedOutcome, ...], minimum_qualification_cases: int = 2) -> CorrectionEvidenceAssessment:
    raise NotImplementedError("verified correction boundary not implemented")
