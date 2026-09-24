import sqlite3

import pytest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationEventDraft,
)
from vera_core import (
    TaskExecutionError,
    TaskExecutionLedger,
    TaskPacket,
    QualifiedVeraRuntime,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"


def packet():
    return TaskPacket(
        purpose="Build the next native Vera lifecycle frontier.",
        subject="thebrazenbeard/vera-mono@exact-head",
        completion_state="Required code, regression tests, and docs are verified.",
        evidence_requirements=(
            "exact Git head",
            "hosted CI result",
        ),
        writable_scope=("vera-mono/main",),
        non_targets=("provider deployment", "Project installation"),
        forbidden_shortcuts_or_effects=(
            "do not delete failing tests",
            "do not infer deployment from source",
        ),
        priority_order=("correctness", "evidence", "reversibility", "speed"),
        unknowns=("external provider state is not part of this task",),
        return_shape=(
            "exact head",
            "changed artifacts",
            "tests/readbacks",
            "blockers",
            "claim ceiling",
            "next frontier",
        ),
        relevant_surfaces=(
            "source",
            "build/package",
            "install/registration",
            "docs/rules",
            "workspace/coordination",
        ),
    )


def surfaces():
    return {
        "source": "changed-and-verified",
        "build/package": "verified-current",
        "install/registration": "out-of-scope",
        "docs/rules": "changed-and-verified",
        "workspace/coordination": "verified-current",
    }


def accepted_state(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m1",
            text="task closeout state",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op1",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def actor():
    return ActorContext("workstream/memory", ALL_PERMISSIONS)


def draft():
    return CoordinationEventDraft(
        thread_key="task-closeout",
        source_branch="workstream/memory",
        target_branch="workstream/integration",
        event_type="STATUS",
        status="IN_PROGRESS",
        objective="Exercise task closeout recovery gate",
        summary="coordination effect for closeout gate",
    )


def test_task_ledger_checkpoint_and_closeout_survive_restart(tmp_path):
    path = tmp_path / "tasks.sqlite"
    ledger = TaskExecutionLedger(path)
    opened = ledger.open_task(
        "task-1",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    assert opened.closed is False

    checkpointed = ledger.checkpoint(
        "task-1",
        "cp-1",
        completed_evidence=("main head readback",),
        blockers=("CI still running",),
        protected_effects_still_gated=(),
        next_frontier="wait for exact CI readback",
        lifecycle_evidence_digest="b" * 64,
    )
    assert checkpointed.latest_checkpoint["blockers"] == ["CI still running"]
    assert checkpointed.packet.subject == packet().subject

    with pytest.raises(TaskExecutionError):
        ledger.close_task(
            "task-1",
            "close-pending",
            surfaces={
                **surfaces(),
                "docs/rules": "pending",
            },
            evidence_refs=("CI run 1",),
            blockers=(),
            claim_ceiling="SOURCE_ONLY",
            next_frontier="NONE",
            lifecycle_evidence_digest="c" * 64,
        )

    closed = ledger.close_task(
        "task-1",
        "close-1",
        surfaces=surfaces(),
        evidence_refs=("main@abc123", "CI run 1: PASS"),
        blockers=(),
        claim_ceiling="SOURCE_AND_CI_ONLY_NOT_DEPLOYMENT",
        next_frontier="NONE",
        lifecycle_evidence_digest="c" * 64,
    )
    assert closed.closed is True
    assert closed.closeout.surfaces["install/registration"] == "out-of-scope"

    reopened = TaskExecutionLedger(path).read("task-1")
    assert reopened.closed is True
    assert reopened.packet.packet_digest == packet().packet_digest
    assert TaskExecutionLedger(path).verify_chain()


def test_qualified_runtime_task_closeout_is_surface_separated(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-runtime", packet())
    runtime.checkpoint_task(
        "task-runtime",
        "cp-1",
        completed_evidence=("source changes committed",),
        blockers=(),
        next_frontier="run hosted CI",
    )

    assessment = runtime.assess_task_closeout(
        "task-runtime",
        surfaces=surfaces(),
    )
    assert assessment.ready is True

    closed = runtime.close_task(
        "task-runtime",
        "close-1",
        surfaces=surfaces(),
        evidence_refs=("main@exact", "hosted CI PASS"),
        claim_ceiling="SOURCE_AND_CI_ONLY_NOT_INSTALL_OR_RUNTIME",
        next_frontier="NONE",
    )
    assert closed.closed is True
    assert closed.closeout.surfaces["source"] == "changed-and-verified"
    assert (
        closed.closeout.surfaces["install/registration"]
        == "out-of-scope"
    )
    assert runtime.resume_context()["tasks"]["closed_task_ids"] == [
        "task-runtime"
    ]


def test_task_closeout_blocks_unresolved_effect_even_with_green_surfaces(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-blocked-effect", packet())
    permit = runtime.accepted_permit()
    effect_id = "provider:test:task-unresolved"
    kind = "PROVIDER/test/WRITE"
    request_digest = "1" * 64
    mechanical_digest = "2" * 64
    authority_digest = "3" * 64
    runtime.audit.append(
        effect_id=effect_id,
        effect_kind=kind,
        event_type="AUTHORITY_VERIFIED",
        payload={
            "request_digest": request_digest,
            "mechanical_permit_digest": mechanical_digest,
            "lifecycle_permit": {
                **permit.canonical_body(),
                "permit_digest": permit.permit_digest,
            },
            "authority_evidence_digest": authority_digest,
            "authority_details": {"kind": "TEST"},
        },
    )
    receipt = runtime.fence.reserve(
        effect_id=effect_id,
        request_digest=request_digest,
        mechanical_permit_digest=mechanical_digest,
        authority_evidence_digest=authority_digest,
        currentness_evidence_digest=permit.permit_digest,
    )
    runtime.audit.append(
        effect_id=effect_id,
        effect_kind=kind,
        event_type="RESERVED",
        payload={
            "request_digest": receipt.request_digest,
            "mechanical_permit_digest": receipt.mechanical_permit_digest,
            "authority_evidence_digest": receipt.authority_evidence_digest,
            "currentness_evidence_digest": receipt.currentness_evidence_digest,
        },
    )

    assessment = runtime.assess_task_closeout(
        "task-blocked-effect",
        surfaces=surfaces(),
    )
    assert assessment.ready is False
    assert effect_id in assessment.unresolved_effect_ids
    with pytest.raises(TaskExecutionError):
        runtime.close_task(
            "task-blocked-effect",
            "close-blocked",
            surfaces=surfaces(),
            evidence_refs=("CI PASS",),
            claim_ceiling="SOURCE_ONLY",
            next_frontier="reconcile effect",
        )


def test_task_closeout_blocks_coordination_recovery_gap(tmp_path, monkeypatch):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-coordination-gap", packet())

    def lose_result(*args, **kwargs):
        raise RuntimeError("result journal unavailable after commit")

    monkeypatch.setattr(
        runtime.coordination_commands,
        "record_result",
        lose_result,
    )
    with pytest.raises(RuntimeError):
        runtime.coordination.invoke(
            "coordination_post",
            permit=runtime.accepted_permit(),
            actor=actor(),
            command_id="task-coord-gap",
            args=(draft(),),
        )

    assessment = runtime.assess_task_closeout(
        "task-coordination-gap",
        surfaces=surfaces(),
    )
    assert assessment.ready is False
    assert assessment.coordination_recovery_ids == ("task-coord-gap",)


def test_task_journal_tamper_fails_closed(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-tamper",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.checkpoint(
        "task-tamper",
        "cp-1",
        completed_evidence=("evidence",),
        blockers=(),
        protected_effects_still_gated=(),
        next_frontier="continue",
        lifecycle_evidence_digest="b" * 64,
    )
    with sqlite3.connect(ledger.path) as db:
        db.execute(
            "UPDATE events SET payload_json='{}' WHERE sequence=2"
        )
    with pytest.raises(TaskExecutionError):
        ledger.verify_chain()
