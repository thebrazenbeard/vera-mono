from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, TypeVar

from vera_assurance import EffectFence, EffectReceipt, EffectState
from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope

from .action_gate import LifecycleBoundCoordinationBus, LifecycleEffectGateway
from .effect_recovery import (
    EffectReconciliationVerifier,
    LifecycleEffectRecovery,
)
from .execution_adapters import (
    PCExecutionTransport,
    ProviderExecutionTransport,
)
from .lifecycle import AcceptedLifecyclePermit, NativeVeraLifecycle
from .outbound_authority import (
    PCJobAuthorityProof,
    PCJobAuthorityVerifier,
    ProviderAuthorityEnvelope,
    ProviderAuthorityVerifier,
    pc_authority_subject,
    provider_authority_subject,
    validate_pc_authorization_binding,
)
from .outbound_audit import OutboundAuditConsistency, OutboundExecutionAudit
from .outbound_trust import OutboundTrustRegistry
from .pc_execution_binding import PreparedPCDispatch
from .state import VeraStateDirectory


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PreparedProviderDispatch:
    permit: AcceptedLifecyclePermit
    effect_id: str
    provider_id: str
    operation: str
    request_payload: Any
    request_digest: str
    authority_subject: str


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
    audit: OutboundExecutionAudit
    pc_execution_transport: PCExecutionTransport | None
    provider_execution_transports: Mapping[str, ProviderExecutionTransport]

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
        pc_execution_transport: PCExecutionTransport | None = None,
        provider_execution_transports: Mapping[
            str, ProviderExecutionTransport
        ] | None = None,
        coordination_bus: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> "QualifiedVeraRuntime":
        if type(state) is not VeraStateDirectory:
            raise TypeError("state must be an exact VeraStateDirectory")

        lifecycle = state.open()
        fence = lifecycle.effect_fence or state.effect_fence()
        outbound_trust = state.outbound_trust_registry()
        outbound_trust.verify_chain()
        audit = state.outbound_execution_audit()
        with lifecycle.action_lock():
            audit.repair_from_fence(fence)

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

        if pc_execution_transport is not None:
            if not isinstance(pc_execution_transport, PCExecutionTransport):
                raise TypeError(
                    "pc_execution_transport must satisfy PCExecutionTransport"
                )
            if pc_authority_verifier is None:
                raise ValueError(
                    "PC execution transport requires a trusted PC authority verifier"
                )
        provider_transports = dict(provider_execution_transports or {})
        provider_verifiers = dict(provider_authority_verifiers or {})
        for provider_id, transport in provider_transports.items():
            if type(provider_id) is not str or not provider_id:
                raise ValueError(
                    "provider execution transport keys must be non-empty strings"
                )
            if not isinstance(transport, ProviderExecutionTransport):
                raise TypeError(
                    f"provider execution transport for {provider_id!r} "
                    "does not satisfy ProviderExecutionTransport"
                )
            if transport.provider_id != provider_id:
                raise ValueError(
                    f"provider execution transport identity mismatch for "
                    f"{provider_id!r}"
                )
            if provider_id not in provider_verifiers:
                raise ValueError(
                    f"provider execution transport {provider_id!r} requires "
                    "a trusted provider authority verifier"
                )

        effects = LifecycleEffectGateway(
            lifecycle=lifecycle,
            fence=fence,
            pc_authority_verifier=pc_authority_verifier,
            provider_authority_verifiers=provider_authority_verifiers,
            outbound_trust_registry=outbound_trust,
            audit=audit,
            clock=clock,
        )
        coordination = (
            None
            if coordination_bus is None
            else LifecycleBoundCoordinationBus(
                lifecycle=lifecycle,
                bus=coordination_bus,
                fence=fence,
                audit=audit,
            )
        )
        recovery = (
            None
            if reconciliation_verifier is None
            else LifecycleEffectRecovery(
                fence=fence,
                verifier=reconciliation_verifier,
                outbound_trust_registry=outbound_trust,
                audit=audit,
            )
        )
        return cls(
            lifecycle=lifecycle,
            fence=fence,
            effects=effects,
            coordination=coordination,
            recovery=recovery,
            outbound_trust=outbound_trust,
            audit=audit,
            pc_execution_transport=pc_execution_transport,
            provider_execution_transports=provider_transports,
        )

    def accepted_permit(self) -> AcceptedLifecyclePermit:
        return self.lifecycle.accepted_action_permit()

    def cancel_reserved_effect(self, effect_id: str) -> EffectReceipt:
        """Cancel an effect proven not to have crossed the dispatch claim."""
        with self.lifecycle.action_lock():
            receipt = self.fence.read(effect_id)
            if receipt.state is not EffectState.RESERVED:
                raise ValueError(
                    "only a mechanically RESERVED pre-dispatch effect may be cancelled"
                )
            cancelled = self.fence.cancel_before_dispatch(effect_id)
            previous = self.audit.latest(effect_id)
            if previous is None:
                raise ValueError(
                    "qualified reserved effect is missing outbound audit evidence"
                )
            self.audit.append(
                effect_id=effect_id,
                effect_kind=previous.effect_kind,
                event_type="CANCELLED_PRE_DISPATCH",
                payload={
                    "request_digest": cancelled.request_digest,
                    "mechanical_permit_digest": (
                        cancelled.mechanical_permit_digest
                    ),
                    "authority_evidence_digest": (
                        cancelled.authority_evidence_digest
                    ),
                    "currentness_evidence_digest": (
                        cancelled.currentness_evidence_digest
                    ),
                },
            )
            return cancelled

    def prepare_pc_job(
        self,
        *,
        job: JobEnvelope,
        authorization: AuthorizationEnvelope,
    ) -> PreparedPCDispatch:
        validate_pc_authorization_binding(job, authorization)
        if job.project_id != self.lifecycle.project_id:
            raise ValueError("PC job project does not match qualified runtime")
        permit = self.accepted_permit()
        job_digest = job.digest()
        authorization_digest = authorization.digest()
        return PreparedPCDispatch(
            permit=permit,
            job=job,
            authorization=authorization,
            job_digest=job_digest,
            authorization_digest=authorization_digest,
            authority_subject=pc_authority_subject(
                job_digest=job_digest,
                authorization_digest=authorization_digest,
                lifecycle_permit_digest=permit.permit_digest,
            ),
        )

    def dispatch_pc_job(
        self,
        prepared: PreparedPCDispatch,
        *,
        authority_proof: PCJobAuthorityProof,
        execute: Callable[[], T],
    ) -> Any:
        if type(prepared) is not PreparedPCDispatch:
            raise TypeError("prepared must be exact PreparedPCDispatch")
        if prepared.job.digest() != prepared.job_digest:
            raise ValueError("prepared PC job changed after preparation")
        if prepared.authorization.digest() != prepared.authorization_digest:
            raise ValueError("prepared PC authorization changed after preparation")
        return self.effects.dispatch_pc_job(
            permit=prepared.permit,
            job=prepared.job,
            authorization=prepared.authorization,
            authority_proof=authority_proof,
            execute=execute,
        )

    def execute_pc_job(
        self,
        prepared: PreparedPCDispatch,
        *,
        authority_proof: PCJobAuthorityProof,
    ) -> Any:
        transport = self.pc_execution_transport
        if transport is None:
            raise ValueError(
                "qualified PC execution requires a host-injected PC execution transport"
            )
        if transport.host_id != prepared.job.host_id:
            raise ValueError(
                "PC execution transport host identity does not match job host"
            )
        return self.dispatch_pc_job(
            prepared,
            authority_proof=authority_proof,
            execute=lambda: transport.execute(
                prepared.job,
                prepared.authorization,
            ),
        )

    def prepare_provider_effect(
        self,
        *,
        effect_id: str,
        provider_id: str,
        operation: str,
        request_payload: Any,
    ) -> PreparedProviderDispatch:
        permit = self.accepted_permit()
        request_digest = self.effects.provider_request_digest(
            provider_id=provider_id,
            operation=operation,
            request_payload=request_payload,
        )
        return PreparedProviderDispatch(
            permit=permit,
            effect_id=effect_id,
            provider_id=provider_id,
            operation=operation,
            request_payload=request_payload,
            request_digest=request_digest,
            authority_subject=provider_authority_subject(
                effect_id=effect_id,
                provider_id=provider_id,
                operation=operation,
                request_digest=request_digest,
                lifecycle_permit_digest=permit.permit_digest,
            ),
        )

    def dispatch_provider_effect(
        self,
        prepared: PreparedProviderDispatch,
        *,
        authority: ProviderAuthorityEnvelope,
        execute: Callable[[], T],
    ) -> Any:
        if type(prepared) is not PreparedProviderDispatch:
            raise TypeError("prepared must be exact PreparedProviderDispatch")
        observed_digest = self.effects.provider_request_digest(
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_payload=prepared.request_payload,
        )
        if observed_digest != prepared.request_digest:
            raise ValueError("prepared provider request changed after preparation")
        return self.effects.dispatch_provider_effect(
            permit=prepared.permit,
            effect_id=prepared.effect_id,
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_payload=prepared.request_payload,
            authority=authority,
            execute=execute,
        )

    def execute_provider_effect(
        self,
        prepared: PreparedProviderDispatch,
        *,
        authority: ProviderAuthorityEnvelope,
    ) -> Any:
        transport = self.provider_execution_transports.get(
            prepared.provider_id
        )
        if transport is None:
            raise ValueError(
                "qualified provider execution requires a host-injected "
                f"transport for {prepared.provider_id!r}"
            )
        if transport.provider_id != prepared.provider_id:
            raise ValueError(
                "provider execution transport identity changed after construction"
            )
        return self.dispatch_provider_effect(
            prepared,
            authority=authority,
            execute=lambda: transport.execute(
                prepared.operation,
                prepared.request_payload,
            ),
        )

    def resume_context(self) -> dict[str, Any]:
        context = self.lifecycle.reconstruct().as_resume_context()
        context["outbound_trust"] = self.outbound_trust.context()
        context["outbound_audit"] = self.audit.context()
        integrity = self.audit.verify_fence_consistency(self.fence)
        context["outbound_effect_integrity"] = {
            "schema": "VERA_MONO_OUTBOUND_EFFECT_INTEGRITY_V1",
            "audit_head_digest": integrity.audit_head_digest,
            "fence_effect_count": integrity.fence_effect_count,
            "audited_effect_count": integrity.audited_effect_count,
            "authority_only_effect_ids": list(
                integrity.authority_only_effect_ids
            ),
            "repaired_effect_ids": list(integrity.repaired_effect_ids),
        }
        return context
