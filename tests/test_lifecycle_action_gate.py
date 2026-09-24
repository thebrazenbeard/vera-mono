from datetime import datetime, timezone

import pytest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    InMemoryCoordinationRepository,
)
from pc_connection.contracts import AuthorizationEnvelope, JobEnvelope
from vera_assurance import EffectFenceError, EffectState
from vera_core import (
    HmacEffectReconciliationAuthority,
    HmacPCJobAuthority,
    HmacProviderAuthority,
    LifecycleActionDenied,
    LifecycleAssuranceError,
    LifecycleBoundCoordinationBus,
    LifecycleEffectGateway,
    LifecycleEffectRecovery,
    OutboundAuthorityError,
    EffectRecoveryAuthorityError,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
PROVIDER_ID = "example-provider"


def build_accepted(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    request = AdmissionRequest(
        record_id="m1",
        text="accepted state",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id=PROJECT,
        governed_identity_id=IDENTITY,
    )
    admitted = lifecycle.memory.admit(
        request,
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state, lifecycle, lifecycle.accepted_action_permit()


def status_draft():
    return CoordinationEventDraft(
        thread_key="lifecycle-bound-bus",
        source_branch="workstream/memory",
        target_branch="workstream/integration",
        event_type="STATUS",
        status="IN_PROGRESS",
        objective="Prove exact accepted lifecycle gating",
        summary="This event may leave Vera only from accepted currentness.",
    )


def pc_job(**changes):
    value = {
        "schema_version": "VERA_PCCC_JOB_V1",
        "envelope_id": "00000000-0000-7000-8000-000000000001",
        "request_id": "00000000-0000-7000-8000-000000000002",
        "idempotency_key": "lifecycle-bound-ping-001",
        "project_id": PROJECT,
        "requester_principal_id": "service/vera",
        "requester_principal_type": "SERVICE",
        "host_id": "00000000-0000-7000-8000-000000000003",
        "operation_id": "PING",
        "operation_version": 1,
        "parameters_digest": "0" * 64,
        "artifact_manifest_digest": "0" * 64,
        "read_roots_digest": "1" * 64,
        "write_root_id": "NONE",
        "authorization_id": "00000000-0000-7000-8000-000000000004",
        "authorization_revision": 1,
        "not_before": "2026-08-01T20:00:00.000000Z",
        "expires_at": "2026-08-01T20:15:00.000000Z",
        "timeout_seconds": 30,
        "max_attempts": 1,
        "lease_ttl_seconds": 90,
        "retry_class": "PURE_READ",
        "protocol_min_version": "1.0.0",
        "agent_min_version": "0.1.0",
        "required_local_policy_digest": "2" * 64,
        "required_capability_digest": "3" * 64,
        "issuer_revocation_epoch": 0,
        "host_revocation_epoch": 0,
        "nonce": "00000000-0000-7000-8000-000000000005",
        "trace_correlation_id": "00000000-0000-7000-8000-000000000006",
    }
    value.update(changes)
    return JobEnvelope.from_mapping(value)


def pc_authorization(job, **changes):
    value = {
        "schema_version": "VERA_PCCC_AUTHORIZATION_V1",
        "envelope_id": "00000000-0000-7000-8000-000000000011",
        "job_id": "00000000-0000-7000-8000-000000000012",
        "issuer_id": "issuer/pccc-owner",
        "subject_user_id": "user/operator",
        "host_id": job.host_id,
        "operation": job.operation_id,
        "operation_version": job.operation_version,
        "parameters_digest": job.parameters_digest,
        "artifact_manifest_digest": job.artifact_manifest_digest,
        "read_roots_digest": job.read_roots_digest,
        "write_root_id": job.write_root_id,
        "authorization_id": job.authorization_id,
        "authorization_revision": job.authorization_revision,
        "issued_at": "2026-08-01T19:59:00.000000Z",
        "not_before": job.not_before,
        "expires_at": job.expires_at,
        "nonce": "00000000-0000-7000-8000-000000000014",
        "max_attempts": job.max_attempts,
        "lease_ttl_seconds": job.lease_ttl_seconds,
        "protocol_min_version": job.protocol_min_version,
        "agent_min_version": job.agent_min_version,
        "issuer_revocation_epoch": job.issuer_revocation_epoch,
        "host_revocation_epoch": job.host_revocation_epoch,
    }
    value.update(changes)
    return AuthorizationEnvelope.from_mapping(value)


def provider_authority(
    permit,
    request_payload,
    *,
    effect_id,
    operation="WRITE",
    secret=b"p" * 32,
):
    verifier = HmacProviderAuthority(
        "provider-authority",
        PROVIDER_ID,
        secret,
    )
    request_digest = LifecycleEffectGateway.provider_request_digest(
        provider_id=PROVIDER_ID,
        operation=operation,
        request_payload=request_payload,
    )
    envelope = verifier.issue(
        effect_id=effect_id,
        operation=operation,
        request_digest=request_digest,
        lifecycle_permit_digest=permit.permit_digest,
    )
    return verifier, envelope


def provider_gateway(state, lifecycle, verifier):
    return LifecycleEffectGateway(
        lifecycle=lifecycle,
        fence=state.effect_fence(),
        provider_authority_verifiers={PROVIDER_ID: verifier},
    )


def pc_authority(permit, job, authorization, *, secret=b"c" * 32):
    verifier = HmacPCJobAuthority("pc-authority", secret)
    proof = verifier.issue(
        job=job,
        authorization=authorization,
        lifecycle_permit_digest=permit.permit_digest,
    )
    return verifier, proof


def pc_gateway(state, lifecycle, verifier, *, now=None):
    return LifecycleEffectGateway(
        lifecycle=lifecycle,
        fence=state.effect_fence(),
        pc_authority_verifier=verifier,
        clock=lambda: now
        or datetime(2026, 8, 1, 20, 5, tzinfo=timezone.utc),
    )


def test_coordination_gateway_covers_every_public_bus_command(tmp_path):
    state, lifecycle, _ = build_accepted(tmp_path)
    bus = CoordinationBus(InMemoryCoordinationRepository())
    gateway = LifecycleBoundCoordinationBus(
        lifecycle=lifecycle,
        bus=bus,
        fence=state.effect_fence(),
    )
    public = {
        name for name in dir(bus) if name.startswith("coordination_")
    } | {"entry_checkpoint", "exit_checkpoint"}
    assert public <= gateway.COMMANDS


def test_coordination_write_consumes_exact_permit_and_is_single_use_fenced(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    repo = InMemoryCoordinationRepository()
    gateway = LifecycleBoundCoordinationBus(
        lifecycle=lifecycle,
        bus=CoordinationBus(repo),
        fence=state.effect_fence(),
    )
    actor = ActorContext("workstream/memory", ALL_PERMISSIONS)
    effect = gateway.invoke(
        "coordination_post",
        permit=permit,
        actor=actor,
        command_id="bus-command-1",
        args=(status_draft(),),
    )
    assert effect.fence_receipt.state is EffectState.COMMITTED
    assert effect.value.receipt.database_write_confirmed is True
    assert len(repo.list_thread("lifecycle-bound-bus")) == 1
    with pytest.raises(EffectFenceError):
        gateway.invoke(
            "coordination_post",
            permit=permit,
            actor=actor,
            command_id="bus-command-1",
            args=(status_draft(),),
        )


def test_every_coordination_read_is_lifecycle_permit_bound(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    gateway = LifecycleBoundCoordinationBus(
        lifecycle=lifecycle,
        bus=CoordinationBus(InMemoryCoordinationRepository()),
        fence=state.effect_fence(),
    )
    actor = ActorContext("workstream/memory", ALL_PERMISSIONS)
    assert gateway.invoke(
        "coordination_read_inbox",
        permit=permit,
        actor=actor,
    ).receipt.result_class == "COMPLETE"

    lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m2",
            text="memory advanced without accepted currentness",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op2",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )
    with pytest.raises(LifecycleActionDenied):
        gateway.invoke(
            "coordination_read_inbox",
            permit=permit,
            actor=actor,
        )


def test_interrupted_candidate_blocks_verified_provider_authority(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    lifecycle.checkpoints.append(
        checkpoint_id="cp2",
        runtime_id="runtime-interrupted",
        memory_head_digest=lifecycle.memory.current_head,
        control_source_digest=permit.control_source_digest,
        expected_head=lifecycle.checkpoints.current_head,
        unfinished_work=("interrupted candidate",),
    )
    payload = {"value": 1}
    verifier, authority = provider_authority(permit, payload, effect_id="e1")
    gateway = provider_gateway(state, lifecycle, verifier)
    calls = []
    with pytest.raises(LifecycleActionDenied):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="e1",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_blocked_candidate_blocks_verified_provider_authority(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    hostile = {
        "project_id": PROJECT,
        "identity_id": "wrong-identity",
        "runtime_id": "runtime-1",
        "memory_head_digest": lifecycle.memory.current_head,
        "recovery_checkpoint_digest": permit.recovery_checkpoint_digest,
        "recovery_checkpoint_generation": permit.recovery_checkpoint_generation,
        "control_source_digest": "b" * 64,
    }
    with pytest.raises(LifecycleAssuranceError):
        lifecycle.checkpoint(
            checkpoint_id="cp-blocked",
            runtime_id="runtime-blocked",
            expected_memory_head=lifecycle.memory.current_head,
            expected_checkpoint_head=lifecycle.checkpoints.current_head,
            expected_currentness_generation=permit.currentness_generation,
            assurance_baseline=hostile,
        )

    payload = {"value": 2}
    verifier, authority = provider_authority(permit, payload, effect_id="e2")
    gateway = provider_gateway(state, lifecycle, verifier)
    calls = []
    with pytest.raises(LifecycleActionDenied):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="e2",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_provider_effect_requires_exact_verified_authority_and_effect_fence(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    payload = {"value": 7}
    verifier, authority = provider_authority(permit, payload, effect_id="provider-write-1")
    gateway = provider_gateway(state, lifecycle, verifier)
    calls = []
    result = gateway.dispatch_provider_effect(
        permit=permit,
        effect_id="provider-write-1",
        provider_id=PROVIDER_ID,
        operation="WRITE",
        request_payload=payload,
        authority=authority,
        execute=lambda: calls.append("executed") or {"ok": True},
    )
    assert result.fence_receipt.state is EffectState.COMMITTED
    assert result.lifecycle_permit_digest == permit.permit_digest
    assert calls == ["executed"]

    # A fresh externally issued authority proof still cannot bypass the durable
    # effect fence for an already-used effect id.
    verifier2, authority2 = provider_authority(permit, payload, effect_id="provider-write-1")
    gateway2 = provider_gateway(state, lifecycle, verifier2)
    with pytest.raises(EffectFenceError):
        gateway2.dispatch_provider_effect(
            permit=permit,
            effect_id="provider-write-1",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority2,
            execute=lambda: calls.append("executed-again"),
        )
    assert calls == ["executed"]


def test_provider_authority_cannot_be_replayed_for_changed_request(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    original = {"value": 1}
    verifier, authority = provider_authority(permit, original, effect_id="changed-request")
    gateway = provider_gateway(state, lifecycle, verifier)
    calls = []
    with pytest.raises(OutboundAuthorityError):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="changed-request",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload={"value": 2},
            authority=authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_caller_minted_provider_verifier_cannot_replace_trusted_registry(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    payload = {"value": 3}
    trusted, _ = provider_authority(permit, payload, effect_id="forged-provider-authority", secret=b"t" * 32)
    attacker, forged = provider_authority(permit, payload, effect_id="forged-provider-authority", secret=b"x" * 32)
    gateway = provider_gateway(state, lifecycle, trusted)
    calls = []
    with pytest.raises(OutboundAuthorityError):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="forged-provider-authority",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=forged,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []
    assert attacker is not trusted


def test_pc_job_requires_authorization_envelope_and_exact_subject_proof(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    verifier, proof = pc_authority(permit, job, authorization)
    gateway = pc_gateway(state, lifecycle, verifier)
    calls = []
    result = gateway.dispatch_pc_job(
        permit=permit,
        job=job,
        authorization=authorization,
        authority_proof=proof,
        execute=lambda: calls.append("pc") or {"pong": True},
    )
    assert result.effect_kind == "PC/PING"
    assert result.fence_receipt.currentness_evidence_digest == permit.permit_digest
    assert calls == ["pc"]


def test_pc_authorization_field_mismatch_fails_before_authority_issue(tmp_path):
    _, _, permit = build_accepted(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job, authorization_revision=2)
    verifier = HmacPCJobAuthority("pc-authority", b"c" * 32)
    with pytest.raises(OutboundAuthorityError):
        verifier.issue(
            job=job,
            authorization=authorization,
            lifecycle_permit_digest=permit.permit_digest,
        )


def test_caller_minted_pc_verifier_cannot_replace_trusted_verifier(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    trusted = HmacPCJobAuthority("pc-authority", b"t" * 32)
    attacker, forged = pc_authority(
        permit,
        job,
        authorization,
        secret=b"x" * 32,
    )
    gateway = pc_gateway(state, lifecycle, trusted)
    calls = []
    with pytest.raises(OutboundAuthorityError):
        gateway.dispatch_pc_job(
            permit=permit,
            job=job,
            authorization=authorization,
            authority_proof=forged,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []
    assert attacker is not trusted


def test_pc_authority_for_old_permit_cannot_escape_after_memory_moves(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    verifier, proof = pc_authority(permit, job, authorization)
    gateway = pc_gateway(state, lifecycle, verifier)

    lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m-stale",
            text="stale the old accepted permit",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op-stale",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )

    calls = []
    with pytest.raises(LifecycleActionDenied):
        gateway.dispatch_pc_job(
            permit=permit,
            job=job,
            authorization=authorization,
            authority_proof=proof,
            execute=lambda: calls.append("stale-pc"),
        )
    assert calls == []


def test_old_permit_is_rejected_after_new_generation_is_accepted(tmp_path):
    state, lifecycle, old_permit = build_accepted(tmp_path)
    lifecycle.checkpoint(
        checkpoint_id="cp2",
        runtime_id="runtime-2",
        expected_memory_head=lifecycle.memory.current_head,
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=old_permit.currentness_generation,
    )
    new_permit = lifecycle.accepted_action_permit()
    assert new_permit.currentness_generation == old_permit.currentness_generation + 1
    assert new_permit.permit_digest != old_permit.permit_digest

    payload = {"value": 9}
    verifier, authority = provider_authority(old_permit, payload, effect_id="stale-generation")
    gateway = provider_gateway(state, lifecycle, verifier)
    calls = []
    with pytest.raises(LifecycleActionDenied):
        gateway.dispatch_provider_effect(
            permit=old_permit,
            effect_id="stale-generation",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_unregistered_provider_has_no_escape_path(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    payload = {"value": 10}
    _, authority = provider_authority(permit, payload, effect_id="unregistered-provider")
    gateway = LifecycleEffectGateway(
        lifecycle=lifecycle,
        fence=state.effect_fence(),
    )
    with pytest.raises(OutboundAuthorityError):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="unregistered-provider",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority,
            execute=lambda: {"escaped": True},
        )


def test_pc_without_injected_verifier_has_no_escape_path(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    _, proof = pc_authority(permit, job, authorization)
    gateway = LifecycleEffectGateway(
        lifecycle=lifecycle,
        fence=state.effect_fence(),
    )
    with pytest.raises(OutboundAuthorityError):
        gateway.dispatch_pc_job(
            permit=permit,
            job=job,
            authorization=authorization,
            authority_proof=proof,
            execute=lambda: {"escaped": True},
        )


def test_pc_dispatch_rejects_expired_authorization_even_with_valid_proof(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    verifier, proof = pc_authority(permit, job, authorization)
    gateway = pc_gateway(
        state,
        lifecycle,
        verifier,
        now=datetime(2026, 8, 1, 20, 16, tzinfo=timezone.utc),
    )
    calls = []
    with pytest.raises(OutboundAuthorityError):
        gateway.dispatch_pc_job(
            permit=permit,
            job=job,
            authorization=authorization,
            authority_proof=proof,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_ambiguous_external_effect_freezes_actions_and_lifecycle_until_reconciled(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    payload = {"value": "ambiguous"}
    verifier, authority = provider_authority(
        permit,
        payload,
        effect_id="ambiguous-effect",
    )
    gateway = provider_gateway(state, lifecycle, verifier)

    def ambiguous_execution():
        raise RuntimeError("transport died after dispatch")

    with pytest.raises(RuntimeError):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="ambiguous-effect",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority,
            execute=ambiguous_execution,
        )

    fence = state.effect_fence()
    ambiguous = fence.read("provider:example-provider:ambiguous-effect")
    assert ambiguous.state is EffectState.ATTEMPTED_UNKNOWN
    restart_state = lifecycle.reconstruct()
    assert restart_state.effect_recovery_required is True
    assert restart_state.unresolved_effects == (
        (
            "provider:example-provider:ambiguous-effect",
            "ATTEMPTED_UNKNOWN",
        ),
    )
    assert restart_state.as_resume_context()["effect_recovery_required"] is True

    with pytest.raises(EffectFenceError):
        lifecycle.accepted_action_permit()

    with pytest.raises(EffectFenceError):
        lifecycle.checkpoint(
            checkpoint_id="cp-after-ambiguous",
            runtime_id="runtime-2",
            expected_memory_head=lifecycle.memory.current_head,
            expected_checkpoint_head=lifecycle.checkpoints.current_head,
            expected_currentness_generation=permit.currentness_generation,
        )

    second_payload = {"value": "must-not-escape"}
    second_verifier, second_authority = provider_authority(
        permit,
        second_payload,
        effect_id="second-effect",
    )
    second_gateway = provider_gateway(state, lifecycle, second_verifier)
    calls = []
    with pytest.raises(EffectFenceError):
        second_gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="second-effect",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=second_payload,
            authority=second_authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []

    recovery_authority = HmacEffectReconciliationAuthority(
        "effect-recovery-owner",
        b"r" * 32,
    )
    recovery = LifecycleEffectRecovery(
        fence=fence,
        verifier=recovery_authority,
    )
    proof = recovery_authority.issue(
        ambiguous,
        effect_occurred=False,
        result_digest=None,
    )
    reconciled = recovery.reconcile(
        "provider:example-provider:ambiguous-effect",
        proof=proof,
        effect_occurred=False,
        result_digest=None,
    )
    assert reconciled.state is EffectState.RECONCILED_NO_EFFECT
    assert reconciled.reconciliation_evidence_digest is not None
    assert fence.unresolved() == ()
    assert lifecycle.reconstruct().effect_recovery_required is False

    refreshed = lifecycle.accepted_action_permit()
    assert refreshed.permit_digest == permit.permit_digest


def test_caller_minted_reconciliation_verifier_cannot_clear_ambiguous_effect(tmp_path):
    state, lifecycle, permit = build_accepted(tmp_path)
    payload = {"value": "ambiguous-recovery"}
    provider_verifier, authority = provider_authority(
        permit,
        payload,
        effect_id="ambiguous-recovery",
    )
    gateway = provider_gateway(state, lifecycle, provider_verifier)

    with pytest.raises(RuntimeError):
        gateway.dispatch_provider_effect(
            permit=permit,
            effect_id="ambiguous-recovery",
            provider_id=PROVIDER_ID,
            operation="WRITE",
            request_payload=payload,
            authority=authority,
            execute=lambda: (_ for _ in ()).throw(RuntimeError("unknown outcome")),
        )

    fence = state.effect_fence()
    effect_id = "provider:example-provider:ambiguous-recovery"
    receipt = fence.read(effect_id)
    trusted = HmacEffectReconciliationAuthority(
        "effect-recovery-owner",
        b"t" * 32,
    )
    attacker = HmacEffectReconciliationAuthority(
        "effect-recovery-owner",
        b"x" * 32,
    )
    forged = attacker.issue(
        receipt,
        effect_occurred=False,
        result_digest=None,
    )
    recovery = LifecycleEffectRecovery(
        fence=fence,
        verifier=trusted,
    )
    with pytest.raises(EffectRecoveryAuthorityError):
        recovery.reconcile(
            effect_id,
            proof=forged,
            effect_occurred=False,
            result_digest=None,
        )
    assert fence.read(effect_id).state is EffectState.ATTEMPTED_UNKNOWN
