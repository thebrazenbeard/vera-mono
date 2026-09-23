from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Speaker(str, Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class TimeSemantics(str, Enum):
    MESSAGE_CREATION = "MESSAGE_CREATION"
    GENERATION_INVOCATION_START = "GENERATION_INVOCATION_START"
    TURN_START = "TURN_START"
    TURN_COMPLETION = "TURN_COMPLETION"
    INGESTION = "INGESTION"
    UNKNOWN = "UNKNOWN"


class TimestampSource(str, Enum):
    PLATFORM_MESSAGE_METADATA = "PLATFORM_MESSAGE_METADATA"
    TRUSTED_BRIDGE = "TRUSTED_BRIDGE"
    HOST_RUNTIME_CLOCK = "HOST_RUNTIME_CLOCK"
    CODEX_TURN_METADATA = "CODEX_TURN_METADATA"
    UNAVAILABLE = "UNAVAILABLE"


class ElapsedStatus(str, Enum):
    EXACT = "EXACT"
    BOUNDED = "BOUNDED"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICTED = "CONFLICTED"


class CapabilityClass(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class TemporalEndpoint:
    timestamp: datetime | None
    semantics: TimeSemantics
    source: TimestampSource
    clock_domain: str | None
    resolution_seconds: float | None
    uncertainty_seconds: float | None

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
                raise ValueError("timestamp must be timezone-aware")
        for name, value in (
            ("resolution_seconds", self.resolution_seconds),
            ("uncertainty_seconds", self.uncertainty_seconds),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": isoformat_z(self.timestamp),
            "time_semantics": self.semantics.value,
            "timestamp_source": self.source.value,
            "clock_domain": self.clock_domain,
            "resolution_seconds": self.resolution_seconds,
            "uncertainty_seconds": self.uncertainty_seconds,
        }


@dataclass(frozen=True)
class InboundEvent:
    message_id: str
    speaker: Speaker
    endpoint: TemporalEndpoint

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "speaker": self.speaker.value,
            **self.endpoint.to_dict(),
        }


@dataclass(frozen=True)
class GenerationEvent:
    in_response_to_message_id: str
    endpoint: TemporalEndpoint
    generation_event_definition: str = "PRE_MODEL_INVOCATION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "in_response_to_message_id": self.in_response_to_message_id,
            "generation_event_definition": self.generation_event_definition,
            **self.endpoint.to_dict(),
        }


@dataclass(frozen=True)
class AssistantMessageEvent:
    message_id: str
    speaker: Speaker
    in_response_to_message_id: str
    endpoint: TemporalEndpoint
    capture_mode: str = "POST_RESPONSE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "speaker": self.speaker.value,
            "in_response_to_message_id": self.in_response_to_message_id,
            "capture_mode": self.capture_mode,
            **self.endpoint.to_dict(),
        }


@dataclass(frozen=True)
class ApproximationEvidence:
    estimated_elapsed_seconds: float
    method: str
    error_model: str

    def is_documented(self) -> bool:
        return (
            self.estimated_elapsed_seconds >= 0
            and bool(self.method.strip())
            and bool(self.error_model.strip())
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimated_elapsed_seconds": self.estimated_elapsed_seconds,
            "method": self.method,
            "error_model": self.error_model,
        }


@dataclass(frozen=True)
class ElapsedResult:
    status: ElapsedStatus
    value_seconds: float | None = None
    lower_bound_seconds: float | None = None
    upper_bound_seconds: float | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "value_seconds": self.value_seconds,
            "lower_bound_seconds": self.lower_bound_seconds,
            "upper_bound_seconds": self.upper_bound_seconds,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class LifecycleEvaluation:
    capability: CapabilityClass
    causal_binding: ElapsedStatus
    inbound_to_generation: ElapsedResult
    inbound_to_assistant: ElapsedResult
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.value,
            "causal_binding": self.causal_binding.value,
            "inbound_to_generation": self.inbound_to_generation.to_dict(),
            "inbound_to_assistant": self.inbound_to_assistant.to_dict(),
            "reasons": list(self.reasons),
        }


def isoformat_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
