from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .core import CalculatorPolicy, calculate_elapsed, validate_semantic_source
from .types import (
    AssistantMessageEvent,
    CapabilityClass,
    ElapsedResult,
    ElapsedStatus,
    GenerationEvent,
    InboundEvent,
    LifecycleEvaluation,
    Speaker,
    TemporalEndpoint,
    TimeSemantics,
    TimestampSource,
)


class EvidenceValidationError(ValueError):
    """Raised when strict adapter validation rejects malformed evidence."""


@dataclass(frozen=True)
class TulAdapter:
    policy: CalculatorPolicy = CalculatorPolicy()

    def evaluate(
        self,
        inbound: InboundEvent,
        generation: GenerationEvent,
        assistant: AssistantMessageEvent,
    ) -> LifecycleEvaluation:
        relation_errors = self._relation_errors(inbound, generation, assistant)
        structural_errors = self._structural_errors(inbound, generation, assistant)
        if relation_errors or structural_errors:
            reasons = tuple([*relation_errors, *structural_errors])
            conflicted = ElapsedResult(status=ElapsedStatus.CONFLICTED, reasons=reasons)
            return LifecycleEvaluation(
                capability=CapabilityClass.PARTIAL,
                causal_binding=ElapsedStatus.CONFLICTED,
                inbound_to_generation=conflicted,
                inbound_to_assistant=conflicted,
                reasons=reasons,
            )

        inbound_to_generation = calculate_elapsed(
            inbound.endpoint,
            generation.endpoint,
            policy=self.policy,
        )
        inbound_to_assistant = calculate_elapsed(
            inbound.endpoint,
            assistant.endpoint,
            policy=self.policy,
        )

        full = (
            inbound.endpoint.timestamp is not None
            and generation.endpoint.timestamp is not None
            and assistant.endpoint.timestamp is not None
            and inbound.endpoint.semantics is TimeSemantics.MESSAGE_CREATION
            and generation.endpoint.semantics is TimeSemantics.GENERATION_INVOCATION_START
            and assistant.endpoint.semantics is TimeSemantics.MESSAGE_CREATION
            and inbound_to_generation.status
            in {ElapsedStatus.EXACT, ElapsedStatus.BOUNDED, ElapsedStatus.APPROXIMATE}
            and inbound_to_assistant.status
            in {ElapsedStatus.EXACT, ElapsedStatus.BOUNDED, ElapsedStatus.APPROXIMATE}
        )

        any_available = any(
            endpoint.timestamp is not None
            for endpoint in (inbound.endpoint, generation.endpoint, assistant.endpoint)
        )
        capability = (
            CapabilityClass.FULL
            if full
            else CapabilityClass.PARTIAL
            if any_available
            else CapabilityClass.UNAVAILABLE
        )

        return LifecycleEvaluation(
            capability=capability,
            causal_binding=ElapsedStatus.EXACT,
            inbound_to_generation=inbound_to_generation,
            inbound_to_assistant=inbound_to_assistant,
        )

    def validate_strict(
        self,
        inbound: InboundEvent,
        generation: GenerationEvent,
        assistant: AssistantMessageEvent,
    ) -> None:
        errors = [
            *self._relation_errors(inbound, generation, assistant),
            *self._structural_errors(inbound, generation, assistant),
        ]
        if errors:
            raise EvidenceValidationError("; ".join(errors))

    @staticmethod
    def _relation_errors(
        inbound: InboundEvent,
        generation: GenerationEvent,
        assistant: AssistantMessageEvent,
    ) -> list[str]:
        errors: list[str] = []
        if generation.in_response_to_message_id != inbound.message_id:
            errors.append("generation causal binding does not match inbound.message_id")
        if assistant.in_response_to_message_id != inbound.message_id:
            errors.append("assistant causal binding does not match inbound.message_id")
        return errors

    @staticmethod
    def _structural_errors(
        inbound: InboundEvent,
        generation: GenerationEvent,
        assistant: AssistantMessageEvent,
    ) -> list[str]:
        errors: list[str] = []
        if not inbound.message_id:
            errors.append("inbound.message_id is required")
        if not assistant.message_id:
            errors.append("assistant.message_id is required")
        if inbound.speaker is not Speaker.USER:
            errors.append("fixture inbound speaker must be USER")
        if assistant.speaker is not Speaker.ASSISTANT:
            errors.append("assistant speaker must be ASSISTANT")
        if generation.generation_event_definition != "PRE_MODEL_INVOCATION":
            errors.append("generation event definition must be PRE_MODEL_INVOCATION")

        for label, endpoint in (
            ("inbound", inbound.endpoint),
            ("generation", generation.endpoint),
            ("assistant", assistant.endpoint),
        ):
            valid, reasons = validate_semantic_source(endpoint)
            if not valid:
                errors.extend(f"{label}: {reason}" for reason in reasons)
        return errors


_ALLOWED_ENDPOINT_KEYS = {
    "timestamp",
    "time_semantics",
    "timestamp_source",
    "clock_domain",
    "resolution_seconds",
    "uncertainty_seconds",
}


def reject_semantic_payload(mapping: Mapping[str, Any], allowed_keys: set[str]) -> None:
    unknown = set(mapping) - allowed_keys
    if unknown:
        raise EvidenceValidationError(
            "semantic or unsupported payload keys are forbidden: " + ", ".join(sorted(unknown))
        )


def endpoint_from_mapping(mapping: Mapping[str, Any]) -> TemporalEndpoint:
    from datetime import datetime

    reject_semantic_payload(mapping, _ALLOWED_ENDPOINT_KEYS)
    raw_timestamp = mapping.get("timestamp")
    timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")) if raw_timestamp else None
    return TemporalEndpoint(
        timestamp=timestamp,
        semantics=TimeSemantics(mapping["time_semantics"]),
        source=TimestampSource(mapping["timestamp_source"]),
        clock_domain=mapping.get("clock_domain"),
        resolution_seconds=mapping.get("resolution_seconds"),
        uncertainty_seconds=mapping.get("uncertainty_seconds"),
    )
