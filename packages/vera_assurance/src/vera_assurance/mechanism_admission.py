"""Evidence gate for admitting new mechanisms into a composed system.

Adapted from World Zero's mechanism-admission controls. Passing this internal
gate means only that a mechanism has the minimum bounded evidence packet for
source-level composition; it is not independent review or runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass


class MechanismAdmissionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MechanismEvidencePacket:
    mechanism_id: str
    clarity_pass: bool
    identifiability: str
    kill_test_id: str | None
    kill_test_survived: bool
    holdout_or_invariant_target: str | None
    holdout_or_invariant_value_pass: bool
    ablation_expectation: str | None
    ablation_value_pass: bool
    structural_rival_analysis: str | None
    complexity_proportionate: bool
    numerical_integrity: str
    unresolved_negative_transfer_defects: tuple[str, ...] = ()
    hard_invariant_required: bool = False
    authorization_effect: str = "NONE"

    def __post_init__(self) -> None:
        if type(self.mechanism_id) is not str or not self.mechanism_id:
            raise ValueError("mechanism_id must be a non-empty exact string")
        if type(self.identifiability) is not str or not self.identifiability:
            raise ValueError("identifiability must be a non-empty exact string")
        object.__setattr__(
            self,
            "unresolved_negative_transfer_defects",
            tuple(self.unresolved_negative_transfer_defects),
        )
        if any(
            type(item) is not str or not item
            for item in self.unresolved_negative_transfer_defects
        ):
            raise ValueError(
                "negative-transfer defects must be non-empty exact strings"
            )
        if self.authorization_effect != "NONE":
            raise ValueError("mechanism admission cannot mint authorization")


def mechanism_admission_defects(
    packet: MechanismEvidencePacket,
) -> tuple[str, ...]:
    if type(packet) is not MechanismEvidencePacket:
        raise TypeError("packet must be exact MechanismEvidencePacket")

    defects: list[str] = []
    if packet.clarity_pass is not True:
        defects.append("semantic/boundary clarity gate did not pass")

    ordinarily_identifiable = packet.identifiability in {
        "IDENTIFIABLE_ENOUGH_FOR_TEST",
        "WEAKLY_IDENTIFIABLE",
    }
    if not ordinarily_identifiable and not packet.hard_invariant_required:
        defects.append(
            "identifiability is below WEAKLY_IDENTIFIABLE without a hard-invariant exception"
        )

    if type(packet.kill_test_id) is not str or not packet.kill_test_id:
        defects.append("preregistered kill test is missing")
    elif packet.kill_test_survived is not True:
        defects.append("preregistered kill test has not been survived")

    if (
        type(packet.holdout_or_invariant_target) is not str
        or not packet.holdout_or_invariant_target
    ):
        defects.append("holdout or invariant target is missing")
    if packet.holdout_or_invariant_value_pass is not True:
        defects.append("claim-relevant holdout/invariant value has not passed")

    if (
        type(packet.ablation_expectation) is not str
        or not packet.ablation_expectation
    ):
        defects.append("ablation expectation is missing")
    if packet.ablation_value_pass is not True:
        defects.append("nontrivial ablation value has not passed")

    if (
        type(packet.structural_rival_analysis) is not str
        or not packet.structural_rival_analysis
    ):
        defects.append("structural rival analysis is missing")

    if packet.complexity_proportionate is not True:
        defects.append("complexity cost is not proportionate to demonstrated gain")

    if packet.numerical_integrity != "PASS":
        defects.append(
            f"numerical integrity is not PASS: {packet.numerical_integrity}"
        )

    if packet.unresolved_negative_transfer_defects:
        defects.append(
            "unresolved negative-transfer defect(s): "
            + ", ".join(packet.unresolved_negative_transfer_defects)
        )

    return tuple(defects)


def assert_mechanism_admissible(packet: MechanismEvidencePacket) -> None:
    defects = mechanism_admission_defects(packet)
    if defects:
        raise MechanismAdmissionError(
            f"{packet.mechanism_id}: " + "; ".join(defects)
        )
