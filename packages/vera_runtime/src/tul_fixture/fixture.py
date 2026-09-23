from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Protocol

from .adapter import TulAdapter
from .types import (
    AssistantMessageEvent,
    GenerationEvent,
    InboundEvent,
    LifecycleEvaluation,
    Speaker,
    TemporalEndpoint,
    TimeSemantics,
    TimestampSource,
)


@dataclass(frozen=True)
class ClockReading:
    timestamp: datetime
    clock_domain: str
    resolution_seconds: float
    uncertainty_seconds: float


class Clock(Protocol):
    def read(self) -> ClockReading: ...


class SystemClock:
    """Wall-clock source controlled by the local fixture host."""

    def __init__(self, *, clock_domain: str = "python:time.time_ns") -> None:
        info = time.get_clock_info("time")
        self._clock_domain = clock_domain
        self._resolution = max(float(info.resolution), 1e-9)

    def read(self) -> ClockReading:
        nanoseconds = time.time_ns()
        timestamp = datetime.fromtimestamp(nanoseconds / 1_000_000_000, tz=timezone.utc)
        return ClockReading(
            timestamp=timestamp,
            clock_domain=self._clock_domain,
            resolution_seconds=self._resolution,
            uncertainty_seconds=self._resolution,
        )


class SequenceClock:
    """Deterministic clock for proof and adversarial tests."""

    def __init__(self, readings: Iterable[ClockReading]) -> None:
        self._readings = iter(readings)

    def read(self) -> ClockReading:
        try:
            return next(self._readings)
        except StopIteration as exc:
            raise RuntimeError("SequenceClock exhausted") from exc


ModelCall = Callable[[str, dict[str, Any]], str | Awaitable[str]]


@dataclass(frozen=True)
class HostFixtureExecution:
    inbound: InboundEvent
    generation: GenerationEvent
    assistant: AssistantMessageEvent
    evaluation: LifecycleEvaluation
    model_output: str

    def to_proof_dict(self) -> dict[str, Any]:
        """Return non-semantic proof evidence. Model text is intentionally excluded."""
        return {
            "inbound": self.inbound.to_dict(),
            "generation": self.generation.to_dict(),
            "assistant": self.assistant.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "semantic_payload_included": False,
        }


class InstrumentedHostFixture:
    """Minimal controlled host that creates and binds all TUL lifecycle events."""

    def __init__(self, *, clock: Clock | None = None, adapter: TulAdapter | None = None) -> None:
        self.clock = clock or SystemClock()
        self.adapter = adapter or TulAdapter()

    async def run_async(self, user_text: str, model_call: ModelCall) -> HostFixtureExecution:
        inbound_id = f"msg-user-{uuid.uuid4()}"
        inbound_reading = self.clock.read()
        inbound = InboundEvent(
            message_id=inbound_id,
            speaker=Speaker.USER,
            endpoint=self._endpoint(
                inbound_reading,
                semantics=TimeSemantics.MESSAGE_CREATION,
                source=TimestampSource.TRUSTED_BRIDGE,
            ),
        )

        generation_reading = self.clock.read()
        generation = GenerationEvent(
            in_response_to_message_id=inbound.message_id,
            endpoint=self._endpoint(
                generation_reading,
                semantics=TimeSemantics.GENERATION_INVOCATION_START,
                source=TimestampSource.HOST_RUNTIME_CLOCK,
            ),
        )

        temporal_context = {
            "inbound": inbound.to_dict(),
            "reply_generation": generation.to_dict(),
        }
        result = model_call(user_text, temporal_context)
        model_output = await result if inspect.isawaitable(result) else result
        if not isinstance(model_output, str):
            raise TypeError("model_call must return str or Awaitable[str]")

        assistant_reading = self.clock.read()
        assistant = AssistantMessageEvent(
            message_id=f"msg-assistant-{uuid.uuid4()}",
            speaker=Speaker.ASSISTANT,
            in_response_to_message_id=inbound.message_id,
            endpoint=self._endpoint(
                assistant_reading,
                semantics=TimeSemantics.MESSAGE_CREATION,
                source=TimestampSource.TRUSTED_BRIDGE,
            ),
        )

        evaluation = self.adapter.evaluate(inbound, generation, assistant)
        return HostFixtureExecution(
            inbound=inbound,
            generation=generation,
            assistant=assistant,
            evaluation=evaluation,
            model_output=model_output,
        )

    def run(self, user_text: str, model_call: ModelCall) -> HostFixtureExecution:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(user_text, model_call))
        raise RuntimeError("run() cannot be called inside a running event loop; use run_async()")

    @staticmethod
    def _endpoint(
        reading: ClockReading,
        *,
        semantics: TimeSemantics,
        source: TimestampSource,
    ) -> TemporalEndpoint:
        return TemporalEndpoint(
            timestamp=reading.timestamp,
            semantics=semantics,
            source=source,
            clock_domain=reading.clock_domain,
            resolution_seconds=reading.resolution_seconds,
            uncertainty_seconds=reading.uncertainty_seconds,
        )
