"""Runtime-bound promotion for NOVEL_MAPPING research evidence.

Measurement alone tops out at PARTIAL. Promotion to PASS requires Vera Mono's
existing live-current independent-review machinery to bind both the exact
held-out cut and the exact qualification artifact.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .agi_novel_mapping import NovelMappingQualificationResult

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


_TARGET_DIMENSIONS = (
    "NOVEL_TASK_TRANSFER",
    "LEARNING_EFFICIENCY",
)


@dataclass(frozen=True, slots=True)
class NovelMappingPromotionAssessment:
    promoted: bool
    packet: dict[str, object]
    reason: str
    independent_review_receipt_digest: str | None = None


class QualifiedNovelMappingPromotionAdapter:
    """Promote measured evidence only through live independent review."""

    def __init__(self, *, runtime: "QualifiedVeraRuntime") -> None:
        self.runtime = runtime

    @staticmethod
    def _answer(
        measurement: NovelMappingQualificationResult,
        *,
        promoted: bool,
        reason: str,
        receipt_digest: str | None = None,
    ) -> NovelMappingPromotionAssessment:
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
            }
        return NovelMappingPromotionAssessment(
            promoted=promoted,
            packet=packet,
            reason=reason,
            independent_review_receipt_digest=receipt_digest,
        )

    def promote(
        self,
        measurement: NovelMappingQualificationResult,
        *,
        task_id: str,
        consumer_id: str,
        probe_id: str,
        review_id: str,
    ) -> NovelMappingPromotionAssessment:
        if type(measurement) is not NovelMappingQualificationResult:
            raise TypeError(
                "measurement must be exact NovelMappingQualificationResult"
            )

        packet = measurement.packet
        probe = packet.get("probe")
        states = packet.get("dimension_states")
        if not isinstance(probe, dict) or not isinstance(states, dict):
            raise ValueError("measurement packet is structurally incomplete")
        if probe.get("family") != "NOVEL_MAPPING":
            raise ValueError("promotion requires NOVEL_MAPPING evidence")
        if probe.get("probe_id") != probe_id:
            return self._answer(
                measurement,
                promoted=False,
                reason="review probe does not match measurement probe",
            )

        target_states = {
            dimension: states.get(dimension)
            for dimension in _TARGET_DIMENSIONS
        }
        if any(state == "FAIL" for state in target_states.values()):
            return self._answer(
                measurement,
                promoted=False,
                reason="failed measurement state cannot be rescued by review",
            )
        if any(state != "PARTIAL" for state in target_states.values()):
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "promotion requires both target dimensions to be "
                    "measurement state PARTIAL"
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
                "cut and qualification artifact"
            ),
            receipt_digest=receipt.receipt_digest,
        )
