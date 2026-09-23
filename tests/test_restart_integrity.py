import sqlite3

import pytest

from vera_assurance import AtomicCurrentnessStore, EffectFenceError
from vera_core import LifecycleJournalError, NativeVeraLifecycle
from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger
from vera_recovery import NativeCheckpointError, NativeRecoveryCheckpointStore


PROJECT = "vera-mono"
IDENTITY = "vera"


def accepted_lifecycle(tmp_path):
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
    request = AdmissionRequest(
        record_id="m1",
        text="durable",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id=PROJECT,
        governed_identity_id=IDENTITY,
    )
    admitted = memory.admit(request, expected_head=memory.current_head)
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return lifecycle


def test_restart_fails_closed_on_journal_tamper(tmp_path):
    lifecycle = accepted_lifecycle(tmp_path)
    with sqlite3.connect(lifecycle.journal.path) as db:
        db.execute(
            "UPDATE events SET payload_json='{}' WHERE sequence=1"
        )
    with pytest.raises(LifecycleJournalError):
        lifecycle.reconstruct()


def test_restart_fails_closed_on_currentness_snapshot_tamper(tmp_path):
    lifecycle = accepted_lifecycle(tmp_path)
    with sqlite3.connect(lifecycle.currentness.path) as db:
        db.execute(
            "UPDATE currentness SET snapshot_digest=? WHERE subject_id=?",
            ("0" * 64, "vera-runtime"),
        )
    with pytest.raises(EffectFenceError):
        lifecycle.reconstruct()


def test_restart_fails_closed_on_recovery_checkpoint_tamper(tmp_path):
    lifecycle = accepted_lifecycle(tmp_path)
    with sqlite3.connect(lifecycle.checkpoints.path) as db:
        db.execute(
            "UPDATE checkpoints SET payload_json='{}' WHERE checkpoint_id='cp1'"
        )
    with pytest.raises(NativeCheckpointError):
        lifecycle.reconstruct()
