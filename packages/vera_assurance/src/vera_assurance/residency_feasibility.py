"""Analytical specialist-residency feasibility assurance.

Adapted from Mosaic's deterministic residency harness. This module models
declared byte budgets only. It does not inspect accelerator/device state,
perform swaps, or establish hardware qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterable


class ResidencyFeasibilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SpecialistResidency:
    specialist_id: str
    weight_bytes: int
    runtime_bytes: int

    def __post_init__(self) -> None:
        if type(self.specialist_id) is not str or not self.specialist_id:
            raise ValueError("specialist_id must be a non-empty exact string")
        for label, value in (
            ("weight_bytes", self.weight_bytes),
            ("runtime_bytes", self.runtime_bytes),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative exact integer")

    @property
    def resident_bytes(self) -> int:
        return self.weight_bytes + self.runtime_bytes


@dataclass(frozen=True, slots=True)
class ResidencyEnvelope:
    resident_ceiling_bytes: int
    shared_core_bytes: int
    specialists: tuple[SpecialistResidency, ...]

    def __post_init__(self) -> None:
        if (
            type(self.resident_ceiling_bytes) is not int
            or self.resident_ceiling_bytes <= 0
        ):
            raise ValueError(
                "resident_ceiling_bytes must be a positive exact integer"
            )
        if type(self.shared_core_bytes) is not int or self.shared_core_bytes < 0:
            raise ValueError(
                "shared_core_bytes must be a non-negative exact integer"
            )
        object.__setattr__(self, "specialists", tuple(self.specialists))
        if not self.specialists:
            raise ValueError("specialists must not be empty")
        if any(type(item) is not SpecialistResidency for item in self.specialists):
            raise TypeError(
                "specialists must contain exact SpecialistResidency values"
            )
        ids = [item.specialist_id for item in self.specialists]
        if len(ids) != len(set(ids)):
            raise ValueError("specialist_id values must be unique")


@dataclass(frozen=True, slots=True)
class ResidencyStep:
    index: int
    specialist_id: str
    modeled_resident_bytes: int
    within_declared_ceiling: bool


@dataclass(frozen=True, slots=True)
class ResidencyFeasibilityReport:
    input_sha256: str
    resident_ceiling_bytes: int
    total_logical_pool_bytes: int
    modeled_peak_resident_bytes: int
    logical_pool_exceeds_ceiling: bool
    all_modeled_steps_within_ceiling: bool
    steps: tuple[ResidencyStep, ...]
    hardware_measurement_performed: bool = False
    qualification: str = "ANALYTICAL_FEASIBILITY_ONLY"
    authorization_effect: str = "NONE"


def _input_digest(
    envelope: ResidencyEnvelope,
    sequence: tuple[str, ...],
) -> str:
    subject = {
        "schema": "VERA_ANALYTICAL_RESIDENCY_SUBJECT_V1",
        "resident_ceiling_bytes": envelope.resident_ceiling_bytes,
        "shared_core_bytes": envelope.shared_core_bytes,
        "specialists": [
            {
                "specialist_id": item.specialist_id,
                "weight_bytes": item.weight_bytes,
                "runtime_bytes": item.runtime_bytes,
            }
            for item in envelope.specialists
        ],
        "sequence": list(sequence),
    }
    canonical = json.dumps(
        subject,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def evaluate_residency_sequence(
    envelope: ResidencyEnvelope,
    sequence: Iterable[str],
) -> ResidencyFeasibilityReport:
    if type(envelope) is not ResidencyEnvelope:
        raise TypeError("envelope must be exact ResidencyEnvelope")

    ordered = tuple(sequence)
    if not ordered:
        raise ResidencyFeasibilityError("residency sequence must not be empty")
    if any(type(item) is not str or not item for item in ordered):
        raise ResidencyFeasibilityError(
            "residency sequence must contain non-empty exact strings"
        )

    by_id = {item.specialist_id: item for item in envelope.specialists}
    steps: list[ResidencyStep] = []
    peak = 0
    for index, specialist_id in enumerate(ordered):
        specialist = by_id.get(specialist_id)
        if specialist is None:
            raise ResidencyFeasibilityError(
                f"unknown specialist in sequence: {specialist_id}"
            )
        modeled = envelope.shared_core_bytes + specialist.resident_bytes
        peak = max(peak, modeled)
        steps.append(
            ResidencyStep(
                index=index,
                specialist_id=specialist_id,
                modeled_resident_bytes=modeled,
                within_declared_ceiling=(
                    modeled <= envelope.resident_ceiling_bytes
                ),
            )
        )

    total_pool = envelope.shared_core_bytes + sum(
        item.resident_bytes for item in envelope.specialists
    )
    return ResidencyFeasibilityReport(
        input_sha256=_input_digest(envelope, ordered),
        resident_ceiling_bytes=envelope.resident_ceiling_bytes,
        total_logical_pool_bytes=total_pool,
        modeled_peak_resident_bytes=peak,
        logical_pool_exceeds_ceiling=(
            total_pool > envelope.resident_ceiling_bytes
        ),
        all_modeled_steps_within_ceiling=all(
            step.within_declared_ceiling for step in steps
        ),
        steps=tuple(steps),
    )
