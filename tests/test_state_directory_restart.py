from vera_core import VeraStateDirectory
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"


def test_state_directory_reopens_complete_lifecycle_without_conversation(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "vera-state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    memory = lifecycle.memory
    request = AdmissionRequest(
        record_id="m1",
        text="durable state",
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
    receipt = lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
        commitments=("keep durable continuity",),
        unfinished_work=("continue after restart",),
    )

    assert state.paths.memory.is_file()
    assert state.paths.recovery.is_file()
    assert state.paths.currentness.is_file()
    assert state.paths.lifecycle_journal.is_file()

    context = VeraStateDirectory(
        tmp_path / "vera-state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    ).resume_context()
    assert context["status"] == "ACCEPTED_CURRENT"
    assert context["accepted_checkpoint_digest"] == receipt.recovery_checkpoint_digest
    assert context["accepted_runtime_id"] == "runtime-1"
    assert context["commitments"] == ["keep durable continuity"]
    assert context["unfinished_work"] == ["continue after restart"]


def test_state_directory_does_not_provision_trust_or_authority(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "vera-state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    state.open()
    assert not state.paths.trust.exists()
