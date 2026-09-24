from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, TypeVar

from coordination_bus import CoordinationBus
from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import EffectFence, EffectReceipt, EffectState
from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope

from .action_gate import LifecycleBoundCoordinationBus, LifecycleEffectGateway
from .coordination_command_journal import CoordinationCommandJournal
from .effect_recovery import (
    EffectReconciliationVerifier,
    LifecycleEffectRecovery,
)
from .execution_adapters import (
    PCExecutionTransport,
    ProviderExecutionTransport,
    SourceMutationTransport,
)
from .lifecycle import (
    AcceptedLifecyclePermit,
    LifecycleActionDenied,
    NativeVeraLifecycle,
)
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
from .pc_execution_binding import PCExecutionBindingStore, PreparedPCDispatch
from .provider_execution_binding import (
    PreparedProviderDispatch,
    ProviderExecutionBindingStore,
    ProviderExecutionRecoveryAssessment,
)
from .state import VeraStateDirectory
from .source_mutation import (
    QualifiedSourceMutationAdapter,
    SourceMutationRecoveryAssessment,
)
from .source_mutation_binding import SourceMutationBindingStore
from .source_mutation_outcome import SourceMutationOutcomeStore
from .task_execution import (
    TaskCloseoutAssessment,
    TaskDependencyAssessment,
    TaskDelegation,
    TaskDelegationRef,
    TaskDependencyRef,
    TaskExecutionError,
    TaskExecutionLedger,
    TaskPacket,
    TaskState,
)


