"""Runtime-bound promotion for CORRECTION_TRANSFER evidence.

Measurement alone tops out at PARTIAL. Promotion to PASS requires a
live-current independent review binding the exact held-out cut and exact
qualification artifact. The promotion preserves the explicit ceiling that the
failure-signature classifier was not learned by the subject.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

from .agi_correction_transfer_qualification import (
    CorrectionTransferQualificationResult,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


_TARGET_DIMENSIONS = (
    "RETENTION_AND_INTERFERENCE",
    "ROBUSTNESS_AND_ANTI_GAMING",
)


@dataclass(frozen=True, slots=True)
class CorrectionTransferPromotionAssessment:
    promoted: bool
    packet: dict[str, object]
    reason: str
    independent_review_receipt_digest: str | None = None


class QualifiedCorrectionTransferPromotionAdapter:
    """Promote measured correction transfer only through live review."""

    def __init__(self, *, runtime: "QualifiedVeraRuntime") -> None:
        self.runtime = runtime

    @staticmethod
    def _answer(
        measurement: CorrectionTransferQualificationResult,
        *,
        promoted: bool,
        reason: str,
        receipt_digest: str | None = None,
    ) -> CorrectionTransferPromotionAssessment:
        packet = deepcopy(measurement.packet)
        if promoted:
            states = dict(packet["dimension_states"])
            for dimension in _TARGET_DIMENSIONS:
                states[dimension] = "PASS"
            packet["dimension_states"] = states
            packet["independent_review"] = {
                "status": "PASS",
                "receipt_digest": receipt_digest,
                "live_current": True,
                "qualification_artifact_digest": (
                    measurement.qualification_artifact_digest
                ),
                "signature_classifier_learned_by_subject": False,
            }
        return CorrectionTransferPromotionAssessment(
            promoted=promoted,
            packet=packet,
            reason=reason,
            independent_review_receipt_digest=receipt_digest,
        )

    def promote(
        self,
        measurement: CorrectionTransferQualificationResult,
        *,
        task_id: str,
        consumer_id: str,
        probe_id: str,
        review_id: str,
    ) -> CorrectionTransferPromotionAssessment:
        if type(measurement) is not CorrectionTransferQualificationResult:
            raise TypeError(
                "measurement must be exact "
                "CorrectionTransferQualificationResult"
            )

        packet = measurement.packet
        probe = packet.get("probe")
        states = packet.get("dimension_states")
        if not isinstance(probe, dict) or not isinstance(states, dict):
            raise ValueError("measurement packet is structurally incomplete")
        if probe.get("family") != "CORRECTION_TRANSFER":
            raise ValueError(
                "promotion requires CORRECTION_TRANSFER evidence"
            )
        if probe.get("probe_id") != probe_id:
            return self._answer(
                measurement,
                promoted=False,
                reason="review probe does not match measurement probe",
            )

        if any(states.get(dimension) != "PARTIAL" for dimension in _TARGET_DIMENSIONS):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "promotion requires both correction-transfer measurement "
                    "states to be PARTIAL"
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
            type(artifact) is not dict
            or artifact.get("signature_classifier_learned_by_subject")
            is not False
        ):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "qualification artifact must preserve the explicit "
                    "signature-classifier learning ceiling"
                ),
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

        items_digest = probe.get("items_digest")
        if requirement.get("held_out_probe_set_digest") != items_digest:
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
                    "independent review binds a different qualification "
                    "artifact"
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
                "correction-transfer cut and qualification artifact; "
                "signature-classifier learning remains outside the claim"
            ),
            receipt_digest=receipt.receipt_digest,
        )
