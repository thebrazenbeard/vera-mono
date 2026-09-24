import pytest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationEventDraft,
)
from vera_assurance import EffectState
from vera_core import QualifiedVeraRuntime, VeraStateDirectory
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"


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
            text="qualified coordination state",
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


def draft(summary="coordination survives restart"):
    return CoordinationEventDraft(
        thread_key="qualified-coordination",
        source_branch="workstream/memory",
        target_branch="workstream/integration",
        event_type="STATUS",
        status="IN_PROGRESS",
        objective="Exercise durable coordination recovery",
        summary=summary,
    )


def test_coordination_command_result_survives_restart_without_replay(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    permit = runtime.accepted_permit()

    result = runtime.coordination.invoke(
        "coordination_post",
        permit=permit,
        actor=actor(),
        command_id="coord-1",
        args=(draft(),),
    )
    assert result.fence_receipt.state is EffectState.COMMITTED
    assert result.value.receipt.database_write_confirmed is True
    recorded = runtime.coordination_commands.read_result("coord-1")
    assert recorded is not None
    assert recorded.result_digest == result.result_digest

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    assessment = restarted.coordination.assess_command("coord-1")
    assert assessment.terminal is True
    assert assessment.recovery_required is False
    assert assessment.retry_candidate_allowed is False
    assert assessment.result_recorded is True
    assert assessment.fence_state == "COMMITTED"
    assert len(
        restarted.coordination.bus.repository.list_thread(
            "qualified-coordination"
        )
    ) == 1

    context = restarted.resume_context()
    assert context["coordination_commands"]["binding_count"] == 1
    assert context["coordination_commands"]["result_count"] == 1
    assert context["coordination_command_recovery"][0]["terminal"] is True


def test_crash_after_coordination_commit_before_result_journal_never_replays(
    tmp_path,
    monkeypatch,
):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    permit = runtime.accepted_permit()

    def lose_result(*args, **kwargs):
        raise RuntimeError("crash after effect commit before command result journal")

    monkeypatch.setattr(
        runtime.coordination_commands,
        "record_result",
        lose_result,
    )
    with pytest.raises(RuntimeError):
        runtime.coordination.invoke(
            "coordination_post",
            permit=permit,
            actor=actor(),
            command_id="coord-crash",
            args=(draft("committed before journal result"),),
        )

    assert runtime.fence.read(
        "coordination:coord-crash"
    ).state is EffectState.COMMITTED
    assert len(
        runtime.coordination.bus.repository.list_thread(
            "qualified-coordination"
        )
    ) == 1

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    assessment = restarted.coordination.assess_command("coord-crash")
    assert assessment.result_recorded is False
    assert assessment.fence_state == "COMMITTED"
    assert assessment.recovery_required is True
    assert assessment.retry_candidate_allowed is False
    assert assessment.terminal is False

    calls_before = len(
        restarted.coordination.bus.repository.list_thread(
            "qualified-coordination"
        )
    )
    with pytest.raises(Exception):
        restarted.coordination.invoke(
            "coordination_post",
            permit=restarted.accepted_permit(),
            actor=actor(),
            command_id="coord-crash",
            args=(draft("committed before journal result"),),
        )
    assert len(
        restarted.coordination.bus.repository.list_thread(
            "qualified-coordination"
        )
    ) == calls_before


def test_reserved_coordination_command_cancels_without_dispatch(tmp_path, monkeypatch):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    permit = runtime.accepted_permit()

    def reserve_then_crash(**kwargs):
        evidence = kwargs["verify_authority"]()
        request_digest = runtime.coordination.effects.effect_request_digest(
            permit=kwargs["permit"],
            effect_id=kwargs["effect_id"],
            effect_kind=kwargs["effect_kind"],
            request_payload=kwargs["request_payload"],
        )
        mechanical_digest = (
            runtime.coordination.effects.mechanical_permit_digest(
                permit=kwargs["permit"],
                effect_id=kwargs["effect_id"],
                request_digest=request_digest,
            )
        )
        runtime.audit.append(
            effect_id=kwargs["effect_id"],
            effect_kind=kwargs["effect_kind"],
            event_type="AUTHORITY_VERIFIED",
            payload={
                "request_digest": request_digest,
                "mechanical_permit_digest": mechanical_digest,
                "lifecycle_permit": {
                    **kwargs["permit"].canonical_body(),
                    "permit_digest": kwargs["permit"].permit_digest,
                },
                "authority_evidence_digest": evidence.evidence_digest,
                "authority_details": dict(evidence.details),
            },
        )
        receipt = runtime.fence.reserve(
            effect_id=kwargs["effect_id"],
            request_digest=request_digest,
            mechanical_permit_digest=mechanical_digest,
            authority_evidence_digest=evidence.evidence_digest,
            currentness_evidence_digest=kwargs["permit"].permit_digest,
        )
        runtime.audit.append(
            effect_id=kwargs["effect_id"],
            effect_kind=kwargs["effect_kind"],
            event_type="RESERVED",
            payload={
                "request_digest": receipt.request_digest,
                "mechanical_permit_digest": receipt.mechanical_permit_digest,
                "authority_evidence_digest": receipt.authority_evidence_digest,
                "currentness_evidence_digest": receipt.currentness_evidence_digest,
            },
        )
        raise RuntimeError("crash before dispatch claim")

    monkeypatch.setattr(
        runtime.coordination.effects,
        "_dispatch_verified",
        reserve_then_crash,
    )
    with pytest.raises(RuntimeError):
        runtime.coordination.invoke(
            "coordination_post",
            permit=permit,
            actor=actor(),
            command_id="coord-reserved",
            args=(draft("reserved but not dispatched"),),
        )

    assessment = runtime.coordination.assess_command("coord-reserved")
    assert assessment.fence_state == "RESERVED"
    assert assessment.pre_dispatch_cancel_allowed is True
    assert assessment.recovery_required is False

    cancelled = runtime.coordination.cancel_reserved_command(
        "coord-reserved"
    )
    assert cancelled.fence_state == "CANCELLED_PRE_DISPATCH"
    assert cancelled.terminal is True
    assert cancelled.retry_candidate_allowed is False
    assert runtime.audit.latest(
        "coordination:coord-reserved"
    ).event_type == "CANCELLED_PRE_DISPATCH"
    assert runtime.coordination.bus.repository.list_thread(
        "qualified-coordination"
    ) == ()
