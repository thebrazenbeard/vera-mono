"""TUL Instrumented Host Fixture v0.1.

This package implements a local, host-controlled proof fixture for the frozen
TUL Host Capability Requirement v0.1.3. It does not claim native ChatGPT or
Codex lifecycle support.
"""

from .adapter import EvidenceValidationError, TulAdapter
from .core import CalculatorPolicy, calculate_elapsed
from .fixture import InstrumentedHostFixture, SequenceClock, SystemClock
from .types import (
    ApproximationEvidence,
    AssistantMessageEvent,
    CapabilityClass,
    ElapsedResult,
    ElapsedStatus,
    GenerationEvent,
    InboundEvent,
    Speaker,
    TimeSemantics,
    TimestampSource,
)

__all__ = [
    "ApproximationEvidence",
    "AssistantMessageEvent",
    "CalculatorPolicy",
    "CapabilityClass",
    "ElapsedResult",
    "ElapsedStatus",
    "EvidenceValidationError",
    "GenerationEvent",
    "InboundEvent",
    "InstrumentedHostFixture",
    "SequenceClock",
    "Speaker",
    "SystemClock",
    "TimeSemantics",
    "TimestampSource",
    "TulAdapter",
    "calculate_elapsed",
]
