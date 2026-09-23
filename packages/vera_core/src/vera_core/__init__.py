"""Vera monorepo composition root."""

from .lifecycle import (
    LifecycleAssuranceError,
    LifecycleReconstruction,
    LifecycleReconstructionError,
    NativeLifecycleReceipt,
    NativeVeraLifecycle,
)
from .lifecycle_journal import (
    LifecycleEvent,
    LifecycleJournal,
    LifecycleJournalError,
)
from .reasoning_cascade import (
    CascadeEngine,
    CascadeOutcome,
    LayerResult,
    LayerSpec,
    ReasoningRequest,
)
from .registry import CAPABILITIES, LocalCapability, capability, validate_registry
from .state import VeraStateDirectory, VeraStatePaths

__all__ = [
    "CAPABILITIES",
    "CascadeEngine",
    "CascadeOutcome",
    "LayerResult",
    "LayerSpec",
    "LifecycleAssuranceError",
    "LifecycleEvent",
    "LifecycleJournal",
    "LifecycleJournalError",
    "LifecycleReconstruction",
    "LifecycleReconstructionError",
    "LocalCapability",
    "NativeLifecycleReceipt",
    "NativeVeraLifecycle",
    "ReasoningRequest",
    "VeraStateDirectory",
    "VeraStatePaths",
    "capability",
    "validate_registry",
]
