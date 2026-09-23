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

from .lifecycle_journal import LifecycleJournal


class LifecycleAssuranceError(ValueError):
    def __init__(self, report: DriftReport):
        self.report = report
        super().__init__(
            f"native lifecycle assurance blocked currentness publication: {report.status}"
        )


class LifecycleReconstructionError(ValueError):
    pass


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
    lifecycle_journal_head: str
    receipt_digest: str
    claim_ceiling: str


@dataclass(frozen=True, slots=True)
class LifecycleReconstruction:
    status: str
    project_id: str
    identity_id: str
    live_memory_head: str
    current_control_source_digest: str
    currentness_generation: int | None
    currentness_snapshot_digest: str | None
    accepted_checkpoint_id: str | None
    accepted_checkpoint_digest: str | None
    accepted_runtime_id: str | None
    accepted_memory_head_digest: str | None
    latest_checkpoint_id: str | None
    latest_checkpoint_digest: str | None
    latest_checkpoint_generation: int | None
    pending_checkpoint_id: str | None
    resume_checkpoint_id: str | None
    commitments: tuple[str, ...]
    unfinished_work: tuple[str, ...]
    lifecycle_journal_head: str
    claim_ceiling: str

    @property
    def accepted_currentness_exists(self) -> bool:
        return self.accepted_checkpoint_digest is not None

    def as_resume_context(self) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_RESTART_CONTEXT_V1",
            "status": self.status,
            "project_id": self.project_id,
            "identity_id": self.identity_id,
            "accepted_runtime_id": self.accepted_runtime_id,
            "accepted_checkpoint_id": self.accepted_checkpoint_id,
            "accepted_checkpoint_digest": self.accepted_checkpoint_digest,
            "live_memory_head": self.live_memory_head,
            "accepted_memory_head_digest": self.accepted_memory_head_digest,
            "pending_checkpoint_id": self.pending_checkpoint_id,
            "resume_checkpoint_id": self.resume_checkpoint_id,
            "commitments": list(self.commitments),
            "unfinished_work": list(self.unfinished_work),
            "currentness_generation": self.currentness_generation,
            "currentness_snapshot_digest": self.currentness_snapshot_digest,
            "current_control_source_digest": self.current_control_source_digest,
            "lifecycle_journal_head": self.lifecycle_journal_head,
            "claim_ceiling": self.claim_ceiling,
        }


