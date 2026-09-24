from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from coordination_bus import SQLiteCoordinationRepository
from r8a0.trust import configure_provisioning_root
from vera_assurance import AtomicCurrentnessStore, EffectFence
from vera_memory import MemoryLedger
from vera_recovery import NativeRecoveryCheckpointStore

from .coordination_command_journal import CoordinationCommandJournal
from .lifecycle import LifecycleReconstruction, NativeVeraLifecycle
from .lifecycle_journal import LifecycleJournal
from .installation_verification import InstallationVerificationStore
from .outbound_audit import OutboundExecutionAudit
from .outbound_trust import OutboundTrustRegistry
from .pc_execution_binding import PCExecutionBindingStore
from .provider_execution_binding import ProviderExecutionBindingStore
from .route_verification import RouteVerificationStore
from .runtime_consumption import RuntimeConsumptionVerificationStore
from .source_mutation_binding import SourceMutationBindingStore
from .source_mutation_outcome import SourceMutationOutcomeStore
from .source_verification import SourceVerificationStore
from .task_execution import TaskExecutionLedger


@dataclass(frozen=True, slots=True)
class VeraStatePaths:
    root: Path
    memory: Path
    recovery: Path
    currentness: Path
    lifecycle_journal: Path
    effects: Path
    outbound_audit: Path
    outbound_trust: Path
    pc_execution_bindings: Path
    provider_execution_bindings: Path
    source_mutation_bindings: Path
    source_mutation_outcomes: Path
    source_verifications: Path
    installation_verifications: Path
    route_verifications: Path
    runtime_consumption_verifications: Path
    coordination: Path
    coordination_commands: Path
    tasks: Path
    trust: Path


