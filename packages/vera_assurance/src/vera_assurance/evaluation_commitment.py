"""Pre-outcome evaluation commitments and condition-bound comparison.

Adapted from Noema's prediction boundary/comparator. This preserves what a
candidate committed to before outcome evaluation and the conditions under which
two candidates are compared. It does not score outcomes or grant authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("prediction must be canonical JSON-compatible data") from exc
    return text.encode("utf-8")


@dataclass(frozen=True, slots=True)
class PredictionCommitment:
    candidate_id: str
    step: int
    commitment: str

    def __post_init__(self) -> None:
        if type(self.candidate_id) is not str or not self.candidate_id:
            raise ValueError("candidate_id must be a non-empty exact string")
        if type(self.step) is not int or self.step < 0:
            raise ValueError("step must be a non-negative exact integer")
        if (
            type(self.commitment) is not str
            or len(self.commitment) != 64
            or any(ch not in "0123456789abcdef" for ch in self.commitment)
        ):
            raise ValueError("commitment must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class ComparisonConditions:
    information_condition_id: str
    opportunity_condition_id: str
    resource_condition_id: str
    representation_version: str

    def __post_init__(self) -> None:
        for label, value in (
            ("information_condition_id", self.information_condition_id),
            ("opportunity_condition_id", self.opportunity_condition_id),
            ("resource_condition_id", self.resource_condition_id),
            ("representation_version", self.representation_version),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")


@dataclass(frozen=True, slots=True)
class CommittedComparison:
    left_candidate_id: str
    right_candidate_id: str
    step: int
    left_commitment: str
    right_commitment: str
    conditions: ComparisonConditions
    authorization_effect: str = "NONE"


def commit_prediction(
    *,
    candidate_id: str,
    step: int,
    prediction: Mapping[str, object],
) -> PredictionCommitment:
    if type(candidate_id) is not str or not candidate_id:
        raise ValueError("candidate_id must be a non-empty exact string")
    if type(step) is not int or step < 0:
        raise ValueError("step must be a non-negative exact integer")
    if not isinstance(prediction, Mapping):
        raise TypeError("prediction must be a mapping")

    payload = {
        "schema": "VERA_PREOUTCOME_PREDICTION_COMMITMENT_V1",
        "candidate_id": candidate_id,
        "step": step,
        "prediction": dict(prediction),
    }
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    return PredictionCommitment(
        candidate_id=candidate_id,
        step=step,
        commitment=digest,
    )


def compare_committed_predictions(
    left: PredictionCommitment,
    right: PredictionCommitment,
    *,
    conditions: ComparisonConditions,
) -> CommittedComparison:
    if type(left) is not PredictionCommitment or type(right) is not PredictionCommitment:
        raise TypeError(
            "left and right must be exact PredictionCommitment values"
        )
    if type(conditions) is not ComparisonConditions:
        raise TypeError("conditions must be exact ComparisonConditions")
    if left.step != right.step:
        raise ValueError("comparison requires commitments from the same step")
    if left.candidate_id == right.candidate_id:
        raise ValueError("comparison requires distinct candidate IDs")

    return CommittedComparison(
        left_candidate_id=left.candidate_id,
        right_candidate_id=right.candidate_id,
        step=left.step,
        left_commitment=left.commitment,
        right_commitment=right.commitment,
        conditions=conditions,
    )
