"""Vera monorepo composition root."""

from .lifecycle import (
    LifecycleAssuranceError,
    NativeLifecycleReceipt,
    NativeVeraLifecycle,
)
from .reasoning_cascade import (
    CascadeEngine,
    CascadeOutcome,
    LayerResult,
    LayerSpec,
    ReasoningRequest,
)
from .registry import CAPABILITIES, LocalCapability, capability, validate_registry

__all__ = [
    "CAPABILITIES",
    "CascadeEngine",
    "CascadeOutcome",
    "LayerResult",
    "LayerSpec",
    "LifecycleAssuranceError",
    "LocalCapability",
    "NativeLifecycleReceipt",
    "NativeVeraLifecycle",
    "ReasoningRequest",
    "capability",
    "validate_registry",
]
