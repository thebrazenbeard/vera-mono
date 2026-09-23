"""Vera monorepo composition root."""

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
    "LocalCapability",
    "ReasoningRequest",
    "capability",
    "validate_registry",
]
