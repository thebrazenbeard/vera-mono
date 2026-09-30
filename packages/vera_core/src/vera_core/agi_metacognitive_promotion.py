"""Runtime-bound promotion for metacognitive calibration evidence.

Measurement alone tops out at PARTIAL. Promotion to PASS requires Vera Mono's
live-current independent-review machinery to bind the exact held-out cut and
the exact metacognitive qualification artifact.

This adapter promotes only METACOGNITIVE_CALIBRATION. Sharing the
AMBIGUOUS_SPEC family does not grant ROBUSTNESS_AND_ANTI_GAMING or
LONG_HORIZON_AGENCY.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

from .agi_metacognitive_qualification import (
    MetacognitiveCalibrationQualificationResult,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


_TARGET_DIMENSION = "METACOGNITIVE_CALIBRATION"


@dataclass(frozen=True, slots=True)
class MetacognitiveCalibrationPromotionAssessment:
    promoted: bool
    packet: dict[str, object]
    reason: str
    independent_review_receipt_digest: str | None = None


class QualifiedMetacognitiveCalibrationPromotionAdapter:
    """Promote metacognitive evidence only through live independent review."""

    def __init__(self, *, runtime: "QualifiedVeraRuntime") -> None:
        self.runtime = runtime

    @staticmethod
    def _answer(
        measurement: MetacognitiveCalibrationQualificationResult,
        *,
        promoted: bool,
        reason: str,
        receipt_digest: str | None = None,
    ) -> MetacognitiveCalibrationPromotionAssessment:
        packet = deepcopy(measurement.packet)
        if promoted:
            states = dict(packet["dimension_states"])
            states[_TARGET_DIMENSION] = "PASS"
            packet["dimension_states"] = states
            packet["independent_review"] = {
                "status": "PASS",
                "receipt_digest": receipt_digest,
                "live_current": True,
                "qualification_artifact_digest": (
                    measurement.qualification_artifact_digest
                ),
                "dimension_scope": [_TARGET_DIMENSION],
            }
        return MetacognitiveCalibrationPromotionAssessment(
            promoted=promoted,
            packet=packet,
            reason=reason,
            independent_review_receipt_digest=receipt_digest,
        )

    def promote(
        self,
        measurement: MetacognitiveCalibrationQualificationResult,
        *,
        task_id: str,
        consumer_id: str,
        probe_id: str,
        review_id: str,
    ) -> MetacognitiveCalibrationPromotionAssessment:
        if type(measurement) is not MetacognitiveCalibrationQualificationResult:
            raise TypeError(
                "measurement must be exact "
                "MetacognitiveCalibrationQualificationResult"
            )

        packet = measurement.packet
        probe = packet.get("probe")
        states = packet.get("dimension_states")
        if not isinstance(probe, dict) or not isinstance(states, dict):
            raise ValueError("measurement packet is structurally incomplete")
        if probe.get("family") != "AMBIGUOUS_SPEC":
            raise ValueError(
                "metacognitive promotion requires AMBIGUOUS_SPEC family evidence"
            )
        if probe.get("probe_id") != probe_id:
            return self._answer(
                measurement,
                promoted=False,
                reason="review probe does not match measurement probe",
            )
        if set(states) != {_TARGET_DIMENSION}:
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "metacognitive measurement must contain only "
                    "METACOGNITIVE_CALIBRATION state"
                ),
            )

        state = states.get(_TARGET_DIMENSION)
        if state == "FAIL":
            return self._answer(
                measurement,
                promoted=False,
                reason="failed measurement state cannot be rescued by review",
            )
        if state != "PARTIAL":
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "promotion requires METACOGNITIVE_CALIBRATION "
                    "measurement state PARTIAL"
                ),
            )

        try:
            artifact = json.loads(measurement.qualification_artifact_json)
        except json.JSONDecodeError:
            return self._answer(
                measurement,
                promoted=False,
                reason="qualification artifact is not valid JSON",
            )
        if (
            not isinstance(artifact, dict)
            or artifact.get("schema")
            != "VERA_AGI_METACOGNITIVE_CALIBRATION_QUALIFICATION_V1"
            or artifact.get("measurement_only") is not True
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason="qualification artifact is not the governed measurement",
            )

        assessment = self.runtime.assess_independent_behavior_review(
            task_id,
            consumer_id,
            probe_id,
            review_id,
        )
        if (
            assessment.passed is not True
            or assessment.latest_status != "PASS"
            or assessment.current_verdict != "PASS"
            or assessment.current_authority_current is not True
            or assessment.current_operationally_separate is not True
            or assessment.current_signatures_valid is not True
            or assessment.current_matches_receipt is not True
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "independent review is not live-current PASS with "
                    "current signatures and exact receipt match"
                ),
            )

        try:
            receipt = self.runtime.independent_behavior_reviews.latest(
                task_id,
                consumer_id,
                probe_id,
                review_id,
            )
        except KeyError:
            return self._answer(
                measurement,
                promoted=False,
                reason="current independent review receipt is missing",
            )

        if (
            assessment.latest_receipt_digest != receipt.receipt_digest
            or receipt.status != "PASS"
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "live assessment does not bind the current review receipt"
                ),
            )

        requirement = receipt.payload.get("requirement")
        observation = receipt.payload.get("observation")
        if not isinstance(requirement, dict) or not isinstance(
            observation, dict
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason="independent review receipt payload is incomplete",
            )

        if (
            requirement.get("held_out_probe_set_digest")
            != probe.get("items_digest")
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "independent review binds a different held-out probe set"
                ),
            )

        if (
            observation.get("result_digest")
            != measurement.qualification_artifact_digest
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "independent review binds a different qualification artifact"
                ),
            )

        if observation.get("verdict") != "PASS":
            return self._answer(
                measurement,
                promoted=False,
                reason="independent review observation verdict is not PASS",
            )

        return self._answer(
            measurement,
            promoted=True,
            reason=(
                "live-current independent review binds the exact held-out "
                "cut and metacognitive qualification artifact"
            ),
            receipt_digest=receipt.receipt_digest,
        )
