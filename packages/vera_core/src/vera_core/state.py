from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from r8a0.trust import configure_provisioning_root
from vera_assurance import AtomicCurrentnessStore, EffectFence
from vera_memory import MemoryLedger
from vera_recovery import NativeRecoveryCheckpointStore

from .lifecycle import LifecycleReconstruction, NativeVeraLifecycle
from .lifecycle_journal import LifecycleJournal


@dataclass(frozen=True, slots=True)
class VeraStatePaths:
    root: Path
    memory: Path
    recovery: Path
    currentness: Path
    lifecycle_journal: Path
    effects: Path
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
        return NativeVeraLifecycle(
            memory=memory,
            checkpoints=checkpoints,
            currentness=currentness,
            journal=journal,
            effect_fence=effect_fence,
            project_id=self.project_id,
            identity_id=self.identity_id,
            currentness_subject_id=self.currentness_subject_id,
        )

    def effect_fence(self) -> EffectFence:
        return EffectFence(self.paths.effects)

    def reconstruct(self) -> LifecycleReconstruction:
        return self.open().reconstruct()

    def resume_context(self) -> dict:
        return self.reconstruct().as_resume_context()
