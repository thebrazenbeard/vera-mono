from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

from vera_assurance import EffectFence

from .action_gate import LifecycleBoundCoordinationBus, LifecycleEffectGateway
from .effect_recovery import (
    EffectReconciliationVerifier,
    LifecycleEffectRecovery,
)
from .lifecycle import AcceptedLifecyclePermit, NativeVeraLifecycle
from .outbound_authority import (
    PCJobAuthorityVerifier,
    ProviderAuthorityVerifier,
)
from .outbound_trust import OutboundTrustRegistry
from .state import VeraStateDirectory


@dataclass(frozen=True, slots=True)
class QualifiedVeraRuntime:
    """Canonical host-composed escape boundary for vera-mono.

    The state directory owns durable local state. Trusted authority verifiers are
    injected by the host at construction and are intentionally not persisted by
    this object. Low-level bus, PC, provider, and mechanical fence primitives
    remain available for tests/adapters, but this is the qualified composition
    root for outbound behavior.
    """

    lifecycle: NativeVeraLifecycle
    fence: EffectFence
    effects: LifecycleEffectGateway
    coordination: LifecycleBoundCoordinationBus | None
    recovery: LifecycleEffectRecovery | None
    outbound_trust: OutboundTrustRegistry

    @classmethod
    def from_state_directory(
        cls,
        state: VeraStateDirectory,
        *,
        pc_authority_verifier: PCJobAuthorityVerifier | None = None,
        provider_authority_verifiers: Mapping[
            str, ProviderAuthorityVerifier
        ] | None = None,
        reconciliation_verifier: EffectReconciliationVerifier | None = None,
        coordination_bus: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> "QualifiedVeraRuntime":
        if type(state) is not VeraStateDirectory:
            raise TypeError("state must be an exact VeraStateDirectory")

        lifecycle = state.open()
        fence = lifecycle.effect_fence or state.effect_fence()
        outbound_trust = state.outbound_trust_registry()
        outbound_trust.verify_chain()

        if pc_authority_verifier is not None:
            outbound_trust.assert_current(
                authority_id=pc_authority_verifier.authority_id,
                role="PC",
                key_id=pc_authority_verifier.key_id,
                key_digest=pc_authority_verifier.key_digest,
            )
        for provider_id, verifier in dict(
            provider_authority_verifiers or {}
        ).items():
            outbound_trust.assert_current(
                authority_id=verifier.authority_id,
                role="PROVIDER",
                provider_id=provider_id,
                key_id=verifier.key_id,
                key_digest=verifier.key_digest,
            )
        if reconciliation_verifier is not None:
            outbound_trust.assert_current(
                authority_id=reconciliation_verifier.authority_id,
                role="RECONCILIATION",
                key_id=reconciliation_verifier.key_id,
                key_digest=reconciliation_verifier.key_digest,
            )

        effects = LifecycleEffectGateway(
            lifecycle=lifecycle,
            fence=fence,
            pc_authority_verifier=pc_authority_verifier,
            provider_authority_verifiers=provider_authority_verifiers,
            outbound_trust_registry=outbound_trust,
            clock=clock,
        )
        coordination = (
            None
            if coordination_bus is None
            else LifecycleBoundCoordinationBus(
                lifecycle=lifecycle,
                bus=coordination_bus,
                fence=fence,
            )
        )
        recovery = (
            None
            if reconciliation_verifier is None
            else LifecycleEffectRecovery(
                fence=fence,
                verifier=reconciliation_verifier,
                outbound_trust_registry=outbound_trust,
            )
        )
        return cls(
            lifecycle=lifecycle,
            fence=fence,
            effects=effects,
            coordination=coordination,
            recovery=recovery,
            outbound_trust=outbound_trust,
        )

    def accepted_permit(self) -> AcceptedLifecyclePermit:
        return self.lifecycle.accepted_action_permit()

    def resume_context(self) -> dict[str, Any]:
        return self.lifecycle.reconstruct().as_resume_context()
