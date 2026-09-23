import pytest

from vera_assurance import AtomicCurrentnessStore
from vera_core import LifecycleAssuranceError, NativeVeraLifecycle
from vera_control import local_r10_source_digest
from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger
from vera_recovery import NativeRecoveryCheckpointStore


PROJECT = "vera-mono"
IDENTITY = "vera"


def admit(memory: MemoryLedger, *, record_id: str, operation_id: str, expected_head: str):
    request = AdmissionRequest(
        record_id=record_id,
        text=f"memory:{record_id}",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id=operation_id,
        project_id=PROJECT,
        governed_identity_id=IDENTITY,
    )
    return memory.admit(request, expected_head=expected_head)


def values_from_receipt(receipt):
    return {
        "project_id": receipt.project_id,
        "identity_id": receipt.identity_id,
        "runtime_id": receipt.runtime_id,
        "memory_head_digest": receipt.memory_head_digest,
        "recovery_checkpoint_digest": receipt.recovery_checkpoint_digest,
        "recovery_checkpoint_generation": receipt.recovery_checkpoint_generation,
        "control_source_digest": receipt.control_source_digest,
    }


def build_lifecycle(tmp_path):
    memory = MemoryLedger(
        tmp_path / "memory.sqlite",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    checkpoints = NativeRecoveryCheckpointStore(
        tmp_path / "recovery.sqlite",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    currentness = AtomicCurrentnessStore(tmp_path / "currentness.sqlite")
    lifecycle = NativeVeraLifecycle(
        memory=memory,
        checkpoints=checkpoints,
        currentness=currentness,
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    return memory, checkpoints, currentness, lifecycle


def test_native_lifecycle_wires_memory_checkpoint_control_currentness_assurance(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    first_memory = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    first = lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=first_memory["store_head"],
        expected_checkpoint_head=checkpoints.current_head,
        expected_currentness_generation=None,
        commitments=("preserve local authority boundaries",),
    )
    assert first.assurance_status == "PASS"
    assert first.memory_head_digest == first_memory["store_head"]
    assert first.currentness_generation == 0
    assert currentness.read("vera-runtime").snapshot_digest == first.currentness_snapshot_digest

    second_memory = admit(
        memory,
        record_id="m2",
        operation_id="op2",
        expected_head=first_memory["store_head"],
    )
    second = lifecycle.checkpoint(
        checkpoint_id="cp2",
        runtime_id="runtime-2",
        expected_memory_head=second_memory["store_head"],
        expected_checkpoint_head=checkpoints.current_head,
        expected_currentness_generation=0,
        assurance_baseline=values_from_receipt(first),
        unfinished_work=("next lifecycle frontier",),
    )
    assert second.assurance_status == "PASS"
    assert second.recovery_checkpoint_generation == 2
    assert second.currentness_generation == 1
    assert second.control_source_digest == first.control_source_digest


def test_assurance_blocks_critical_identity_drift_before_currentness_commit(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    memory_receipt = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    hostile_baseline = {
        "project_id": PROJECT,
        "identity_id": "different-identity",
        "runtime_id": "prior",
        "memory_head_digest": memory_receipt["store_head"],
        "recovery_checkpoint_digest": "a" * 64,
        "recovery_checkpoint_generation": 0,
        "control_source_digest": "b" * 64,
    }
    with pytest.raises(LifecycleAssuranceError) as exc:
        lifecycle.checkpoint(
            checkpoint_id="cp-blocked",
            runtime_id="runtime-1",
            expected_memory_head=memory_receipt["store_head"],
            expected_checkpoint_head=checkpoints.current_head,
            expected_currentness_generation=None,
            assurance_baseline=hostile_baseline,
        )
    assert exc.value.report.status == "BLOCK"
    with pytest.raises(KeyError):
        currentness.read("vera-runtime")


def test_restart_reconstructs_last_accepted_generation_without_chat_state(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    admitted = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    receipt = lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=checkpoints.current_head,
        expected_currentness_generation=None,
        commitments=("preserve exact local state",),
        unfinished_work=("resume frontier",),
    )

    reopened_memory = MemoryLedger(
        tmp_path / "memory.sqlite",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    reopened_checkpoints = NativeRecoveryCheckpointStore(
        tmp_path / "recovery.sqlite",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    reopened_currentness = AtomicCurrentnessStore(tmp_path / "currentness.sqlite")
    reopened = NativeVeraLifecycle(
        memory=reopened_memory,
        checkpoints=reopened_checkpoints,
        currentness=reopened_currentness,
        project_id=PROJECT,
        identity_id=IDENTITY,
    )

    state = reopened.reconstruct()
    assert state.status == "ACCEPTED_CURRENT"
    assert state.accepted_checkpoint_digest == receipt.recovery_checkpoint_digest
    assert state.accepted_runtime_id == "runtime-1"
    assert state.commitments == ("preserve exact local state",)
    assert state.unfinished_work == ("resume frontier",)
    assert state.as_resume_context()["resume_checkpoint_id"] == "cp1"


def test_restart_distinguishes_memory_ahead_from_accepted_currentness(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    first = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=first["store_head"],
        expected_checkpoint_head=checkpoints.current_head,
        expected_currentness_generation=None,
    )
    admit(
        memory,
        record_id="m2",
        operation_id="op2",
        expected_head=first["store_head"],
    )

    state = lifecycle.reconstruct()
    assert state.status == "MEMORY_AHEAD_OF_CURRENTNESS"
    assert state.accepted_checkpoint_id == "cp1"
    assert state.pending_checkpoint_id is None
    assert state.live_memory_head != state.accepted_memory_head_digest


def test_restart_distinguishes_interrupted_candidate_from_accepted_generation(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    first = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=first["store_head"],
        expected_checkpoint_head=checkpoints.current_head,
        expected_currentness_generation=None,
        unfinished_work=("accepted-work",),
    )
    second = admit(
        memory,
        record_id="m2",
        operation_id="op2",
        expected_head=first["store_head"],
    )
    pending = checkpoints.append(
        checkpoint_id="cp2",
        runtime_id="runtime-2",
        memory_head_digest=second["store_head"],
        control_source_digest=local_r10_source_digest(),
        expected_head=checkpoints.current_head,
        unfinished_work=("candidate-work",),
    )

    state = lifecycle.reconstruct()
    assert state.status == "INTERRUPTED_CANDIDATE"
    assert state.accepted_checkpoint_id == "cp1"
    assert state.pending_checkpoint_id == "cp2"
    assert state.latest_checkpoint_digest == pending.checkpoint_digest
    assert state.resume_checkpoint_id == "cp2"
    assert state.unfinished_work == ("candidate-work",)


def test_restart_reconciles_currentness_commit_missing_final_journal_event(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    admitted = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    checkpoint = checkpoints.append(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        memory_head_digest=admitted["store_head"],
        control_source_digest=local_r10_source_digest(),
        expected_head=checkpoints.current_head,
        commitments=("recover durable commit",),
    )
    values = {
        "project_id": PROJECT,
        "identity_id": IDENTITY,
        "runtime_id": checkpoint.runtime_id,
        "memory_head_digest": checkpoint.memory_head_digest,
        "recovery_checkpoint_digest": checkpoint.checkpoint_digest,
        "recovery_checkpoint_generation": checkpoint.generation,
        "control_source_digest": checkpoint.control_source_digest,
    }
    currentness.publish("vera-runtime", values, expected_generation=None)

    assert not lifecycle.journal.has_event("cp1", "CURRENTNESS_COMMITTED")
    state = lifecycle.reconstruct()
    assert state.status == "ACCEPTED_RECONCILED"
    assert lifecycle.journal.has_event("cp1", "RESTART_RECONCILED_COMMITTED")
    assert state.commitments == ("recover durable commit",)


def test_blocked_candidate_is_restart_visible_but_not_current(tmp_path):
    memory, checkpoints, currentness, lifecycle = build_lifecycle(tmp_path)
    memory_receipt = admit(
        memory,
        record_id="m1",
        operation_id="op1",
        expected_head=memory.current_head,
    )
    hostile_baseline = {
        "project_id": PROJECT,
        "identity_id": "different-identity",
        "runtime_id": "prior",
        "memory_head_digest": memory_receipt["store_head"],
        "recovery_checkpoint_digest": "a" * 64,
        "recovery_checkpoint_generation": 0,
        "control_source_digest": "b" * 64,
    }
    with pytest.raises(LifecycleAssuranceError):
        lifecycle.checkpoint(
            checkpoint_id="cp-blocked",
            runtime_id="runtime-1",
            expected_memory_head=memory_receipt["store_head"],
            expected_checkpoint_head=checkpoints.current_head,
            expected_currentness_generation=None,
            assurance_baseline=hostile_baseline,
            unfinished_work=("inspect-block",),
        )

    state = lifecycle.reconstruct()
    assert state.status == "BLOCKED_CANDIDATE"
    assert state.accepted_currentness_exists is False
    assert state.pending_checkpoint_id == "cp-blocked"
    assert state.unfinished_work == ("inspect-block",)
