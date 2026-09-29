"""Runtime-bound promotion for compositional-transfer research evidence.

Measurement alone tops out at PARTIAL. Promotion to PASS requires Vera Mono's
live-current independent-review machinery to bind the exact held-out cut and
qualification artifact.

This single-domain frontier may promote NOVEL_TASK_TRANSFER only.
CROSS_DOMAIN_BREADTH remains capped at PARTIAL until genuinely multi-domain
evidence exists.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .agi_compositional_transfer import (
    CompositionalTransferQualificationResult,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


_PROMOTABLE_DIMENSION = "NOVEL_TASK_TRANSFER"
_BREADTH_DIMENSION = "CROSS_DOMAIN_BREADTH"


@dataclass(frozen=True, slots=True)
class CompositionalTransferPromotionAssessment:
    promoted: bool
    packet: dict[str, object]
    reason: str
    independent_review_receipt_digest: str | None = None


class QualifiedCompositionalTransferPromotionAdapter:
    """Promote measured transfer only through live independent review."""

    def __init__(self, *, runtime: "QualifiedVeraRuntime") -> None:
        self.runtime = runtime

    @staticmethod
    def _answer(
        measurement: CompositionalTransferQualificationResult,
        *,
        promoted: bool,
        reason: str,
        receipt_digest: str | None = None,
    ) -> CompositionalTransferPromotionAssessment:
        packet = deepcopy(measurement.packet)
        if promoted:
            states = dict(packet["dimension_states"])
            states[_PROMOTABLE_DIMENSION] = "PASS"
            # Intentionally do not promote CROSS_DOMAIN_BREADTH.
            packet["dimension_states"] = states
            packet["independent_review"] = {
                "status": "PASS",
                "receipt_digest": receipt_digest,
                "live_current": True,
                "qualification_artifact_digest": (
                    measurement.qualification_artifact_digest
                ),
                "single_domain_breadth_ceiling": True,
            }
        return CompositionalTransferPromotionAssessment(
            promoted=promoted,
            packet=packet,
            reason=reason,
            independent_review_receipt_digest=receipt_digest,
        )

    def promote(
        self,
        measurement: CompositionalTransferQualificationResult,
        *,
        task_id: str,
        consumer_id: str,
        probe_id: str,
        review_id: str,
    ) -> CompositionalTransferPromotionAssessment:
        if type(measurement) is not CompositionalTransferQualificationResult:
            raise TypeError(
                "measurement must be exact "
                "CompositionalTransferQualificationResult"
            )

        packet = measurement.packet
        probe = packet.get("probe")
        states = packet.get("dimension_states")
        if not isinstance(probe, dict) or not isinstance(states, dict):
            raise ValueError("measurement packet is structurally incomplete")
        if probe.get("family") != "COMPOSITIONAL_TRANSFER":
            raise ValueError(
                "promotion requires COMPOSITIONAL_TRANSFER evidence"
            )
        if probe.get("probe_id") != probe_id:
            return self._answer(
                measurement,
                promoted=False,
                reason="review probe does not match measurement probe",
            )

        transfer_state = states.get(_PROMOTABLE_DIMENSION)
        breadth_state = states.get(_BREADTH_DIMENSION)
        if transfer_state == "FAIL" or breadth_state == "FAIL":
            return self._answer(
                measurement,
                promoted=False,
                reason="failed measurement state cannot be rescued by review",
            )
        if transfer_state != "PARTIAL" or breadth_state != "PARTIAL":
            return self._answer(
                measurement,
                promoted=False,
                reason=(
                    "promotion requires both compositional measurement states "
                    "to be PARTIAL"
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
                "cut and compositional qualification artifact; "
                "single-domain breadth remains PARTIAL"
            ),
            receipt_digest=receipt.receipt_digest,
        )