T = TypeVar("T")


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
    source_mutation_transports: Mapping[
        tuple[str, str], SourceMutationTransport
    ]
    pc_execution_bindings: PCExecutionBindingStore
    provider_execution_bindings: ProviderExecutionBindingStore
    source_mutation_bindings: SourceMutationBindingStore
    source_mutation_outcomes: SourceMutationOutcomeStore
    coordination_commands: CoordinationCommandJournal
    tasks: TaskExecutionLedger

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
        source_mutation_transports: Mapping[
            tuple[str, str], SourceMutationTransport
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
        pc_execution_bindings = state.pc_execution_binding_store()
        provider_execution_bindings = (
            state.provider_execution_binding_store()
        )
        source_mutation_bindings = (
            state.source_mutation_binding_store()
        )
        source_mutation_outcomes = (
            state.source_mutation_outcome_store()
        )
        coordination_commands = state.coordination_command_journal()
        tasks = state.task_execution_ledger()

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

        source_transports = dict(source_mutation_transports or {})
        for scope, transport in source_transports.items():
            if (
                not isinstance(scope, tuple)
                or len(scope) != 2
                or not all(type(item) is str and item for item in scope)
            ):
                raise TypeError(
                    "source mutation transport keys must be (repository, ref)"
                )
            if not isinstance(transport, SourceMutationTransport):
                raise TypeError(
                    f"source mutation transport for {scope!r} "
                    "does not satisfy SourceMutationTransport"
                )
            if (transport.repository, transport.ref) != scope:
                raise ValueError(
                    f"source mutation transport identity mismatch for {scope!r}"
                )
            expected_provider_id = f"source:{scope[0]}"
            if transport.provider_id != expected_provider_id:
                raise ValueError(
                    "source mutation transport provider identity must be "
                    f"{expected_provider_id!r}"
                )
            if transport.provider_id not in provider_verifiers:
                raise ValueError(
                    f"source mutation transport {scope!r} requires a trusted "
                    "provider authority verifier"
                )
            if transport.provider_id in provider_transports:
                raise ValueError(
                    "source mutation provider id is reserved from generic "
                    "provider execution transports"
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
        resolved_coordination_bus = (
            CoordinationBus(state.coordination_repository())
            if coordination_bus is None
            else coordination_bus
        )
        coordination = LifecycleBoundCoordinationBus(
            lifecycle=lifecycle,
            bus=resolved_coordination_bus,
            fence=fence,
            audit=audit,
            command_journal=coordination_commands,
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
            source_mutation_transports=source_transports,
            pc_execution_bindings=pc_execution_bindings,
            provider_execution_bindings=provider_execution_bindings,
            source_mutation_bindings=source_mutation_bindings,
            source_mutation_outcomes=source_mutation_outcomes,
            coordination_commands=coordination_commands,
            tasks=tasks,
        )

    def accepted_permit(self) -> AcceptedLifecyclePermit:
        return self.lifecycle.accepted_action_permit()

    def source_mutation_adapter(self) -> QualifiedSourceMutationAdapter:
        return QualifiedSourceMutationAdapter(
            runtime=self,
            transports=self.source_mutation_transports,
        )

    def _task_runtime_evidence_digest(self) -> str:
        lifecycle_context = self.lifecycle.reconstruct().as_resume_context()
        integrity = self.audit.verify_fence_consistency(self.fence)
        trust_head = self.outbound_trust.verify_chain()
        repository = self.coordination.bus.repository
        verify_coordination = getattr(repository, "verify_integrity", None)
        coordination_head = (
            verify_coordination()
            if callable(verify_coordination)
            else None
        )
        coordination_projection = (
            self.coordination_commands.verify_integrity()
        )
        body = {
            "schema": "VERA_MONO_TASK_RUNTIME_EVIDENCE_V1",
            "project_id": self.lifecycle.project_id,
            "identity_id": self.lifecycle.identity_id,
            "lifecycle": lifecycle_context,
            "outbound_audit_head_digest": integrity.audit_head_digest,
            "outbound_trust_head_digest": trust_head,
            "coordination_head_digest": coordination_head,
            "coordination_command_projection_digest": (
                coordination_projection
            ),
        }
        return sha256_hex(canonical_json_bytes(body))

    def start_task(
        self,
        task_id: str,
        packet: TaskPacket,
    ) -> TaskState:
        with self.tasks.action_lock():
            return self.tasks.open_task(
                task_id,
                packet,
                lifecycle_evidence_digest=self._task_runtime_evidence_digest(),
            )

    def _task_dependency_target_started(
        self,
        *,
        kind: str,
        target_id: str,
    ) -> bool:
        if kind == "EFFECT":
            if self.audit.latest(target_id) is not None:
                return True
            try:
                self.fence.read(target_id)
            except KeyError:
                pass
            else:
                return True
            if target_id.startswith("pc:"):
                return bool(
                    self.pc_execution_bindings.bindings_for_effect(
                        target_id
                    )
                )
            return False
        if kind == "COORDINATION_COMMAND":
            try:
                self.coordination_commands.read_binding(target_id)
            except KeyError:
                return False
            return True
        if kind == "PROVIDER_EFFECT":
            try:
                self.provider_execution_bindings.read(target_id)
            except KeyError:
                return False
            return True
        raise TaskExecutionError(
            f"unsupported task dependency kind: {kind!r}"
        )

    def _bind_task_dependency_unlocked(
        self,
        task_id: str,
        dependency_id: str,
        *,
        kind: str,
        target_id: str,
    ) -> TaskState:
        state = self.tasks.read(task_id)
        if state.closed:
            raise TaskExecutionError(
                "closed task cannot accept dependency"
            )
        existing = {
            item.dependency_id: item for item in state.dependencies
        }.get(dependency_id)
        if existing is not None:
            if existing.kind != kind or existing.target_id != target_id:
                raise TaskExecutionError(
                    "task dependency identity is already bound differently"
                )
            if dependency_id in set(state.cancelled_dependency_ids):
                raise TaskExecutionError(
                    "cancelled task dependency identity cannot be reused"
                )
            return state
        if self._task_dependency_target_started(
            kind=kind,
            target_id=target_id,
        ):
            raise TaskExecutionError(
                "task dependency cannot be bound after target execution "
                "or preparation has started"
            )
        return self.tasks.bind_dependency(
            task_id,
            dependency_id,
            kind=kind,
            target_id=target_id,
        )

    def bind_task_dependency(
        self,
        task_id: str,
        dependency_id: str,
        *,
        kind: str,
        target_id: str,
    ) -> TaskState:
        with self.tasks.action_lock():
            return self._bind_task_dependency_unlocked(
                task_id,
                dependency_id,
                kind=kind,
                target_id=target_id,
            )

    def _validate_task_dependency_ref(
        self,
        ref: TaskDependencyRef,
        *,
        expected_kind: str,
        expected_target_id: str,
    ) -> TaskDependencyRef:
        if type(ref) is not TaskDependencyRef:
            raise TaskExecutionError(
                "task dependency provenance must be exact TaskDependencyRef"
            )
        state = self.tasks.read(ref.task_id)
        if state.closed:
            raise TaskExecutionError(
                "task-bound outbound work cannot execute after task closeout"
            )
        active = {
            item.dependency_id: item
            for item in state.active_dependencies
        }.get(ref.dependency_id)
        if active is None:
            raise TaskExecutionError(
                "task-bound outbound work references inactive dependency"
            )
        if (
            active.kind != expected_kind
            or active.target_id != expected_target_id
            or ref.kind != active.kind
            or ref.target_id != active.target_id
            or ref.binding_event_digest != active.event_digest
        ):
            raise TaskExecutionError(
                "task dependency provenance does not match durable task binding"
            )
        return ref

    def _audit_task_dependency_matches(
        self,
        effect_id: str,
        ref: TaskDependencyRef,
    ) -> bool | None:
        authority_events = tuple(
            event
            for event in self.audit.events(effect_id)
            if event.event_type == "AUTHORITY_VERIFIED"
        )
        if not authority_events:
            return None
        if len(authority_events) != 1:
            raise TaskExecutionError(
                "outbound audit contains multiple authority events for effect"
            )
        details = authority_events[0].payload.get("authority_details")
        if not isinstance(details, Mapping):
            return False
        return details.get("task_dependency") == ref.canonical_body()

    def cancel_task_dependency(
        self,
        task_id: str,
        dependency_id: str,
        *,
        reason: str,
    ) -> TaskState:
        with self.tasks.action_lock():
            state = self.tasks.read(task_id)
            active = {
                item.dependency_id: item
                for item in state.active_dependencies
            }.get(dependency_id)
            if active is None:
                raise TaskExecutionError(
                    "task dependency is not active"
                )
            if self._task_dependency_target_started(
                kind=active.kind,
                target_id=active.target_id,
            ):
                raise TaskExecutionError(
                    "task dependency cannot be cancelled after target "
                    "execution or preparation has started"
                )
            return self.tasks.cancel_dependency(
                task_id,
                dependency_id,
                reason=reason,
            )

    def invoke_task_coordination(
        self,
        task_id: str,
        dependency_id: str,
        command: str,
        *,
        actor: Any,
        command_id: str,
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        if self.coordination is None:
            raise TaskExecutionError(
                "qualified coordination runtime is unavailable"
            )
        with self.tasks.action_lock():
            state = self.tasks.read(task_id)
            if state.closed:
                raise TaskExecutionError(
                    "closed task cannot execute coordination dependency"
                )
            bound = self._bind_task_dependency_unlocked(
                task_id,
                dependency_id,
                kind="COORDINATION_COMMAND",
                target_id=command_id,
            )
            task_dependency = bound.dependency_ref(dependency_id)
            try:
                return self.coordination.invoke(
                    command,
                    permit=self.accepted_permit(),
                    actor=actor,
                    command_id=command_id,
                    args=args,
                    kwargs=kwargs,
                    task_dependency=task_dependency,
                )
            except BaseException:
                if not self._task_dependency_target_started(
                    kind="COORDINATION_COMMAND",
                    target_id=command_id,
                ):
                    self.tasks.cancel_dependency(
                        task_id,
                        dependency_id,
                        reason=(
                            "qualified coordination failed before durable "
                            "command preparation"
                        ),
                    )
                raise

    def prepare_task_provider_effect(
        self,
        task_id: str,
        dependency_id: str,
        *,
        effect_id: str,
        provider_id: str,
        operation: str,
        request_payload: Any,
    ) -> PreparedProviderDispatch:
        with self.tasks.action_lock():
            state = self.tasks.read(task_id)
            if state.closed:
                raise TaskExecutionError(
                    "closed task cannot prepare provider dependency"
                )
            bound = self._bind_task_dependency_unlocked(
                task_id,
                dependency_id,
                kind="PROVIDER_EFFECT",
                target_id=effect_id,
            )
            task_dependency = bound.dependency_ref(dependency_id)
            try:
                return self.prepare_provider_effect(
                    effect_id=effect_id,
                    provider_id=provider_id,
                    operation=operation,
                    request_payload=request_payload,
                    task_dependency=task_dependency,
                )
            except BaseException:
                if not self._task_dependency_target_started(
                    kind="PROVIDER_EFFECT",
                    target_id=effect_id,
                ):
                    self.tasks.cancel_dependency(
                        task_id,
                        dependency_id,
                        reason=(
                            "qualified provider preparation failed before "
                            "durable provider binding"
                        ),
                    )
                raise

    def prepare_task_pc_job(
        self,
        task_id: str,
        dependency_id: str,
        *,
        job: JobEnvelope,
        authorization: AuthorizationEnvelope,
    ) -> PreparedPCDispatch:
        with self.tasks.action_lock():
            state = self.tasks.read(task_id)
            if state.closed:
                raise TaskExecutionError(
                    "closed task cannot prepare PC dependency"
                )
            bound = self._bind_task_dependency_unlocked(
                task_id,
                dependency_id,
                kind="EFFECT",
                target_id=f"pc:{job.envelope_id}",
            )
            task_dependency = bound.dependency_ref(dependency_id)
            try:
                return self.prepare_pc_job(
                    job=job,
                    authorization=authorization,
                    task_dependency=task_dependency,
                )
            except BaseException:
                if not self._task_dependency_target_started(
                    kind="EFFECT",
                    target_id=f"pc:{job.envelope_id}",
                ):
                    self.tasks.cancel_dependency(
                        task_id,
                        dependency_id,
                        reason=(
                            "qualified PC preparation failed before any "
                            "mechanical effect evidence"
                        ),
                    )
                raise

    def delegate_task_work(
        self,
        task_id: str,
        delegation_id: str,
        *,
        repository: str,
        ref: str,
        subject: str,
        assignee_ref: str,
        allowed_effects: tuple[str, ...],
        prohibited_effects: tuple[str, ...],
        return_shape: tuple[str, ...],
        evidence_refs: tuple[str, ...],
    ) -> TaskState:
        with self.tasks.action_lock():
            return self.tasks.delegate_work(
                task_id,
                delegation_id,
                repository=repository,
                ref=ref,
                subject=subject,
                assignee_ref=assignee_ref,
                allowed_effects=allowed_effects,
                prohibited_effects=prohibited_effects,
                return_shape=return_shape,
                evidence_refs=evidence_refs,
            )

    def reassign_task_delegation(
        self,
        task_id: str,
        delegation_id: str,
        reassignment_id: str,
        *,
        new_assignee_ref: str,
        evidence_refs: tuple[str, ...],
    ) -> TaskState:
        with self.tasks.action_lock():
            return self.tasks.reassign_delegation(
                task_id,
                delegation_id,
                reassignment_id,
                new_assignee_ref=new_assignee_ref,
                evidence_refs=evidence_refs,
            )

    def return_task_delegation(
        self,
        task_id: str,
        delegation_id: str,
        return_id: str,
        *,
        summary: str,
        return_values: Mapping[str, str],
        result_evidence_refs: tuple[str, ...],
    ) -> TaskState:
        with self.tasks.action_lock():
            return self.tasks.return_delegation(
                task_id,
                delegation_id,
                return_id,
                summary=summary,
                return_values=return_values,
                result_evidence_refs=result_evidence_refs,
            )

    def cancel_task_delegation(
        self,
        task_id: str,
        delegation_id: str,
        cancellation_id: str,
        *,
        reason: str,
        evidence_refs: tuple[str, ...],
    ) -> TaskState:
        with self.tasks.action_lock():
            return self.tasks.cancel_delegation(
                task_id,
                delegation_id,
                cancellation_id,
                reason=reason,
                evidence_refs=evidence_refs,
            )

    def validate_task_delegation(
        self,
        ref: TaskDelegationRef,
        *,
        actor_ref: str | None = None,
    ) -> TaskDelegationRef:
        return self.tasks.validate_delegation_ref(
            ref,
            actor_ref=actor_ref,
        )

    def assert_task_subject_mutation_allowed(
        self,
        *,
        repository: str,
        ref: str,
        subject: str,
        actor_ref: str,
        delegation_ref: TaskDelegationRef | None = None,
    ) -> TaskDelegationRef | None:
        return self.tasks.assert_subject_mutation_allowed(
            repository=repository,
            ref=ref,
            subject=subject,
            actor_ref=actor_ref,
            delegation_ref=delegation_ref,
        )

    def record_task_correction(
        self,
        task_id: str,
        correction_id: str,
        *,
        summary: str,
        obsolete_route: str,
        required_change: str,
        current_owner_ref: str,
        provenance_refs: tuple[str, ...],
    ) -> TaskState:
        with self.tasks.action_lock():
            return self.tasks.record_correction(
                task_id,
                correction_id,
                summary=summary,
                obsolete_route=obsolete_route,
                required_change=required_change,
                current_owner_ref=current_owner_ref,
                provenance_refs=provenance_refs,
            )

    def checkpoint_task(
        self,
        task_id: str,
        checkpoint_id: str,
        *,
        completed_evidence: tuple[str, ...] = (),
        blockers: tuple[str, ...] = (),
        protected_effects_still_gated: tuple[str, ...] = (),
        next_frontier: str,
        correction_ids_addressed: tuple[str, ...] = (),
        method_change: str | None = None,
        regression_guard: str | None = None,
        blocker_classification: str | None = None,
    ) -> TaskState:
        with self.tasks.action_lock():
            unresolved = tuple(
                f"{receipt.effect_id}:{receipt.state.value}"
                for receipt in self.fence.unresolved()
            )
            protected = tuple(
                dict.fromkeys(
                    (*protected_effects_still_gated, *unresolved)
                )
            )
            return self.tasks.checkpoint(
                task_id,
                checkpoint_id,
                completed_evidence=completed_evidence,
                blockers=blockers,
                protected_effects_still_gated=protected,
                next_frontier=next_frontier,
                lifecycle_evidence_digest=self._task_runtime_evidence_digest(),
                correction_ids_addressed=correction_ids_addressed,
                method_change=method_change,
                regression_guard=regression_guard,
                blocker_classification=blocker_classification,
            )

    def assess_task_dependencies(
        self,
        task_id: str,
    ) -> tuple[TaskDependencyAssessment, ...]:
        state = self.tasks.read(task_id)
        if not state.active_dependencies:
            return ()

        self.audit.verify_fence_consistency(self.fence)
        assessments: list[TaskDependencyAssessment] = []
        success_states = {
            EffectState.COMMITTED.value,
            EffectState.RECONCILED_COMMITTED.value,
        }

        for dependency in state.active_dependencies:
            ref = state.dependency_ref(dependency.dependency_id)
            if dependency.kind == "EFFECT":
                try:
                    receipt = self.fence.read(dependency.target_id)
                except KeyError:
                    receipt = None

                pc_bindings = (
                    self.pc_execution_bindings.bindings_for_effect(
                        dependency.target_id
                    )
                    if dependency.target_id.startswith("pc:")
                    else ()
                )
                if receipt is None:
                    if pc_bindings:
                        if any(
                            binding.prepared.task_dependency != ref
                            for binding in pc_bindings
                        ):
                            assessments.append(
                                TaskDependencyAssessment(
                                    dependency_id=dependency.dependency_id,
                                    kind=dependency.kind,
                                    target_id=dependency.target_id,
                                    status="PROVENANCE_MISMATCH",
                                    evidence_digest=pc_bindings[-1].binding_digest,
                                    reason=(
                                        "PC execution binding does not carry "
                                        "the exact owning task dependency"
                                    ),
                                )
                            )
                        else:
                            assessments.append(
                                TaskDependencyAssessment(
                                    dependency_id=dependency.dependency_id,
                                    kind=dependency.kind,
                                    target_id=dependency.target_id,
                                    status="PENDING",
                                    evidence_digest=pc_bindings[-1].binding_digest,
                                    reason=(
                                        "PC attempt preparation is durable but "
                                        "no mechanical effect has started"
                                    ),
                                )
                            )
                    else:
                        assessments.append(
                            TaskDependencyAssessment(
                                dependency_id=dependency.dependency_id,
                                kind=dependency.kind,
                                target_id=dependency.target_id,
                                status="MISSING",
                                evidence_digest=None,
                                reason=(
                                    "bound effect dependency has no mechanical "
                                    "or PC preparation evidence"
                                ),
                            )
                        )
                    continue

                latest = self.audit.latest(dependency.target_id)
                evidence_digest = (
                    None if latest is None else latest.event_digest
                )
                provenance_matches = self._audit_task_dependency_matches(
                    dependency.target_id,
                    ref,
                )
                if provenance_matches is not True:
                    status = "PROVENANCE_MISMATCH"
                    reason = (
                        "mechanical effect does not carry the exact owning "
                        "task dependency in qualified authority evidence"
                    )
                elif receipt.state.value in success_states:
                    status = "SATISFIED"
                    reason = (
                        "qualified task-bound effect reached a successful "
                        "terminal state"
                    )
                elif receipt.state in {
                    EffectState.EXECUTING,
                    EffectState.ATTEMPTED_UNKNOWN,
                }:
                    status = "RECOVERY_REQUIRED"
                    reason = (
                        "task-bound effect may have crossed dispatch and "
                        "requires reconciliation"
                    )
                elif receipt.state in {
                    EffectState.CANCELLED_PRE_DISPATCH,
                    EffectState.RECONCILED_NO_EFFECT,
                }:
                    status = "TERMINAL_UNSATISFIED"
                    reason = (
                        "task-bound effect terminated without the required "
                        "external effect"
                    )
                else:
                    status = "PENDING"
                    reason = (
                        "task-bound effect has not reached terminal success"
                    )
                assessments.append(
                    TaskDependencyAssessment(
                        dependency_id=dependency.dependency_id,
                        kind=dependency.kind,
                        target_id=dependency.target_id,
                        status=status,
                        evidence_digest=evidence_digest,
                        reason=reason,
                    )
                )
                continue

            if dependency.kind == "COORDINATION_COMMAND":
                if self.coordination is None:
                    assessments.append(
                        TaskDependencyAssessment(
                            dependency_id=dependency.dependency_id,
                            kind=dependency.kind,
                            target_id=dependency.target_id,
                            status="MISSING",
                            evidence_digest=None,
                            reason="qualified coordination runtime is unavailable",
                        )
                    )
                    continue
                try:
                    command = self.coordination.assess_command(
                        dependency.target_id
                    )
                except KeyError:
                    assessments.append(
                        TaskDependencyAssessment(
                            dependency_id=dependency.dependency_id,
                            kind=dependency.kind,
                            target_id=dependency.target_id,
                            status="MISSING",
                            evidence_digest=None,
                            reason=(
                                "bound coordination command has no durable "
                                "command binding"
                            ),
                        )
                    )
                    continue

                result = self.coordination_commands.read_result(
                    dependency.target_id
                )
                provenance_matches = self._audit_task_dependency_matches(
                    command.effect_id,
                    ref,
                )
                if provenance_matches is False:
                    assessments.append(
                        TaskDependencyAssessment(
                            dependency_id=dependency.dependency_id,
                            kind=dependency.kind,
                            target_id=dependency.target_id,
                            status="PROVENANCE_MISMATCH",
                            evidence_digest=(
                                None
                                if self.audit.latest(command.effect_id) is None
                                else self.audit.latest(
                                    command.effect_id
                                ).event_digest
                            ),
                            reason=(
                                "coordination effect authority evidence does "
                                "not carry the exact owning task dependency"
                            ),
                        )
                    )
                    continue
                if (
                    command.terminal
                    and command.result_recorded
                    and command.fence_state in success_states
                    and result is not None
                    and provenance_matches is True
                ):
                    status = "SATISFIED"
                    evidence_digest = result.result_record_digest
                    reason = (
                        "coordination command result and terminal effect agree"
                    )
                elif (
                    command.result_recorded
                    and provenance_matches is not True
                ):
                    status = "PROVENANCE_MISMATCH"
                    evidence_digest = (
                        None
                        if self.audit.latest(command.effect_id) is None
                        else self.audit.latest(command.effect_id).event_digest
                    )
                    reason = (
                        "coordination result exists without exact task-bound "
                        "authority provenance"
                    )
                elif command.recovery_required:
                    status = "RECOVERY_REQUIRED"
                    evidence_digest = None
                    reason = command.reason
                elif command.terminal:
                    status = "TERMINAL_UNSATISFIED"
                    evidence_digest = None
                    reason = command.reason
                else:
                    status = "PENDING"
                    evidence_digest = None
                    reason = command.reason
                assessments.append(
                    TaskDependencyAssessment(
                        dependency_id=dependency.dependency_id,
                        kind=dependency.kind,
                        target_id=dependency.target_id,
                        status=status,
                        evidence_digest=evidence_digest,
                        reason=reason,
                    )
                )
                continue

            if dependency.kind == "PROVIDER_EFFECT":
                try:
                    provider_binding = self.provider_execution_bindings.read(
                        dependency.target_id
                    )
                    provider = self.assess_provider_effect(
                        dependency.target_id
                    )
                except KeyError:
                    assessments.append(
                        TaskDependencyAssessment(
                            dependency_id=dependency.dependency_id,
                            kind=dependency.kind,
                            target_id=dependency.target_id,
                            status="MISSING",
                            evidence_digest=None,
                            reason=(
                                "bound provider effect has no durable provider "
                                "execution binding"
                            ),
                        )
                    )
                    continue

                if provider_binding.task_dependency != ref:
                    assessments.append(
                        TaskDependencyAssessment(
                            dependency_id=dependency.dependency_id,
                            kind=dependency.kind,
                            target_id=dependency.target_id,
                            status="PROVENANCE_MISMATCH",
                            evidence_digest=provider_binding.binding_digest,
                            reason=(
                                "provider execution binding does not carry "
                                "the exact owning task dependency"
                            ),
                        )
                    )
                    continue

                latest = self.audit.latest(provider.mechanical_effect_id)
                evidence_digest = (
                    None if latest is None else latest.event_digest
                )
                provenance_matches = self._audit_task_dependency_matches(
                    provider.mechanical_effect_id,
                    ref,
                )
                if (
                    provider.fence_state is not None
                    and provenance_matches is not True
                ):
                    status = "PROVENANCE_MISMATCH"
                    reason = (
                        "provider mechanical effect does not carry the exact "
                        "owning task dependency in qualified authority evidence"
                    )
                elif (
                    provider.terminal
                    and provider.fence_state in success_states
                ):
                    if provider.provider_id.startswith("source:"):
                        try:
                            source_binding = self.source_mutation_bindings.read(
                                dependency.target_id
                            )
                            source_outcome = self.source_mutation_outcomes.read(
                                dependency.target_id
                            )
                        except (KeyError, ValueError):
                            status = "RECOVERY_REQUIRED"
                            reason = (
                                "source provider effect committed but exact "
                                "source mutation outcome is missing or invalid"
                            )
                        else:
                            if (
                                source_outcome.source_binding_digest
                                != source_binding.binding_digest
                                or source_outcome.provider_binding_digest
                                != provider_binding.binding_digest
                                or source_outcome.mechanical_effect_id
                                != provider.mechanical_effect_id
                            ):
                                status = "PROVENANCE_MISMATCH"
                                reason = (
                                    "source outcome does not bind the exact "
                                    "source/provider execution evidence"
                                )
                            else:
                                status = "SATISFIED"
                                evidence_digest = (
                                    source_outcome.outcome_digest
                                )
                                reason = (
                                    "source provider effect and exact durable "
                                    "source outcome both reached success"
                                )
                    else:
                        status = "SATISFIED"
                        reason = (
                            "provider effect reached a successful terminal state"
                        )
                elif provider.recovery_required:
                    status = "RECOVERY_REQUIRED"
                    reason = provider.reason
                elif provider.terminal:
                    status = "TERMINAL_UNSATISFIED"
                    reason = provider.reason
                else:
                    status = "PENDING"
                    reason = provider.reason
                assessments.append(
                    TaskDependencyAssessment(
                        dependency_id=dependency.dependency_id,
                        kind=dependency.kind,
                        target_id=dependency.target_id,
                        status=status,
                        evidence_digest=evidence_digest,
                        reason=reason,
                    )
                )
                continue

            raise TaskExecutionError(
                f"unsupported task dependency kind: {dependency.kind!r}"
            )

        return tuple(assessments)

    def assess_task_closeout(
        self,
        task_id: str,
        *,
        surfaces: Mapping[str, str],
        additional_blockers: tuple[str, ...] = (),
    ) -> TaskCloseoutAssessment:
        state = self.tasks.read(task_id)
        reasons: list[str] = []
        surfaces_ready = True
        try:
            self.tasks._validate_surfaces(state.packet, surfaces)
        except TaskExecutionError as exc:
            surfaces_ready = False
            reasons.append(str(exc))

        reconstruction = self.lifecycle.reconstruct()
        lifecycle_status = reconstruction.status
        if lifecycle_status not in {
            "ACCEPTED_CURRENT",
            "ACCEPTED_RECONCILED",
        }:
            reasons.append(
                f"lifecycle is not accepted-current: {lifecycle_status}"
            )

        unresolved_effect_ids = tuple(
            receipt.effect_id
            for receipt in self.fence.unresolved()
        )
        if unresolved_effect_ids:
            reasons.append(
                "unresolved protected effects remain: "
                + ", ".join(unresolved_effect_ids)
            )

        coordination_recovery_ids = tuple(
            assessment.command_id
            for assessment in self.coordination.recover_commands()
            if assessment.recovery_required
        )
        if coordination_recovery_ids:
            reasons.append(
                "coordination commands require recovery: "
                + ", ".join(coordination_recovery_ids)
            )

        provider_recovery_ids = tuple(
            assessment.effect_id
            for assessment in self.recover_provider_effects()
            if assessment.recovery_required
        )
        if provider_recovery_ids:
            reasons.append(
                "provider effects require recovery: "
                + ", ".join(provider_recovery_ids)
            )

        dependency_assessments = self.assess_task_dependencies(
            task_id
        )
        unsatisfied_dependency_ids = tuple(
            assessment.dependency_id
            for assessment in dependency_assessments
            if not assessment.satisfied
        )
        if unsatisfied_dependency_ids:
            reasons.append(
                "task dependencies are not satisfied: "
                + ", ".join(
                    f"{assessment.dependency_id}({assessment.status})"
                    for assessment in dependency_assessments
                    if not assessment.satisfied
                )
            )

        active_delegation_ids = tuple(
            delegation.delegation_id
            for delegation in state.active_delegations
        )
        if active_delegation_ids:
            reasons.append(
                "task delegated subjects remain active: "
                + ", ".join(active_delegation_ids)
            )

        unresolved_correction_ids = state.unresolved_correction_ids
        if unresolved_correction_ids:
            reasons.append(
                "task corrections remain unresolved: "
                + ", ".join(unresolved_correction_ids)
            )

        blockers = tuple(additional_blockers)
        if blockers:
            reasons.append(
                "task blockers remain: " + ", ".join(blockers)
            )

        if state.closed:
            reasons.append("task is already closed")

        return TaskCloseoutAssessment(
            task_id=task_id,
            lifecycle_status=lifecycle_status,
            surfaces_ready=surfaces_ready,
            unresolved_effect_ids=unresolved_effect_ids,
            coordination_recovery_ids=coordination_recovery_ids,
            provider_recovery_ids=provider_recovery_ids,
            dependency_assessments=dependency_assessments,
            unsatisfied_dependency_ids=unsatisfied_dependency_ids,
            cancelled_dependency_ids=state.cancelled_dependency_ids,
            active_delegation_ids=active_delegation_ids,
            unresolved_correction_ids=unresolved_correction_ids,
            supplied_blockers=blockers,
            ready=not reasons,
            reasons=tuple(reasons),
        )

    def close_task(
        self,
        task_id: str,
        closeout_id: str,
        *,
        surfaces: Mapping[str, str],
        evidence_refs: tuple[str, ...],
        claim_ceiling: str,
        next_frontier: str,
        additional_blockers: tuple[str, ...] = (),
    ) -> TaskState:
        with self.tasks.action_lock():
            assessment = self.assess_task_closeout(
                task_id,
                surfaces=surfaces,
                additional_blockers=additional_blockers,
            )
            if not assessment.ready:
                raise TaskExecutionError(
                    "task closeout blocked: " + "; ".join(assessment.reasons)
                )
            missing_dependency_evidence = tuple(
                item.dependency_id
                for item in assessment.dependency_assessments
                if item.satisfied and item.evidence_digest is None
            )
            if missing_dependency_evidence:
                raise TaskExecutionError(
                    "satisfied task dependency lacks durable evidence digest: "
                    + ", ".join(missing_dependency_evidence)
                )
            state = self.tasks.read(task_id)
            binding_digests = {
                dependency.dependency_id: dependency.event_digest
                for dependency in state.dependencies
            }
            dependency_evidence_refs = tuple(
                (
                    "task-dependency:"
                    f"{item.dependency_id}:"
                    f"{binding_digests[item.dependency_id]}:"
                    f"{item.evidence_digest}"
                )
                for item in assessment.dependency_assessments
                if item.evidence_digest is not None
            )
            cancellation_evidence_refs = tuple(
                (
                    "task-dependency-cancelled:"
                    f"{item.dependency_id}:"
                    f"{binding_digests[item.dependency_id]}:"
                    f"{item.event_digest}"
                )
                for item in state.dependency_cancellations
            )
            delegation_evidence_refs = tuple(
                (
                    "task-delegation:"
                    f"{item.delegation_id}:"
                    f"{item.status}:"
                    f"{item.event_digest}"
                )
                for item in state.delegations
                if not item.active
            )
            merged_evidence = tuple(
                dict.fromkeys(
                    (
                        *evidence_refs,
                        *dependency_evidence_refs,
                        *cancellation_evidence_refs,
                        *delegation_evidence_refs,
                    )
                )
            )
            return self.tasks.close_task(
                task_id,
                closeout_id,
                surfaces=surfaces,
                evidence_refs=merged_evidence,
                blockers=(),
                claim_ceiling=claim_ceiling,
                next_frontier=next_frontier,
                lifecycle_evidence_digest=self._task_runtime_evidence_digest(),
            )

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
        task_dependency: TaskDependencyRef | None = None,
    ) -> PreparedPCDispatch:
        validate_pc_authorization_binding(job, authorization)
        if job.project_id != self.lifecycle.project_id:
            raise ValueError("PC job project does not match qualified runtime")
        if task_dependency is not None:
            self._validate_task_dependency_ref(
                task_dependency,
                expected_kind="EFFECT",
                expected_target_id=f"pc:{job.envelope_id}",
            )
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
            task_dependency=task_dependency,
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
        if prepared.task_dependency is not None:
            self._validate_task_dependency_ref(
                prepared.task_dependency,
                expected_kind="EFFECT",
                expected_target_id=f"pc:{prepared.job.envelope_id}",
            )
        return self.effects.dispatch_pc_job(
            permit=prepared.permit,
            job=prepared.job,
            authorization=prepared.authorization,
            authority_proof=authority_proof,
            execute=execute,
            task_dependency=prepared.task_dependency,
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
        task_dependency: TaskDependencyRef | None = None,
    ) -> PreparedProviderDispatch:
        if task_dependency is not None:
            self._validate_task_dependency_ref(
                task_dependency,
                expected_kind="PROVIDER_EFFECT",
                expected_target_id=effect_id,
            )
        permit = self.accepted_permit()
        request_digest = self.effects.provider_request_digest(
            provider_id=provider_id,
            operation=operation,
            request_payload=request_payload,
        )
        prepared = PreparedProviderDispatch(
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
            task_dependency=task_dependency,
        )
        self.provider_execution_bindings.bind(prepared)
        return prepared

    def rehydrate_provider_effect(
        self,
        effect_id: str,
        *,
        request_payload: Any,
    ) -> PreparedProviderDispatch:
        binding = self.provider_execution_bindings.read(effect_id)
        observed_digest = self.effects.provider_request_digest(
            provider_id=binding.provider_id,
            operation=binding.operation,
            request_payload=request_payload,
        )
        if observed_digest != binding.request_digest:
            raise ValueError(
                "rehydrated provider request payload does not match durable binding"
            )
        prepared = PreparedProviderDispatch(
            permit=binding.permit,
            effect_id=binding.effect_id,
            provider_id=binding.provider_id,
            operation=binding.operation,
            request_payload=request_payload,
            request_digest=binding.request_digest,
            authority_subject=binding.authority_subject,
            task_dependency=binding.task_dependency,
        )
        self.provider_execution_bindings.bind(prepared)
        return prepared

    def dispatch_provider_effect(
        self,
        prepared: PreparedProviderDispatch,
        *,
        authority: ProviderAuthorityEnvelope,
        execute: Callable[[], T],
    ) -> Any:
        if type(prepared) is not PreparedProviderDispatch:
            raise TypeError("prepared must be exact PreparedProviderDispatch")
        if prepared.provider_id.startswith("source:"):
            raise ValueError(
                "source mutation providers must dispatch through the "
                "qualified source mutation adapter"
            )
        observed_digest = self.effects.provider_request_digest(
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_payload=prepared.request_payload,
        )
        if observed_digest != prepared.request_digest:
            raise ValueError("prepared provider request changed after preparation")
        if prepared.task_dependency is not None:
            self._validate_task_dependency_ref(
                prepared.task_dependency,
                expected_kind="PROVIDER_EFFECT",
                expected_target_id=prepared.effect_id,
            )
        return self.effects.dispatch_provider_effect(
            permit=prepared.permit,
            effect_id=prepared.effect_id,
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_payload=prepared.request_payload,
            authority=authority,
            execute=execute,
            task_dependency=prepared.task_dependency,
        )

    def execute_provider_effect(
        self,
        prepared: PreparedProviderDispatch,
        *,
        authority: ProviderAuthorityEnvelope,
    ) -> Any:
        if prepared.provider_id.startswith("source:"):
            raise ValueError(
                "source mutation providers must execute through the "
                "qualified source mutation adapter"
            )
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
        execution_payload = deepcopy(prepared.request_payload)
        observed_digest = self.effects.provider_request_digest(
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_payload=execution_payload,
        )
        if observed_digest != prepared.request_digest:
            raise ValueError(
                "provider request changed while creating execution snapshot"
            )
        snapshotted = PreparedProviderDispatch(
            permit=prepared.permit,
            effect_id=prepared.effect_id,
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_payload=execution_payload,
            request_digest=prepared.request_digest,
            authority_subject=prepared.authority_subject,
            task_dependency=prepared.task_dependency,
        )
        return self.dispatch_provider_effect(
            snapshotted,
            authority=authority,
            execute=lambda: transport.execute(
                snapshotted.operation,
                snapshotted.request_payload,
            ),
        )

    def assess_provider_effect(
        self,
        effect_id: str,
    ) -> ProviderExecutionRecoveryAssessment:
        binding = self.provider_execution_bindings.read(effect_id)
        mechanical_effect_id = (
            f"provider:{binding.provider_id}:{binding.effect_id}"
        )
        self.audit.verify_fence_consistency(self.fence)
        try:
            receipt = self.fence.read(mechanical_effect_id)
        except KeyError:
            receipt = None

        lifecycle_current = True
        try:
            self.lifecycle.validate_action_permit(binding.permit)
        except LifecycleActionDenied:
            lifecycle_current = False

        if receipt is None:
            return ProviderExecutionRecoveryAssessment(
                effect_id=binding.effect_id,
                mechanical_effect_id=mechanical_effect_id,
                provider_id=binding.provider_id,
                operation=binding.operation,
                fence_state=None,
                lifecycle_permit_current=lifecycle_current,
                dispatch_candidate_allowed=lifecycle_current,
                recovery_required=False,
                terminal=False,
                reason=(
                    "provider request is prepared but has no mechanical "
                    "effect record"
                    if lifecycle_current
                    else "provider request is prepared under a stale lifecycle permit"
                ),
            )

        state = receipt.state
        if state is EffectState.RESERVED:
            return ProviderExecutionRecoveryAssessment(
                effect_id=binding.effect_id,
                mechanical_effect_id=mechanical_effect_id,
                provider_id=binding.provider_id,
                operation=binding.operation,
                fence_state=state.value,
                lifecycle_permit_current=lifecycle_current,
                dispatch_candidate_allowed=False,
                recovery_required=False,
                terminal=False,
                reason=(
                    "provider effect is durably reserved pre-dispatch; "
                    "cancel it rather than reusing the effect identity"
                ),
            )
        if state in {
            EffectState.EXECUTING,
            EffectState.ATTEMPTED_UNKNOWN,
        }:
            return ProviderExecutionRecoveryAssessment(
                effect_id=binding.effect_id,
                mechanical_effect_id=mechanical_effect_id,
                provider_id=binding.provider_id,
                operation=binding.operation,
                fence_state=state.value,
                lifecycle_permit_current=lifecycle_current,
                dispatch_candidate_allowed=False,
                recovery_required=True,
                terminal=False,
                reason=(
                    "provider effect may have crossed the dispatch boundary; "
                    "reconciliation is required before any replacement action"
                ),
            )
        return ProviderExecutionRecoveryAssessment(
            effect_id=binding.effect_id,
            mechanical_effect_id=mechanical_effect_id,
            provider_id=binding.provider_id,
            operation=binding.operation,
            fence_state=state.value,
            lifecycle_permit_current=lifecycle_current,
            dispatch_candidate_allowed=False,
            recovery_required=False,
            terminal=True,
            reason=(
                "provider effect identity has reached a terminal mechanical state"
            ),
        )

    def recover_provider_effects(
        self,
    ) -> tuple[ProviderExecutionRecoveryAssessment, ...]:
        return tuple(
            self.assess_provider_effect(binding.effect_id)
            for binding in self.provider_execution_bindings.all()
        )

    def recover_source_mutations(
        self,
    ) -> tuple[SourceMutationRecoveryAssessment, ...]:
        return self.source_mutation_adapter().recover_mutations()

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
        context["pc_execution_bindings"] = (
            self.pc_execution_bindings.context()
        )
        context["provider_execution_bindings"] = (
            self.provider_execution_bindings.context()
        )
        context["source_mutation_bindings"] = (
            self.source_mutation_bindings.context()
        )
        context["source_mutation_outcomes"] = (
            self.source_mutation_outcomes.context()
        )
        context["coordination"] = {
            "schema": "VERA_MONO_COORDINATION_RUNTIME_CONTEXT_V1",
            "repository_type": type(self.coordination.bus.repository).__name__,
            "persistent_native": hasattr(
                self.coordination.bus.repository,
                "verify_integrity",
            ),
        }
        context["coordination_commands"] = self.coordination_commands.context()
        context["tasks"] = self.tasks.context()
        context["task_delegation_ownership"] = [
            {
                "task_id": task.task_id,
                "delegation_id": delegation.delegation_id,
                "repository": delegation.repository,
                "ref": delegation.ref,
                "subject": delegation.subject,
                "assignee_ref": delegation.assignee_ref,
                "allowed_effects": list(delegation.allowed_effects),
                "prohibited_effects": list(
                    delegation.prohibited_effects
                ),
                "return_shape": list(delegation.return_shape),
            }
            for task in self.tasks.tasks()
            for delegation in task.active_delegations
        ]
        context["task_dependency_recovery"] = [
            {
                "task_id": task.task_id,
                "dependencies": [
                    {
                        "dependency_id": assessment.dependency_id,
                        "kind": assessment.kind,
                        "target_id": assessment.target_id,
                        "status": assessment.status,
                        "evidence_digest": assessment.evidence_digest,
                        "cancellation_allowed": (
                            assessment.cancellation_allowed
                        ),
                        "reason": assessment.reason,
                    }
                    for assessment in self.assess_task_dependencies(
                        task.task_id
                    )
                ],
            }
            for task in self.tasks.tasks()
            if not task.closed and task.dependencies
        ]
        context["coordination_command_recovery"] = [
            {
                "command_id": assessment.command_id,
                "effect_id": assessment.effect_id,
                "command": assessment.command,
                "actor_workstream": assessment.actor_workstream,
                "request_digest": assessment.request_digest,
                "result_recorded": assessment.result_recorded,
                "fence_state": assessment.fence_state,
                "lifecycle_permit_current": (
                    assessment.lifecycle_permit_current
                ),
                "retry_candidate_allowed": (
                    assessment.retry_candidate_allowed
                ),
                "pre_dispatch_cancel_allowed": (
                    assessment.pre_dispatch_cancel_allowed
                ),
                "recovery_required": assessment.recovery_required,
                "terminal": assessment.terminal,
                "reason": assessment.reason,
            }
            for assessment in self.coordination.recover_commands()
        ]
        context["source_mutation_recovery"] = [
            {
                "mutation_id": assessment.mutation_id,
                "task_id": assessment.task_id,
                "dependency_id": assessment.dependency_id,
                "repository": assessment.repository,
                "ref": assessment.ref,
                "operation": assessment.operation,
                "path": assessment.path,
                "destination_path": assessment.destination_path,
                "provider_fence_state": assessment.provider_fence_state,
                "lifecycle_permit_current": (
                    assessment.lifecycle_permit_current
                ),
                "task_open": assessment.task_open,
                "packet_current": assessment.packet_current,
                "writable_scope_current": (
                    assessment.writable_scope_current
                ),
                "delegation_current": assessment.delegation_current,
                "provider_binding_current": (
                    assessment.provider_binding_current
                ),
                "provider_authority_current": (
                    assessment.provider_authority_current
                ),
                "transport_available": assessment.transport_available,
                "outcome_current": assessment.outcome_current,
                "new_ref_head": assessment.new_ref_head,
                "content_rehydration_required": (
                    assessment.content_rehydration_required
                ),
                "dispatch_candidate_allowed": (
                    assessment.dispatch_candidate_allowed
                ),
                "recovery_required": assessment.recovery_required,
                "terminal": assessment.terminal,
                "reason": assessment.reason,
            }
            for assessment in self.recover_source_mutations()
        ]
        context["provider_execution_recovery"] = [
            {
                "effect_id": assessment.effect_id,
                "mechanical_effect_id": assessment.mechanical_effect_id,
                "provider_id": assessment.provider_id,
                "operation": assessment.operation,
                "fence_state": assessment.fence_state,
                "lifecycle_permit_current": (
                    assessment.lifecycle_permit_current
                ),
                "dispatch_candidate_allowed": (
                    assessment.dispatch_candidate_allowed
                ),
                "recovery_required": assessment.recovery_required,
                "terminal": assessment.terminal,
                "reason": assessment.reason,
            }
            for assessment in self.recover_provider_effects()
        ]
        return context
