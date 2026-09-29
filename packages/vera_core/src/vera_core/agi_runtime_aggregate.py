"""Runtime-bound aggregation for AGI research evidence.

The pure aggregate function is arithmetic over packet states. This adapter is
the qualified route for consuming PASS states: every PASS-bearing packet must
be rebound to a live-current independent review receipt and may contribute
only dimensions registered for its probe family.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence, TYPE_CHECKING, Any

from .agi_evaluation import _FAMILY_DIMENSIONS
from .agi_qualification import aggregate_agi_qualification

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class AGIPacketReviewBinding:
    probe_id: str
    task_id: str
    consumer_id: str
    review_id: str

    def __post_init__(self) -> None:
        for name in ("probe_id", "task_id", "consumer_id", "review_id"):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty exact string")


class QualifiedAGIRuntimeAggregateAdapter:
    """Validate packet authority before invoking arithmetic aggregation."""

    def __init__(self, *, runtime: "QualifiedVeraRuntime") -> None:
        self.runtime = runtime

    @staticmethod
    def _binding_map(
        bindings: Sequence[AGIPacketReviewBinding],
    ) -> dict[str, AGIPacketReviewBinding]:
        out: dict[str, AGIPacketReviewBinding] = {}
        for binding in bindings:
            if type(binding) is not AGIPacketReviewBinding:
                raise TypeError(
                    "review_bindings must contain exact "
                    "AGIPacketReviewBinding values"
                )
            if binding.probe_id in out:
                raise ValueError(
                    f"duplicate review binding for probe {binding.probe_id!r}"
                )
            out[binding.probe_id] = binding
        return out

    def _verify_pass_packet(
        self,
        packet: Mapping[str, Any],
        binding: AGIPacketReviewBinding,
    ) -> None:
        probe = packet.get("probe")
        results = packet.get("results")
        review_meta = packet.get("independent_review")
        if not isinstance(probe, Mapping):
            raise ValueError("PASS packet is missing probe metadata")
        if not isinstance(results, Mapping):
            raise ValueError("PASS packet is missing results metadata")
        if not isinstance(review_meta, Mapping):
            raise ValueError(
                "PASS packet requires a live independent review binding"
            )
        if review_meta.get("status") != "PASS":
            raise ValueError("PASS packet independent review is not PASS")

        probe_id = probe.get("probe_id")
        if probe_id != binding.probe_id:
            raise ValueError("review binding probe does not match packet probe")

        assessment = self.runtime.assess_independent_behavior_review(
            binding.task_id,
            binding.consumer_id,
            binding.probe_id,
            binding.review_id,
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
            raise ValueError(
                "PASS packet review is not live-current and independently "
                "verified"
            )

        try:
            receipt = self.runtime.independent_behavior_reviews.latest(
                binding.task_id,
                binding.consumer_id,
                binding.probe_id,
                binding.review_id,
            )
        except KeyError as exc:
            raise ValueError(
                "PASS packet current review receipt is missing"
            ) from exc

        expected_receipt = review_meta.get("receipt_digest")
        if (
            type(expected_receipt) is not str
            or assessment.latest_receipt_digest != expected_receipt
            or receipt.receipt_digest != expected_receipt
            or receipt.status != "PASS"
        ):
            raise ValueError(
                "PASS packet does not bind the current review receipt"
            )

        requirement = receipt.payload.get("requirement")
        observation = receipt.payload.get("observation")
        if not isinstance(requirement, Mapping) or not isinstance(
            observation, Mapping
        ):
            raise ValueError("current review receipt payload is incomplete")

        if (
            requirement.get("held_out_probe_set_digest")
            != probe.get("items_digest")
        ):
            raise ValueError(
                "current review receipt binds a different held-out set"
            )

        artifact_digest = results.get("raw_artifact_digest")
        if observation.get("result_digest") != artifact_digest:
            raise ValueError(
                "current review receipt binds a different result artifact"
            )
        if observation.get("verdict") != "PASS":
            raise ValueError("current review observation verdict is not PASS")

    def aggregate(
        self,
        packets: Sequence[Mapping[str, Any]],
        *,
        subject_head: str,
        review_bindings: Sequence[AGIPacketReviewBinding],
        claim_ceiling: str,
    ) -> dict[str, object]:
        bindings = self._binding_map(review_bindings)
        used_bindings: set[str] = set()

        for packet in packets:
            if not isinstance(packet, Mapping):
                raise TypeError("packets must contain mapping values")
            probe = packet.get("probe")
            states = packet.get("dimension_states")
            if not isinstance(probe, Mapping) or not isinstance(
                states, Mapping
            ):
                raise ValueError("evaluation packet is structurally incomplete")

            family = probe.get("family")
            probe_id = probe.get("probe_id")
            if family not in _FAMILY_DIMENSIONS:
                raise ValueError(f"unsupported probe family: {family!r}")
            allowed = frozenset(_FAMILY_DIMENSIONS[family])
            overclaim = sorted(
                dimension for dimension in states if dimension not in allowed
            )
            if overclaim:
                raise ValueError(
                    "packet contains dimension outside registered family "
                    f"scope: {', '.join(overclaim)}"
                )

            if any(state == "PASS" for state in states.values()):
                if type(probe_id) is not str or not probe_id:
                    raise ValueError("PASS packet probe_id is missing")
                binding = bindings.get(probe_id)
                if binding is None:
                    raise ValueError(
                        f"PASS packet requires review binding for {probe_id!r}"
                    )
                self._verify_pass_packet(packet, binding)
                used_bindings.add(probe_id)

        unused = sorted(set(bindings) - used_bindings)
        if unused:
            raise ValueError(
                "review binding supplied for packet without PASS evidence: "
                + ", ".join(unused)
            )

        return aggregate_agi_qualification(
            packets,
            subject_head=subject_head,
            independent_review_state="NOT_REVIEWED",
            claim_ceiling=claim_ceiling,
        )
