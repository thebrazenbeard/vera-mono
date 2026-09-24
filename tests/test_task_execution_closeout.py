import sqlite3
import threading


import pytest

from vera_assurance import EffectFenceError
from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationEventDraft,
)
from vera_core import (
    OutboundActionError,
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


def test_correction_recurrence_requires_changed_method_guard_or_blocker(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-correction",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    corrected = ledger.record_correction(
        "task-correction",
        "corr-1",
        summary="The previous route repeated an already-corrected failure.",
        obsolete_route="retry the same method with a new label",
        required_change=(
            "change the controlling method or add a regression guard"
        ),
        current_owner_ref="VERA_TASK_EXECUTION_AND_CLOSEOUT_V2",
        provenance_refs=("current-user-correction", "project-owner-source"),
    )
    assert corrected.unresolved_correction_ids == ("corr-1",)

    with pytest.raises(TaskExecutionError):
        ledger.checkpoint(
            "task-correction",
            "cp-unaddressed",
            completed_evidence=("failure reproduced",),
            blockers=(),
            protected_effects_still_gated=(),
            next_frontier="do not repeat the obsolete route",
            lifecycle_evidence_digest="b" * 64,
        )

    with pytest.raises(TaskExecutionError):
        ledger.checkpoint(
            "task-correction",
            "cp-no-change",
            completed_evidence=("failure reproduced",),
            blockers=(),
            protected_effects_still_gated=(),
            next_frontier="still unresolved",
            lifecycle_evidence_digest="b" * 64,
            correction_ids_addressed=("corr-1",),
        )

    repaired = ledger.checkpoint(
        "task-correction",
        "cp-repaired",
        completed_evidence=("negative regression test added",),
        blockers=(),
        protected_effects_still_gated=(),
        next_frontier="run exact acceptance evidence",
        lifecycle_evidence_digest="c" * 64,
        correction_ids_addressed=("corr-1",),
        regression_guard=(
            "negative regression test proves the obsolete route fails closed"
        ),
    )
    assert repaired.unresolved_correction_ids == ()
    assert repaired.latest_checkpoint["correction_ids_addressed"] == [
        "corr-1"
    ]


def test_unresolved_correction_blocks_qualified_task_closeout(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-correction-closeout", packet())
    runtime.record_task_correction(
        "task-correction-closeout",
        "corr-1",
        summary="A repeated correction has not yet been repaired.",
        obsolete_route="repeat old route",
        required_change="change method",
        current_owner_ref="VERA_TASK_EXECUTION_AND_CLOSEOUT_V2",
        provenance_refs=("current-user-correction",),
    )
    assessment = runtime.assess_task_closeout(
        "task-correction-closeout",
        surfaces=surfaces(),
    )
    assert assessment.ready is False
    assert assessment.unresolved_correction_ids == ("corr-1",)
    with pytest.raises(TaskExecutionError):
        runtime.close_task(
            "task-correction-closeout",
            "close-blocked",
            surfaces=surfaces(),
            evidence_refs=("CI PASS",),
            claim_ceiling="SOURCE_ONLY",
            next_frontier="repair correction",
        )


def test_correction_lineage_subject_tamper_fails_closed(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-correction-tamper",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.record_correction(
        "task-correction-tamper",
        "corr-1",
        summary="preserve exact referent",
        obsolete_route="wrong referent",
        required_change="keep correction on original subject",
        current_owner_ref="VERA_TASK_EXECUTION_AND_CLOSEOUT_V2",
        provenance_refs=("correction-source",),
    )
    with sqlite3.connect(ledger.path) as db:
        row = db.execute(
            "SELECT payload_json FROM events WHERE event_type='TASK_CORRECTION'"
        ).fetchone()
        import json

        payload = json.loads(row[0])
        payload["subject"] = "different-subject"
        db.execute(
            "UPDATE events SET payload_json=? WHERE event_type='TASK_CORRECTION'",
            (json.dumps(payload, sort_keys=True, separators=(',', ':')),),
        )

    with pytest.raises(TaskExecutionError):
        ledger.read("task-correction-tamper")


def test_task_dependency_binding_survives_restart_and_is_exact(tmp_path):
    path = tmp_path / "tasks.sqlite"
    ledger = TaskExecutionLedger(path)
    opened = ledger.open_task(
        "task-dependency",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    assert opened.dependencies == ()

    bound = ledger.bind_dependency(
        "task-dependency",
        "dep-effect-1",
        kind="EFFECT",
        target_id="provider:example:effect-1",
    )
    assert len(bound.dependencies) == 1
    dependency = bound.dependencies[0]
    assert dependency.dependency_id == "dep-effect-1"
    assert dependency.kind == "EFFECT"
    assert dependency.target_id == "provider:example:effect-1"
    assert len(dependency.event_digest) == 64

    reopened = TaskExecutionLedger(path).read("task-dependency")
    assert reopened.dependencies == bound.dependencies
    replayed = ledger.bind_dependency(
        "task-dependency",
        "dep-effect-1",
        kind="EFFECT",
        target_id="provider:example:effect-1",
    )
    assert replayed.dependencies == bound.dependencies

    with pytest.raises(TaskExecutionError):
        ledger.bind_dependency(
            "task-dependency",
            "dep-effect-1",
            kind="EFFECT",
            target_id="provider:example:effect-2",
        )
    with pytest.raises(TaskExecutionError):
        ledger.bind_dependency(
            "task-dependency",
            "dep-effect-2",
            kind="EFFECT",
            target_id="provider:example:effect-1",
        )
    with pytest.raises(TaskExecutionError):
        ledger.bind_dependency(
            "task-dependency",
            "dep-invalid",
            kind="UNKNOWN",
            target_id="x",
        )


def test_task_dependency_subject_tamper_fails_closed(tmp_path):
    path = tmp_path / "tasks.sqlite"
    ledger = TaskExecutionLedger(path)
    ledger.open_task(
        "task-dependency-tamper",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.bind_dependency(
        "task-dependency-tamper",
        "dep-1",
        kind="COORDINATION_COMMAND",
        target_id="coordination:command-1",
    )

    with sqlite3.connect(path) as db:
        row = db.execute(
            """
            SELECT payload_json FROM events
            WHERE event_type='TASK_DEPENDENCY'
            """
        ).fetchone()
        import json

        payload = json.loads(row[0])
        payload["subject"] = "different-subject"
        db.execute(
            """
            UPDATE events SET payload_json=?
            WHERE event_type='TASK_DEPENDENCY'
            """,
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

    with pytest.raises(TaskExecutionError):
        TaskExecutionLedger(path).read("task-dependency-tamper")


def test_task_dependency_blocks_closeout_until_coordination_command_succeeds(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-coordination-dependency", packet())
    runtime.bind_task_dependency(
        "task-coordination-dependency",
        "dep-coordination",
        kind="COORDINATION_COMMAND",
        target_id="task-coordination-command",
    )

    before = runtime.assess_task_closeout(
        "task-coordination-dependency",
        surfaces=surfaces(),
    )
    assert before.ready is False
    assert before.unsatisfied_dependency_ids == ("dep-coordination",)
    assert before.dependency_assessments[0].status == "MISSING"

    runtime.invoke_task_coordination(
        "task-coordination-dependency",
        "dep-coordination",
        "coordination_post",
        actor=actor(),
        command_id="task-coordination-command",
        args=(draft(),),
    )

    after = runtime.assess_task_closeout(
        "task-coordination-dependency",
        surfaces=surfaces(),
    )
    assert after.ready is True
    assert after.unsatisfied_dependency_ids == ()
    assert after.dependency_assessments[0].status == "SATISFIED"
    assert after.dependency_assessments[0].evidence_digest is not None

    closed = runtime.close_task(
        "task-coordination-dependency",
        "close-dependency",
        surfaces=surfaces(),
        evidence_refs=("coordination dependency committed",),
        claim_ceiling="SOURCE_AND_LOCAL_EFFECT_EVIDENCE_ONLY",
        next_frontier="NONE",
    )
    assert closed.closed is True
    assert any(
        ref.startswith("task-dependency:dep-coordination:")
        for ref in closed.closeout.evidence_refs
    )


def test_task_effect_dependency_cancelled_pre_dispatch_is_terminal_unsatisfied(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-effect-dependency", packet())
    effect_id = "task:required-effect"
    runtime.bind_task_dependency(
        "task-effect-dependency",
        "dep-effect",
        kind="EFFECT",
        target_id=effect_id,
    )

    permit = runtime.accepted_permit()
    runtime.audit.append(
        effect_id=effect_id,
        effect_kind="TEST/REQUIRED",
        event_type="AUTHORITY_VERIFIED",
        payload={
            "request_digest": "1" * 64,
            "mechanical_permit_digest": "2" * 64,
            "lifecycle_permit": {
                **permit.canonical_body(),
                "permit_digest": permit.permit_digest,
            },
            "authority_evidence_digest": "3" * 64,
            "authority_details": {"kind": "TEST"},
        },
    )
    reserved = runtime.fence.reserve(
        effect_id=effect_id,
        request_digest="1" * 64,
        mechanical_permit_digest="2" * 64,
        authority_evidence_digest="3" * 64,
        currentness_evidence_digest=permit.permit_digest,
    )
    runtime.audit.append(
        effect_id=effect_id,
        effect_kind="TEST/REQUIRED",
        event_type="RESERVED",
        payload={
            "request_digest": reserved.request_digest,
            "mechanical_permit_digest": reserved.mechanical_permit_digest,
            "authority_evidence_digest": reserved.authority_evidence_digest,
            "currentness_evidence_digest": reserved.currentness_evidence_digest,
        },
    )
    runtime.cancel_reserved_effect(effect_id)

    assessment = runtime.assess_task_closeout(
        "task-effect-dependency",
        surfaces=surfaces(),
    )
    assert assessment.ready is False
    assert assessment.unsatisfied_dependency_ids == ("dep-effect",)
    dependency = assessment.dependency_assessments[0]
    assert dependency.status == "TERMINAL_UNSATISFIED"
    assert dependency.evidence_digest is not None


def test_task_scoped_coordination_path_binds_and_satisfies_dependency(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-auto-coordination", packet())

    result = runtime.invoke_task_coordination(
        "task-auto-coordination",
        "dep-auto-coordination",
        "coordination_post",
        actor=actor(),
        command_id="task-auto-command",
        args=(draft(),),
    )
    assert result.fence_receipt.state.value == "COMMITTED"

    task = runtime.tasks.read("task-auto-coordination")
    assert len(task.dependencies) == 1
    assert task.dependencies[0].kind == "COORDINATION_COMMAND"
    assert task.dependencies[0].target_id == "task-auto-command"

    assessment = runtime.assess_task_closeout(
        "task-auto-coordination",
        surfaces=surfaces(),
    )
    assert assessment.ready is True
    assert assessment.dependency_assessments[0].status == "SATISFIED"
    resume = runtime.resume_context()
    recovered = resume["task_dependency_recovery"]
    assert len(recovered) == 1
    assert recovered[0]["task_id"] == "task-auto-coordination"
    assert recovered[0]["dependencies"][0]["status"] == "SATISFIED"

    # Exact wrapper replay reaches the underlying command fence rather than
    # failing because the task dependency record itself was duplicated.
    with pytest.raises(EffectFenceError):
        runtime.invoke_task_coordination(
            "task-auto-coordination",
            "dep-auto-coordination",
            "coordination_post",
            actor=actor(),
            command_id="task-auto-command",
            args=(draft(),),
        )
    assert len(runtime.tasks.read("task-auto-coordination").dependencies) == 1


def test_task_dependency_target_has_one_durable_task_owner(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-owner-a",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.open_task(
        "task-owner-b",
        packet(),
        lifecycle_evidence_digest="b" * 64,
    )
    ledger.bind_dependency(
        "task-owner-a",
        "dep-owned",
        kind="EFFECT",
        target_id="effect:single-owner",
    )

    with pytest.raises(TaskExecutionError):
        ledger.bind_dependency(
            "task-owner-b",
            "dep-laundered",
            kind="EFFECT",
            target_id="effect:single-owner",
        )

    context = ledger.context()
    owners = [
        item
        for item in context["dependency_owners"]
        if item["kind"] == "EFFECT"
        and item["target_id"] == "effect:single-owner"
    ]
    assert len(owners) == 1
    assert owners[0]["task_id"] == "task-owner-a"
    assert owners[0]["dependency_id"] == "dep-owned"


def test_task_closeout_serializes_against_task_scoped_mutation(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-lock", packet())
    peer = QualifiedVeraRuntime.from_state_directory(state)

    started = threading.Event()
    finished = threading.Event()
    outcomes = []

    def close_from_peer():
        started.set()
        try:
            outcomes.append(
                peer.close_task(
                    "task-lock",
                    "close-lock",
                    surfaces=surfaces(),
                    evidence_refs=("serialized closeout",),
                    claim_ceiling="SOURCE_ONLY",
                    next_frontier="NONE",
                )
            )
        finally:
            finished.set()

    with runtime.tasks.action_lock():
        thread = threading.Thread(target=close_from_peer)
        thread.start()
        assert started.wait(timeout=1.0)
        assert finished.wait(timeout=0.1) is False

    assert finished.wait(timeout=2.0)
    thread.join(timeout=1.0)
    assert len(outcomes) == 1
    assert outcomes[0].closed is True


def test_qualified_task_dependency_rejects_post_hoc_coordination_claim(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.coordination.invoke(
        "coordination_post",
        permit=runtime.accepted_permit(),
        actor=actor(),
        command_id="already-executed-command",
        args=(draft(),),
    )
    runtime.start_task("task-post-hoc-coordination", packet())

    with pytest.raises(TaskExecutionError):
        runtime.bind_task_dependency(
            "task-post-hoc-coordination",
            "dep-post-hoc",
            kind="COORDINATION_COMMAND",
            target_id="already-executed-command",
        )
    assert runtime.tasks.read(
        "task-post-hoc-coordination"
    ).dependencies == ()


def test_qualified_task_dependency_rejects_post_hoc_provider_preparation(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.prepare_provider_effect(
        effect_id="already-prepared-provider",
        provider_id="unconfigured-provider",
        operation="WRITE",
        request_payload={"value": 1},
    )
    runtime.start_task("task-post-hoc-provider", packet())

    with pytest.raises(TaskExecutionError):
        runtime.bind_task_dependency(
            "task-post-hoc-provider",
            "dep-post-hoc-provider",
            kind="PROVIDER_EFFECT",
            target_id="already-prepared-provider",
        )
    assert runtime.tasks.read(
        "task-post-hoc-provider"
    ).dependencies == ()


def test_task_dependency_can_cancel_only_before_target_start_and_closeout_carries_evidence(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-cancel-dependency", packet())
    runtime.bind_task_dependency(
        "task-cancel-dependency",
        "dep-cancel",
        kind="EFFECT",
        target_id="effect:not-started",
    )

    cancelled = runtime.cancel_task_dependency(
        "task-cancel-dependency",
        "dep-cancel",
        reason="request was invalid before any dispatch preparation",
    )
    assert cancelled.active_dependencies == ()
    assert cancelled.cancelled_dependency_ids == ("dep-cancel",)

    assessment = runtime.assess_task_closeout(
        "task-cancel-dependency",
        surfaces=surfaces(),
    )
    assert assessment.ready is True
    assert assessment.dependency_assessments == ()
    assert assessment.cancelled_dependency_ids == ("dep-cancel",)

    closed = runtime.close_task(
        "task-cancel-dependency",
        "close-cancelled-dependency",
        surfaces=surfaces(),
        evidence_refs=("validation corrected",),
        claim_ceiling="SOURCE_ONLY",
        next_frontier="NONE",
    )
    assert any(
        ref.startswith("task-dependency-cancelled:dep-cancel:")
        for ref in closed.closeout.evidence_refs
    )


def test_task_scoped_coordination_auto_cancels_dependency_on_preparation_failure(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-auto-cancel", packet())

    with pytest.raises(OutboundActionError):
        runtime.invoke_task_coordination(
            "task-auto-cancel",
            "dep-invalid-command",
            "not_a_coordination_command",
            actor=actor(),
            command_id="never-bound-command",
        )

    task = runtime.tasks.read("task-auto-cancel")
    assert task.active_dependencies == ()
    assert task.cancelled_dependency_ids == ("dep-invalid-command",)
    with pytest.raises(KeyError):
        runtime.coordination_commands.read_binding("never-bound-command")


def test_task_dependency_cannot_cancel_after_target_started(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-no-post-start-cancel", packet())
    runtime.invoke_task_coordination(
        "task-no-post-start-cancel",
        "dep-started",
        "coordination_post",
        actor=actor(),
        command_id="started-command",
        args=(draft(),),
    )

    with pytest.raises(TaskExecutionError):
        runtime.cancel_task_dependency(
            "task-no-post-start-cancel",
            "dep-started",
            reason="attempt to erase executed dependency",
        )
    assert runtime.tasks.read(
        "task-no-post-start-cancel"
    ).cancelled_dependency_ids == ()


def test_restart_marks_only_missing_dependency_as_safe_to_cancel(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-cancel-restart", packet())
    runtime.bind_task_dependency(
        "task-cancel-restart",
        "dep-missing",
        kind="EFFECT",
        target_id="effect:not-started-on-restart",
    )
    runtime.prepare_task_provider_effect(
        "task-cancel-restart",
        "dep-pending-provider",
        effect_id="provider-pending-restart",
        provider_id="unconfigured-provider",
        operation="WRITE",
        request_payload={"value": 1},
    )

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    recovered = {
        item["dependency_id"]: item
        for group in restarted.resume_context()["task_dependency_recovery"]
        if group["task_id"] == "task-cancel-restart"
        for item in group["dependencies"]
    }
    assert recovered["dep-missing"]["status"] == "MISSING"
    assert recovered["dep-missing"]["cancellation_allowed"] is True
    assert recovered["dep-pending-provider"]["status"] == "PENDING"
    assert recovered["dep-pending-provider"]["cancellation_allowed"] is False


def test_task_scoped_coordination_is_bidirectionally_bound_in_outbound_audit(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-audit-provenance", packet())

    runtime.invoke_task_coordination(
        "task-audit-provenance",
        "dep-audit-command",
        "coordination_post",
        actor=actor(),
        command_id="task-audit-command",
        args=(draft(),),
    )

    dependency = runtime.tasks.read(
        "task-audit-provenance"
    ).dependency_ref("dep-audit-command")
    events = runtime.audit.events("coordination:task-audit-command")
    authority = events[0]
    assert authority.event_type == "AUTHORITY_VERIFIED"
    assert (
        authority.payload["authority_details"]["task_dependency"]
        == dependency.canonical_body()
    )


def test_task_provider_binding_persists_exact_task_provenance_across_restart(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-provider-provenance", packet())

    prepared = runtime.prepare_task_provider_effect(
        "task-provider-provenance",
        "dep-provider-provenance",
        effect_id="provider-provenance",
        provider_id="example-provider",
        operation="WRITE",
        request_payload={"value": 7},
    )
    assert prepared.task_dependency is not None
    assert prepared.task_dependency.task_id == "task-provider-provenance"
    assert prepared.task_dependency.dependency_id == "dep-provider-provenance"

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    rebound = restarted.rehydrate_provider_effect(
        "provider-provenance",
        request_payload={"value": 7},
    )
    assert rebound.task_dependency == prepared.task_dependency
    assert (
        restarted.provider_execution_bindings.read(
            "provider-provenance"
        ).task_dependency
        == prepared.task_dependency
    )


def test_task_dependency_rejects_effect_executed_outside_task_provenance(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    runtime.start_task("task-provenance-launder", packet())
    runtime.bind_task_dependency(
        "task-provenance-launder",
        "dep-command-launder",
        kind="COORDINATION_COMMAND",
        target_id="laundered-command",
    )

    # Same command target executes through the qualified runtime, but not
    # through the task-scoped path, so its audit lacks the owning task ref.
    runtime.coordination.invoke(
        "coordination_post",
        permit=runtime.accepted_permit(),
        actor=actor(),
        command_id="laundered-command",
        args=(draft(),),
    )

    assessment = runtime.assess_task_closeout(
        "task-provenance-launder",
        surfaces=surfaces(),
    )
    assert assessment.ready is False
    dependency = assessment.dependency_assessments[0]
    assert dependency.status == "PROVENANCE_MISMATCH"
    assert dependency.satisfied is False
    assert dependency.cancellation_allowed is False
