import pytest

from vera_core import (
    QualifiedVeraRuntime,
    TaskExecutionError,
    TaskExecutionLedger,
    TaskPacket,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"


def packet(subject="thebrazenbeard/vera-mono@exact-head"):
    return TaskPacket(
        purpose="Coordinate exact delegated work without ownership collision.",
        subject=subject,
        completion_state="Delegated work is returned or explicitly cancelled.",
        evidence_requirements=("exact head", "delegation return evidence"),
        writable_scope=("vera-mono/main",),
        non_targets=("deployment",),
        forbidden_shortcuts_or_effects=(
            "do not mutate an actively delegated subject independently",
        ),
        priority_order=("ownership", "evidence", "correctness"),
        unknowns=(),
        return_shape=("return evidence", "next frontier"),
        relevant_surfaces=("source", "workspace/coordination"),
    )


def surfaces():
    return {
        "source": "changed-and-verified",
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
            text="delegation ownership state",
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


def delegate(runtime, task_id, delegation_id="d1", assignee="worker/a"):
    return runtime.delegate_task_work(
        task_id,
        delegation_id,
        repository="thebrazenbeard/vera-mono",
        ref="main@abc123",
        subject="packages/vera_core/src/vera_core/delegated.py",
        assignee_ref=assignee,
        allowed_effects=("edit delegated.py", "add focused tests"),
        prohibited_effects=("merge", "deploy", "change credentials"),
        return_shape=("exact head", "changed files", "test evidence"),
        evidence_refs=("bus:delegation-request-1",),
    )


def test_delegated_subject_has_one_active_owner_across_tasks(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    runtime.start_task("task-b", packet("task-b"))

    delegated = delegate(runtime, "task-a")
    active = delegated.active_delegations
    assert len(active) == 1
    assert active[0].assignee_ref == "worker/a"

    with pytest.raises(TaskExecutionError):
        delegate(runtime, "task-b", delegation_id="d2", assignee="worker/b")


def test_reassignment_changes_owner_without_releasing_subject(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    runtime.start_task("task-b", packet("task-b"))
    delegate(runtime, "task-a")

    reassigned = runtime.reassign_task_delegation(
        "task-a",
        "d1",
        "reassign-1",
        new_assignee_ref="worker/b",
        evidence_refs=("bus:reassignment-1",),
    )
    current = reassigned.delegation("d1")
    assert current.active is True
    assert current.assignee_ref == "worker/b"
    assert "bus:reassignment-1" in current.evidence_refs

    with pytest.raises(TaskExecutionError):
        delegate(runtime, "task-b", delegation_id="d2", assignee="worker/c")


def test_return_releases_subject_and_closeout_carries_delegation_evidence(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    runtime.start_task("task-b", packet("task-b"))
    delegate(runtime, "task-a")

    returned = runtime.return_task_delegation(
        "task-a",
        "d1",
        "return-1",
        summary="Worker returned the exact delegated subject.",
        return_values={
            "exact head": "abc123",
            "changed files": "packages/vera_core/src/vera_core/delegated.py",
            "test evidence": "CI:PASS",
        },
        result_evidence_refs=("bus:return-1", "main@abc123"),
    )
    delegation = returned.delegation("d1")
    assert delegation.status == "RETURNED"
    assert returned.active_delegations == ()

    # Once returned, another task may own the exact same scope.
    delegated_b = delegate(runtime, "task-b", delegation_id="d2", assignee="worker/c")
    assert delegated_b.delegation("d2").active is True

    closed = runtime.close_task(
        "task-a",
        "close-1",
        surfaces=surfaces(),
        evidence_refs=("main@abc123", "CI:PASS"),
        claim_ceiling="SOURCE_AND_COORDINATION_ONLY",
        next_frontier="NONE",
    )
    assert closed.closed is True
    assert any(
        ref.startswith("task-delegation:d1:RETURNED:")
        for ref in closed.closeout.evidence_refs
    )


def test_active_delegation_blocks_direct_and_qualified_closeout(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-direct",
        packet("task-direct"),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.delegate_work(
        "task-direct",
        "d1",
        repository="thebrazenbeard/vera-mono",
        ref="main@abc123",
        subject="subject/a",
        assignee_ref="worker/a",
        allowed_effects=("edit",),
        prohibited_effects=("merge",),
        return_shape=("evidence",),
        evidence_refs=("delegation:evidence",),
    )
    with pytest.raises(TaskExecutionError):
        ledger.close_task(
            "task-direct",
            "close-1",
            surfaces=surfaces(),
            evidence_refs=("CI:PASS",),
            blockers=(),
            claim_ceiling="SOURCE_ONLY",
            next_frontier="NONE",
            lifecycle_evidence_digest="b" * 64,
        )

    state = accepted_state(tmp_path / "qualified")
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-qualified", packet("task-qualified"))
    delegate(runtime, "task-qualified")
    assessment = runtime.assess_task_closeout(
        "task-qualified",
        surfaces=surfaces(),
    )
    assert assessment.ready is False
    assert assessment.active_delegation_ids == ("d1",)
    with pytest.raises(TaskExecutionError):
        runtime.close_task(
            "task-qualified",
            "close-1",
            surfaces=surfaces(),
            evidence_refs=("CI:PASS",),
            claim_ceiling="SOURCE_ONLY",
            next_frontier="wait for delegated return",
        )


def test_cancelled_delegation_releases_scope_but_preserves_terminal_evidence(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    runtime.start_task("task-b", packet("task-b"))
    delegate(runtime, "task-a")

    cancelled = runtime.cancel_task_delegation(
        "task-a",
        "d1",
        "cancel-1",
        reason="Patrick cancelled the delegated work before return.",
        evidence_refs=("bus:cancel-1",),
    )
    delegation = cancelled.delegation("d1")
    assert delegation.status == "CANCELLED"
    assert delegation.terminal_summary.startswith("Patrick cancelled")
    assert delegation.terminal_evidence_refs == ("bus:cancel-1",)

    delegated_b = delegate(runtime, "task-b", delegation_id="d2", assignee="worker/b")
    assert delegated_b.delegation("d2").active is True


def test_restart_context_restores_active_delegation_owner(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    delegate(runtime, "task-a")

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    context = restarted.resume_context()
    assert context["task_delegation_ownership"] == [
        {
            "task_id": "task-a",
            "delegation_id": "d1",
            "repository": "thebrazenbeard/vera-mono",
            "ref": "main@abc123",
            "subject": "packages/vera_core/src/vera_core/delegated.py",
            "assignee_ref": "worker/a",
            "allowed_effects": ["edit delegated.py", "add focused tests"],
            "prohibited_effects": ["merge", "deploy", "change credentials"],
            "return_shape": ["exact head", "changed files", "test evidence"],
        }
    ]


def test_delegation_owner_reference_invalidates_on_reassignment_and_return(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    delegated = delegate(runtime, "task-a")
    original_ref = delegated.delegation_ref("d1")

    assert runtime.validate_task_delegation(
        original_ref,
        actor_ref="worker/a",
    ) == original_ref
    with pytest.raises(TaskExecutionError):
        runtime.validate_task_delegation(
            original_ref,
            actor_ref="worker/b",
        )

    reassigned = runtime.reassign_task_delegation(
        "task-a",
        "d1",
        "reassign-1",
        new_assignee_ref="worker/b",
        evidence_refs=("bus:reassign-owner",),
    )
    current_ref = reassigned.delegation_ref("d1")
    assert current_ref.assignee_ref == "worker/b"
    assert current_ref.binding_event_digest != original_ref.binding_event_digest

    with pytest.raises(TaskExecutionError):
        runtime.validate_task_delegation(original_ref)
    assert runtime.validate_task_delegation(
        current_ref,
        actor_ref="worker/b",
    ) == current_ref

    runtime.return_task_delegation(
        "task-a",
        "d1",
        "return-owner",
        summary="delegated scope returned",
        return_values={
            "exact head": "abc123",
            "changed files": "packages/vera_core/src/vera_core/delegated.py",
            "test evidence": "CI:PASS",
        },
        result_evidence_refs=("bus:return-owner",),
    )
    with pytest.raises(TaskExecutionError):
        runtime.validate_task_delegation(current_ref)


def test_delegation_policy_rejects_conflicting_allowed_and_prohibited_effect(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    with pytest.raises(TaskExecutionError):
        runtime.delegate_task_work(
            "task-a",
            "d-conflict",
            repository="thebrazenbeard/vera-mono",
            ref="main@abc123",
            subject="subject/conflict",
            assignee_ref="worker/a",
            allowed_effects=("merge",),
            prohibited_effects=("merge",),
            return_shape=("evidence",),
            evidence_refs=("bus:delegation",),
        )


def test_delegation_return_must_exactly_satisfy_declared_return_shape(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-a", packet("task-a"))
    delegate(runtime, "task-a")

    with pytest.raises(TaskExecutionError):
        runtime.return_task_delegation(
            "task-a",
            "d1",
            "return-bad",
            summary="incomplete worker return",
            return_values={
                "exact head": "abc123",
                "changed files": "delegated.py",
            },
            result_evidence_refs=("bus:return-bad",),
        )

    current = runtime.tasks.read("task-a").delegation("d1")
    assert current.active is True
