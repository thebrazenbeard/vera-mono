from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import (
    AtomicCurrentnessStore,
    DriftPolicy,
    DriftReport,
    Snapshot,
    compare_snapshots,
)
from vera_control.local_profile import local_r10_source_digest
from vera_memory import MemoryLedger
from vera_recovery import NativeRecoveryCheckpoint, NativeRecoveryCheckpointStore


class LifecycleAssuranceError(ValueError):
    def __init__(self, report: DriftReport):
        self.report = report
        super().__init__(f"native lifecycle assurance blocked currentness publication: {report.status}")


@dataclass(frozen=True, slots=True)
class NativeLifecycleReceipt:
    schema: str
    project_id: str
    identity_id: str
    runtime_id: str
    memory_head_digest: str
    recovery_checkpoint_id: str
    recovery_checkpoint_digest: str
    recovery_checkpoint_generation: int
    control_source_digest: str
    currentness_subject_id: str
    currentness_generation: int
    currentness_snapshot_digest: str
    assurance_status: str
    assurance_baseline_digest: str
    assurance_candidate_digest: str
    receipt_digest: str
    claim_ceiling: str


class NativeVeraLifecycle:
    """Wire memory -> recovery checkpoint -> control/currentness -> assurance.

    Currentness is committed only after an internal deterministic assurance gate
    accepts the candidate. This is a local source/runtime invariant check, not
    independent review and not protected-effect authority.
    """

    def __init__(
        self,
        *,
        memory: MemoryLedger,
        checkpoints: NativeRecoveryCheckpointStore,
        currentness: AtomicCurrentnessStore,
        project_id: str,
        identity_id: str,
        currentness_subject_id: str = "vera-runtime",
    ):
        if memory.project_id != project_id or checkpoints.project_id != project_id:
            raise ValueError("lifecycle project_id does not match component stores")
        if memory.identity_id != identity_id or checkpoints.identity_id != identity_id:
            raise ValueError("lifecycle identity_id does not match component stores")
        if type(currentness_subject_id) is not str or not currentness_subject_id:
            raise ValueError("currentness_subject_id must be a non-empty exact string")
        self.memory = memory
        self.checkpoints = checkpoints
        self.currentness = currentness
        self.project_id = project_id
        self.identity_id = identity_id
        self.currentness_subject_id = currentness_subject_id

    @staticmethod
    def default_policy() -> DriftPolicy:
        return DriftPolicy(
            critical_fields=(
                "project_id",
                "identity_id",
                "control_source_digest",
            ),
            mutable_fields=(
                "runtime_id",
                "memory_head_digest",
                "recovery_checkpoint_digest",
                "recovery_checkpoint_generation",
            ),
            required_fields=(
                "project_id",
                "identity_id",
                "runtime_id",
                "memory_head_digest",
                "recovery_checkpoint_digest",
                "recovery_checkpoint_generation",
                "control_source_digest",
            ),
        )

    def checkpoint(
        self,
        *,
        checkpoint_id: str,
        runtime_id: str,
        expected_memory_head: str,
        expected_checkpoint_head: str,
        expected_currentness_generation: int | None,
        commitments: tuple[str, ...] = (),
        unfinished_work: tuple[str, ...] = (),
        assurance_baseline: Mapping[str, Any] | None = None,
        assurance_policy: DriftPolicy | None = None,
        created_at: str | None = None,
    ) -> NativeLifecycleReceipt:
        observed_memory_head = self.memory.current_head
        if observed_memory_head != expected_memory_head:
            raise ValueError("memory head changed before lifecycle checkpoint")

        control_digest = local_r10_source_digest()
        recovery = self.checkpoints.append(
            checkpoint_id=checkpoint_id,
            runtime_id=runtime_id,
            memory_head_digest=observed_memory_head,
            control_source_digest=control_digest,
            expected_head=expected_checkpoint_head,
            commitments=commitments,
            unfinished_work=unfinished_work,
            created_at=created_at,
        )

        candidate_values = self._candidate_values(recovery)
        candidate = Snapshot(self.currentness_subject_id, candidate_values)
        baseline_values = (
            candidate_values
            if assurance_baseline is None
            else dict(assurance_baseline)
        )
        baseline = Snapshot(self.currentness_subject_id, baseline_values)
        report = compare_snapshots(
            baseline,
            candidate,
            assurance_policy or self.default_policy(),
        )
        if report.status == "BLOCK":
            raise LifecycleAssuranceError(report)

        current = self.currentness.publish(
            self.currentness_subject_id,
            candidate_values,
            expected_generation=expected_currentness_generation,
        )

        receipt_body = {
            "schema": "VERA_MONO_NATIVE_LIFECYCLE_RECEIPT_V1",
            "project_id": self.project_id,
            "identity_id": self.identity_id,
            "runtime_id": runtime_id,
            "memory_head_digest": observed_memory_head,
            "recovery_checkpoint_id": recovery.checkpoint_id,
            "recovery_checkpoint_digest": recovery.checkpoint_digest,
            "recovery_checkpoint_generation": recovery.generation,
            "control_source_digest": control_digest,
            "currentness_subject_id": self.currentness_subject_id,
            "currentness_generation": current.generation,
            "currentness_snapshot_digest": current.snapshot_digest,
            "assurance_status": report.status,
            "assurance_baseline_digest": report.baseline_digest,
            "assurance_candidate_digest": report.candidate_digest,
            "claim_ceiling": (
                "LOCAL_MONOREPO_LIFECYCLE_INVARIANT_PASS_"
                "NOT_INDEPENDENT_REVIEW_NOT_EFFECT_AUTHORITY"
            ),
        }
        return NativeLifecycleReceipt(
            **receipt_body,
            receipt_digest=sha256_hex(canonical_json_bytes(receipt_body)),
        )

    def _candidate_values(
        self,
        recovery: NativeRecoveryCheckpoint,
    ) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "identity_id": self.identity_id,
            "runtime_id": recovery.runtime_id,
            "memory_head_digest": recovery.memory_head_digest,
            "recovery_checkpoint_digest": recovery.checkpoint_digest,
            "recovery_checkpoint_generation": recovery.generation,
            "control_source_digest": recovery.control_source_digest,
        }