class VeraStateDirectory:
    """Open the complete persistent local Vera lifecycle from one state root.

    The directory contains local runtime state only. It does not create trust
    keys, grant authority, install a control profile, or perform protected
    effects.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        project_id: str,
        identity_id: str,
        currentness_subject_id: str = "vera-runtime",
    ):
        candidate = Path(root).expanduser().resolve()
        if type(project_id) is not str or not project_id:
            raise ValueError("project_id must be a non-empty exact string")
        if type(identity_id) is not str or not identity_id:
            raise ValueError("identity_id must be a non-empty exact string")
        if type(currentness_subject_id) is not str or not currentness_subject_id:
            raise ValueError(
                "currentness_subject_id must be a non-empty exact string"
            )
        self.paths = VeraStatePaths(
            root=candidate,
            memory=candidate / "memory" / "memory.sqlite",
            recovery=candidate / "recovery" / "checkpoints.sqlite",
            currentness=candidate / "control" / "currentness.sqlite",
            lifecycle_journal=candidate / "lifecycle" / "journal.sqlite",
            effects=candidate / "effects" / "effects.sqlite",
            outbound_audit=candidate / "effects" / "audit.sqlite",
            outbound_trust=candidate / "trust" / "outbound.sqlite",
            pc_execution_bindings=(
                candidate / "pc" / "execution-bindings.sqlite"
            ),
            provider_execution_bindings=(
                candidate / "provider" / "execution-bindings.sqlite"
            ),
            source_mutation_bindings=(
                candidate / "source" / "mutation-bindings.sqlite"
            ),
            source_mutation_outcomes=(
                candidate / "source" / "mutation-outcomes.sqlite"
            ),
            source_verifications=(
                candidate / "source" / "verification.sqlite"
            ),
            installation_verifications=(
                candidate / "install" / "verification.sqlite"
            ),
            route_verifications=(
                candidate / "route" / "verification.sqlite"
            ),
            runtime_consumption_verifications=(
                candidate / "runtime" / "consumption-verification.sqlite"
            ),
            coordination=candidate / "coordination" / "events.sqlite",
            coordination_commands=(
                candidate / "coordination" / "commands.sqlite"
            ),
            tasks=candidate / "tasks" / "tasks.sqlite",
            trust=candidate / "recovery" / "trust",
        )
        self.project_id = project_id
        self.identity_id = identity_id
        self.currentness_subject_id = currentness_subject_id

    def open(self) -> NativeVeraLifecycle:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        configure_provisioning_root(self.paths.root)
        memory = MemoryLedger(
            self.paths.memory,
            project_id=self.project_id,
            identity_id=self.identity_id,
        )
        checkpoints = NativeRecoveryCheckpointStore(
            self.paths.recovery,
            project_id=self.project_id,
            identity_id=self.identity_id,
        )
        currentness = AtomicCurrentnessStore(self.paths.currentness)
        journal = LifecycleJournal(self.paths.lifecycle_journal)
        effect_fence = EffectFence(self.paths.effects)
        effect_audit = OutboundExecutionAudit(self.paths.outbound_audit)
        lifecycle = NativeVeraLifecycle(
            memory=memory,
            checkpoints=checkpoints,
            currentness=currentness,
            journal=journal,
            effect_fence=effect_fence,
            effect_audit=effect_audit,
            project_id=self.project_id,
            identity_id=self.identity_id,
            currentness_subject_id=self.currentness_subject_id,
        )
        with lifecycle.action_lock():
            effect_audit.repair_from_fence(effect_fence)
        return lifecycle

    def effect_fence(self) -> EffectFence:
        return EffectFence(self.paths.effects)

    def outbound_execution_audit(self) -> OutboundExecutionAudit:
        return OutboundExecutionAudit(self.paths.outbound_audit)

    def outbound_trust_registry(self) -> OutboundTrustRegistry:
        return OutboundTrustRegistry(self.paths.outbound_trust)

    def pc_execution_binding_store(self) -> PCExecutionBindingStore:
        return PCExecutionBindingStore(self.paths.pc_execution_bindings)

    def provider_execution_binding_store(
        self,
    ) -> ProviderExecutionBindingStore:
        return ProviderExecutionBindingStore(
            self.paths.provider_execution_bindings
        )

    def source_mutation_binding_store(
        self,
    ) -> SourceMutationBindingStore:
        return SourceMutationBindingStore(
            self.paths.source_mutation_bindings
        )

    def source_mutation_outcome_store(
        self,
    ) -> SourceMutationOutcomeStore:
        return SourceMutationOutcomeStore(
            self.paths.source_mutation_outcomes
        )

    def source_verification_store(
        self,
    ) -> SourceVerificationStore:
        return SourceVerificationStore(
            self.paths.source_verifications
        )

    def installation_verification_store(
        self,
    ) -> InstallationVerificationStore:
        return InstallationVerificationStore(
            self.paths.installation_verifications
        )

    def route_verification_store(
        self,
    ) -> RouteVerificationStore:
        return RouteVerificationStore(self.paths.route_verifications)

    def runtime_consumption_verification_store(
        self,
    ) -> RuntimeConsumptionVerificationStore:
        return RuntimeConsumptionVerificationStore(
            self.paths.runtime_consumption_verifications
        )

    def coordination_repository(self) -> SQLiteCoordinationRepository:
        return SQLiteCoordinationRepository(self.paths.coordination)

    def coordination_command_journal(self) -> CoordinationCommandJournal:
        return CoordinationCommandJournal(self.paths.coordination_commands)

    def task_execution_ledger(self) -> TaskExecutionLedger:
        return TaskExecutionLedger(self.paths.tasks)

    def reconstruct(self) -> LifecycleReconstruction:
        return self.open().reconstruct()

    def resume_context(self) -> dict:
        lifecycle = self.open()
        context = lifecycle.reconstruct().as_resume_context()
        context["outbound_trust"] = self.outbound_trust_registry().context()
        audit = self.outbound_execution_audit()
        fence = lifecycle.effect_fence or self.effect_fence()
        with lifecycle.action_lock():
            integrity = audit.repair_from_fence(fence)
        context["outbound_audit"] = audit.context()
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
            self.pc_execution_binding_store().context()
        )
        context["provider_execution_bindings"] = (
            self.provider_execution_binding_store().context()
        )
        context["source_mutation_bindings"] = (
            self.source_mutation_binding_store().context()
        )
        context["source_mutation_outcomes"] = (
            self.source_mutation_outcome_store().context()
        )
        context["source_verifications"] = (
            self.source_verification_store().context()
        )
        context["installation_verifications"] = (
            self.installation_verification_store().context()
        )
        context["route_verifications"] = (
            self.route_verification_store().context()
        )
        context["runtime_consumption_verifications"] = (
            self.runtime_consumption_verification_store().context()
        )
        context["coordination"] = self.coordination_repository().context()
        context["coordination_commands"] = (
            self.coordination_command_journal().context()
        )
        context["tasks"] = self.task_execution_ledger().context()
        return context