class NativeVeraLifecycle:
    """Wire memory -> recovery checkpoint -> control/currentness -> assurance.

    The digest-chained lifecycle journal makes transition boundaries durable.
    Currentness is committed only after internal deterministic assurance accepts
    the candidate. Restart reconstruction treats currentness as the accepted
    state, recovery checkpoints as transition evidence, and journal events as the
    explanation of how far a candidate progressed.
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
        journal: LifecycleJournal | None = None,
    ):
        if memory.project_id != project_id or checkpoints.project_id != project_id:
            raise ValueError("lifecycle project_id does not match component stores")
        if memory.identity_id != identity_id or checkpoints.identity_id != identity_id:
            raise ValueError("lifecycle identity_id does not match component stores")
        if type(currentness_subject_id) is not str or not currentness_subject_id:
            raise ValueError(
                "currentness_subject_id must be a non-empty exact string"
            )
        self.memory = memory
        self.checkpoints = checkpoints
        self.currentness = currentness
        self.project_id = project_id
        self.identity_id = identity_id
        self.currentness_subject_id = currentness_subject_id
        self.journal = journal or LifecycleJournal(
            checkpoints.path.with_name("lifecycle-journal.sqlite")
        )

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
        self.journal.verify_chain()
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
        self.journal.append(
            transition_id=checkpoint_id,
            event_type="CANDIDATE_PREPARED",
            payload={
                "checkpoint_digest": recovery.checkpoint_digest,
                "checkpoint_generation": recovery.generation,
                "candidate_digest": candidate.digest,
                "expected_currentness_generation": expected_currentness_generation,
                "memory_head_digest": observed_memory_head,
                "control_source_digest": control_digest,
            },
        )

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
            self.journal.append(
                transition_id=checkpoint_id,
                event_type="ASSURANCE_BLOCKED",
                payload={
                    "candidate_digest": candidate.digest,
                    "baseline_digest": report.baseline_digest,
                    "candidate_assurance_digest": report.candidate_digest,
                    "finding_codes": [finding.code for finding in report.findings],
                },
            )
            raise LifecycleAssuranceError(report)

        self.journal.append(
            transition_id=checkpoint_id,
            event_type="ASSURANCE_PASSED",
            payload={
                "candidate_digest": candidate.digest,
                "baseline_digest": report.baseline_digest,
                "candidate_assurance_digest": report.candidate_digest,
                "assurance_status": report.status,
            },
        )

        current = self.currentness.publish(
            self.currentness_subject_id,
            candidate_values,
            expected_generation=expected_currentness_generation,
        )
        commit_event = self.journal.append(
            transition_id=checkpoint_id,
            event_type="CURRENTNESS_COMMITTED",
            payload={
                "candidate_digest": candidate.digest,
                "currentness_generation": current.generation,
                "currentness_snapshot_digest": current.snapshot_digest,
                "currentness_payload_digest": current.payload_digest,
            },
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
            "lifecycle_journal_head": commit_event.event_digest,
            "claim_ceiling": (
                "LOCAL_MONOREPO_LIFECYCLE_INVARIANT_PASS_"
                "NOT_INDEPENDENT_REVIEW_NOT_EFFECT_AUTHORITY"
            ),
        }
        return NativeLifecycleReceipt(
            **receipt_body,
            receipt_digest=sha256_hex(canonical_json_bytes(receipt_body)),
        )

    def reconstruct(self, *, reconcile_journal: bool = True) -> LifecycleReconstruction:
        self.journal.verify_chain()
        live_memory_head = self.memory.current_head
        control_digest = local_r10_source_digest()
        latest = self.checkpoints.latest()

        try:
            current = self.currentness.read(self.currentness_subject_id)
        except KeyError:
            current = None

        if current is None:
            if latest is None:
                return self._reconstruction(
                    status="EMPTY",
                    live_memory_head=live_memory_head,
                    control_digest=control_digest,
                    current=None,
                    accepted=None,
                    latest=None,
                    pending=None,
                    resume=None,
                )
            latest_event = self.journal.latest(latest.checkpoint_id)
            status = (
                "BLOCKED_CANDIDATE"
                if latest_event is not None
                and latest_event.event_type == "ASSURANCE_BLOCKED"
                else "INTERRUPTED_CANDIDATE"
            )
            return self._reconstruction(
                status=status,
                live_memory_head=live_memory_head,
                control_digest=control_digest,
                current=None,
                accepted=None,
                latest=latest,
                pending=latest,
                resume=latest,
            )

        payload = self.currentness.read_payload(self.currentness_subject_id)
        if not isinstance(payload, Mapping):
            raise LifecycleReconstructionError(
                "accepted currentness payload must be an object"
            )
        required = {
            "project_id",
            "identity_id",
            "runtime_id",
            "memory_head_digest",
            "recovery_checkpoint_digest",
            "recovery_checkpoint_generation",
            "control_source_digest",
        }
        if set(payload) != required:
            raise LifecycleReconstructionError(
                "accepted currentness payload field set mismatch"
            )
        if (
            payload["project_id"] != self.project_id
            or payload["identity_id"] != self.identity_id
        ):
            raise LifecycleReconstructionError(
                "accepted currentness project or identity mismatch"
            )

        try:
            accepted = self.checkpoints.read_digest(
                str(payload["recovery_checkpoint_digest"])
            )
        except KeyError as exc:
            raise LifecycleReconstructionError(
                "accepted currentness references a missing recovery checkpoint"
            ) from exc

        expected_values = self._candidate_values(accepted)
        if dict(payload) != expected_values:
            raise LifecycleReconstructionError(
                "accepted currentness does not match its recovery checkpoint"
            )
        if int(payload["recovery_checkpoint_generation"]) != accepted.generation:
            raise LifecycleReconstructionError(
                "accepted recovery checkpoint generation mismatch"
            )

        reconciled = False
        committed_in_journal = self.journal.has_event(
            accepted.checkpoint_id,
            "CURRENTNESS_COMMITTED",
        ) or self.journal.has_event(
            accepted.checkpoint_id,
            "RESTART_RECONCILED_COMMITTED",
        )
        if not committed_in_journal and reconcile_journal:
            candidate = Snapshot(
                self.currentness_subject_id,
                expected_values,
            )
            self.journal.append(
                transition_id=accepted.checkpoint_id,
                event_type="RESTART_RECONCILED_COMMITTED",
                payload={
                    "candidate_digest": candidate.digest,
                    "currentness_generation": current.generation,
                    "currentness_snapshot_digest": current.snapshot_digest,
                    "currentness_payload_digest": current.payload_digest,
                },
            )
            reconciled = True

        if latest is not None and latest.generation > accepted.generation:
            event = self.journal.latest(latest.checkpoint_id)
            status = (
                "BLOCKED_CANDIDATE"
                if event is not None and event.event_type == "ASSURANCE_BLOCKED"
                else "INTERRUPTED_CANDIDATE"
            )
            return self._reconstruction(
                status=status,
                live_memory_head=live_memory_head,
                control_digest=control_digest,
                current=current,
                accepted=accepted,
                latest=latest,
                pending=latest,
                resume=latest,
            )

        if accepted.control_source_digest != control_digest:
            status = "CONTROL_SOURCE_DRIFT"
        elif live_memory_head != accepted.memory_head_digest:
            status = "MEMORY_AHEAD_OF_CURRENTNESS"
        elif reconciled:
            status = "ACCEPTED_RECONCILED"
        else:
            status = "ACCEPTED_CURRENT"

        return self._reconstruction(
            status=status,
            live_memory_head=live_memory_head,
            control_digest=control_digest,
            current=current,
            accepted=accepted,
            latest=latest,
            pending=None,
            resume=accepted,
        )

    def _reconstruction(
        self,
        *,
        status: str,
        live_memory_head: str,
        control_digest: str,
        current: Any,
        accepted: NativeRecoveryCheckpoint | None,
        latest: NativeRecoveryCheckpoint | None,
        pending: NativeRecoveryCheckpoint | None,
        resume: NativeRecoveryCheckpoint | None,
    ) -> LifecycleReconstruction:
        return LifecycleReconstruction(
            status=status,
            project_id=self.project_id,
            identity_id=self.identity_id,
            live_memory_head=live_memory_head,
            current_control_source_digest=control_digest,
            currentness_generation=None if current is None else current.generation,
            currentness_snapshot_digest=(
                None if current is None else current.snapshot_digest
            ),
            accepted_checkpoint_id=(
                None if accepted is None else accepted.checkpoint_id
            ),
            accepted_checkpoint_digest=(
                None if accepted is None else accepted.checkpoint_digest
            ),
            accepted_runtime_id=None if accepted is None else accepted.runtime_id,
            accepted_memory_head_digest=(
                None if accepted is None else accepted.memory_head_digest
            ),
            latest_checkpoint_id=None if latest is None else latest.checkpoint_id,
            latest_checkpoint_digest=(
                None if latest is None else latest.checkpoint_digest
            ),
            latest_checkpoint_generation=(
                None if latest is None else latest.generation
            ),
            pending_checkpoint_id=(
                None if pending is None else pending.checkpoint_id
            ),
            resume_checkpoint_id=None if resume is None else resume.checkpoint_id,
            commitments=() if resume is None else resume.commitments,
            unfinished_work=() if resume is None else resume.unfinished_work,
            lifecycle_journal_head=self.journal.head,
            claim_ceiling=(
                "DETERMINISTIC_LOCAL_RESTART_RECONSTRUCTION_"
                "NOT_INDEPENDENT_REVIEW_NOT_EFFECT_AUTHORITY"
            ),
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
