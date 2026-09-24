"""Vera monorepo composition root."""

from .action_gate import (
    LifecycleBoundCoordinationBus,
    LifecycleEffectGateway,
    OutboundActionError,
    OutboundEffectResult,
)
from .effect_recovery import (
    EffectRecoveryAuthorityError,
    EffectReconciliationProof,
    EffectReconciliationVerifier,
    HmacEffectReconciliationAuthority,
    LifecycleEffectRecovery,
    reconciliation_subject,
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
from .outbound_authority import (
    HmacPCJobAuthority,
    HmacProviderAuthority,
    OutboundAuthorityError,
    PCJobAuthorityProof,
    PCJobAuthorityVerifier,
    ProviderAuthorityEnvelope,
    ProviderAuthorityVerifier,
    pc_authority_subject,
    provider_authority_subject,
    validate_pc_authorization_binding,
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
    "EffectRecoveryAuthorityError",
    "EffectReconciliationProof",
    "EffectReconciliationVerifier",
    "HmacEffectReconciliationAuthority",
    "LifecycleEffectRecovery",
    "reconciliation_subject",
    "CAPABILITIES",
    "CascadeEngine",
    "CascadeOutcome",
    "LayerResult",
    "LayerSpec",
    "LifecycleActionDenied",
    "HmacPCJobAuthority",
    "HmacProviderAuthority",
    "OutboundAuthorityError",
    "PCJobAuthorityProof",
    "PCJobAuthorityVerifier",
    "ProviderAuthorityEnvelope",
    "ProviderAuthorityVerifier",
    "pc_authority_subject",
    "provider_authority_subject",
    "validate_pc_authorization_binding",
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
