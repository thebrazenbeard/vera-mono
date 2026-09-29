"""Fail-closed resource-envelope assurance.

Adapted from Noema's deterministic accounting layer. This module adjudicates
supplied measurements only. It does not own platform instrumentation, scheduling,
execution, or effect authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class FixedResourceEnvelope:
    max_resident_memory_bytes: int
    max_durable_state_bytes: int
    max_update_cpu_seconds: float
    max_query_cpu_seconds: float
    max_shadow_auditions: int

    def __post_init__(self) -> None:
        if (
            type(self.max_resident_memory_bytes) is not int
            or self.max_resident_memory_bytes < 0
        ):
            raise ValueError(
                "max_resident_memory_bytes must be a non-negative exact integer"
            )
        if (
            type(self.max_durable_state_bytes) is not int
            or self.max_durable_state_bytes < 0
        ):
            raise ValueError(
                "max_durable_state_bytes must be a non-negative exact integer"
            )
        for label, value in (
            ("max_update_cpu_seconds", self.max_update_cpu_seconds),
            ("max_query_cpu_seconds", self.max_query_cpu_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{label} must be a finite non-negative number")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{label} must be a finite non-negative number")
        if type(self.max_shadow_auditions) is not int or self.max_shadow_auditions < 0:
            raise ValueError(
                "max_shadow_auditions must be a non-negative exact integer"
            )


@dataclass(frozen=True, slots=True)
class ResourceUsage:
    resident_memory_bytes: int | None
    durable_state_bytes: int | None
    update_cpu_seconds: float | None
    query_cpu_seconds: float | None
    shadow_auditions: int | None

    def __post_init__(self) -> None:
        for label in (
            "resident_memory_bytes",
            "durable_state_bytes",
            "shadow_auditions",
        ):
            value = getattr(self, label)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(
                    f"{label} must be null or a non-negative exact integer"
                )
        for label in ("update_cpu_seconds", "query_cpu_seconds"):
            value = getattr(self, label)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"{label} must be null or a finite non-negative number"
                )
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(
                    f"{label} must be null or a finite non-negative number"
                )


@dataclass(frozen=True, slots=True)
class ResourceEnvelopeReport:
    valid: bool
    violations: tuple[str, ...]
    authorization_effect: str = "NONE"


def adjudicate_resource_envelope(
    envelope: FixedResourceEnvelope,
    usage: ResourceUsage,
) -> ResourceEnvelopeReport:
    if type(envelope) is not FixedResourceEnvelope:
        raise TypeError("envelope must be exact FixedResourceEnvelope")
    if type(usage) is not ResourceUsage:
        raise TypeError("usage must be exact ResourceUsage")

    limits = {
        "resident_memory_bytes": envelope.max_resident_memory_bytes,
        "durable_state_bytes": envelope.max_durable_state_bytes,
        "update_cpu_seconds": float(envelope.max_update_cpu_seconds),
        "query_cpu_seconds": float(envelope.max_query_cpu_seconds),
        "shadow_auditions": envelope.max_shadow_auditions,
    }

    violations: list[str] = []
    for field, limit in limits.items():
        observed = getattr(usage, field)
        if observed is None:
            violations.append(f"{field}:UNMEASURED")
        elif observed > limit:
            violations.append(f"{field}:OVER_LIMIT")

    return ResourceEnvelopeReport(
        valid=not violations,
        violations=tuple(violations),
    )
