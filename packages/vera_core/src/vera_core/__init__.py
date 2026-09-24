"""Vera monorepo composition root."""

from .action_gate import (
    LifecycleBoundCoordinationBus,
    LifecycleEffectGateway,
    OutboundActionError,
    OutboundEffectResult,
)
from .lifecycle import (
    AcceptedLifecyclePermit,
    LifecycleActionDenied,
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
    "AcceptedLifecyclePermit",
    "CAPABILITIES",
    "CascadeEngine",
    "CascadeOutcome",
    "LayerResult",
    "LayerSpec",
    "LifecycleActionDenied",
    "LifecycleAssuranceError",
    "LifecycleBoundCoordinationBus",
    "LifecycleEffectGateway",
    "LifecycleEvent",
    "LifecycleJournal",
    "LifecycleJournalError",
    "LifecycleReconstruction",
    "LifecycleReconstructionError",
    "LocalCapability",
    "NativeLifecycleReceipt",
    "OutboundActionError",
    "OutboundEffectResult",
    "NativeVeraLifecycle",
    "ReasoningRequest",
    "VeraStateDirectory",
    "VeraStatePaths",
    "capability",
    "validate_registry",
]
