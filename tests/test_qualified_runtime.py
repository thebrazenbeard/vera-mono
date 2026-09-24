from datetime import datetime, timezone

import pytest

from coordination_bus import CoordinationBus, InMemoryCoordinationRepository
from pc_connection.contracts import AuthorizationEnvelope, JobEnvelope
from vera_core import (
    HmacEffectReconciliationAuthority,
    HmacPCJobAuthority,
    HmacProviderAuthority,
    OutboundAuthorityError,
    OutboundTrustError,
    QualifiedVeraRuntime,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
PROVIDER = "example-provider"


class StubPCTransport:
    def __init__(self, host_id):
        self.host_id = host_id
        self.calls = []

    def execute(self, job, authorization):
        self.calls.append((job.envelope_id, authorization.envelope_id))
        return {"transport": "pc", "operation": job.operation_id}


class StubProviderTransport:
    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.calls = []

    def execute(self, operation, request_payload):
        self.calls.append((operation, request_payload))
        return {
            "transport": "provider",
            "operation": operation,
            "payload": request_payload,
        }


def accepted_state(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    request = AdmissionRequest(
        record_id="m1",
        text="qualified runtime bootstrap",
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
    return state


def pc_job():
    return JobEnvelope.from_mapping(
        {
            "schema_version": "VERA_PCCC_JOB_V1",
            "envelope_id": "00000000-0000-7000-8000-000000000001",
            "request_id": "00000000-0000-7000-8000-000000000002",
            "idempotency_key": "qualified-runtime-ping",
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
    )


def pc_authorization(job):
    return AuthorizationEnvelope.from_mapping(
        {
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
    )


def test_qualified_runtime_composes_state_bus_effects_and_recovery(tmp_path):
    state = accepted_state(tmp_path)
    provider = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"p" * 32,
    )
    recovery = HmacEffectReconciliationAuthority(
        "recovery-authority",
        b"r" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=provider.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER,
        key_id=provider.key_id,
        key_digest=provider.key_digest,
        expected_registry_generation=trust.generation,
    )
    trust.register(
        authority_id=recovery.authority_id,
        role="RECONCILIATION",
        key_id=recovery.key_id,
        key_digest=recovery.key_digest,
        expected_registry_generation=trust.generation,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: provider},
        reconciliation_verifier=recovery,
        coordination_bus=CoordinationBus(InMemoryCoordinationRepository()),
    )
    assert runtime.coordination is not None
    assert runtime.recovery is not None
    assert runtime.lifecycle.effect_fence is not None
    assert runtime.lifecycle.effect_fence.path == runtime.fence.path

    prepared = runtime.prepare_provider_effect(
        effect_id="qualified-effect",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"qualified": True},
    )
    authority = provider.issue(
        effect_id=prepared.effect_id,
        operation=prepared.operation,
        request_digest=prepared.request_digest,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )
    assert authority.subject == prepared.authority_subject
    result = runtime.dispatch_provider_effect(
        prepared,
        authority=authority,
        execute=lambda: {"ok": True},
    )
    assert result.value == {"ok": True}
    audit_events = runtime.audit.events(
        "provider:example-provider:qualified-effect"
    )
    assert [event.event_type for event in audit_events] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "COMMITTED",
    ]
    authority_details = audit_events[0].payload["authority_details"]
    assert authority_details["kind"] == "PROVIDER"
    assert authority_details["authority_id"] == provider.authority_id
    assert "verification_token" not in str(authority_details)
    resume = runtime.resume_context()
    assert resume["effect_recovery_required"] is False
    assert resume["outbound_trust"]["registry_generation"] == 2
    assert resume["outbound_audit"]["effect_count"] == 1
    assert resume["outbound_audit"]["sequence"] == 4
    assert {
        scope["role"] for scope in resume["outbound_trust"]["scopes"]
    } == {"PROVIDER", "RECONCILIATION"}


def test_qualified_runtime_pc_adapter_owns_lifecycle_wiring(tmp_path):
    state = accepted_state(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    pc = HmacPCJobAuthority(
        authorization.issuer_id,
        b"c" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=pc.authority_id,
        role="PC",
        key_id=pc.key_id,
        key_digest=pc.key_digest,
        expected_registry_generation=trust.generation,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        pc_authority_verifier=pc,
        clock=lambda: datetime(
            2026,
            8,
            1,
            20,
            5,
            tzinfo=timezone.utc,
        ),
    )
    prepared = runtime.prepare_pc_job(
        job=job,
        authorization=authorization,
    )
    proof = pc.issue(
        job=prepared.job,
        authorization=prepared.authorization,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )
    assert proof.subject == prepared.authority_subject
    result = runtime.dispatch_pc_job(
        prepared,
        authority_proof=proof,
        execute=lambda: {"pong": True},
    )
    assert result.value == {"pong": True}
    pc_audit = runtime.audit.events(
        f"pc:{prepared.job.envelope_id}"
    )
    assert [event.event_type for event in pc_audit] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "COMMITTED",
    ]
    assert pc_audit[0].payload["authority_details"]["kind"] == "PC"


def test_qualified_runtime_does_not_invent_unconfigured_authority(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    assert runtime.coordination is None
    assert runtime.recovery is None
    assert runtime.outbound_trust.generation == 0


def test_provider_key_rotation_invalidates_live_runtime_verifier(tmp_path):
    state = accepted_state(tmp_path)
    first = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"a" * 32,
        key_id="provider-v1",
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=first.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER,
        key_id=first.key_id,
        key_digest=first.key_digest,
        expected_registry_generation=0,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: first},
    )
    prepared = runtime.prepare_provider_effect(
        effect_id="rotated-provider-effect",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": 1},
    )
    old_authority = first.issue(
        effect_id=prepared.effect_id,
        operation=prepared.operation,
        request_digest=prepared.request_digest,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )

    second = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"b" * 32,
        key_id="provider-v2",
    )
    trust.rotate(
        authority_id=second.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER,
        key_id=second.key_id,
        key_digest=second.key_digest,
        expected_registry_generation=1,
        expected_authority_generation=1,
    )

    calls = []
    with pytest.raises(OutboundTrustError):
        runtime.dispatch_provider_effect(
            prepared,
            authority=old_authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []

    refreshed = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: second},
    )
    fresh_prepared = refreshed.prepare_provider_effect(
        effect_id="rotated-provider-effect-v2",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": 2},
    )
    fresh_authority = second.issue(
        effect_id=fresh_prepared.effect_id,
        operation=fresh_prepared.operation,
        request_digest=fresh_prepared.request_digest,
        lifecycle_permit_digest=fresh_prepared.permit.permit_digest,
    )
    result = refreshed.dispatch_provider_effect(
        fresh_prepared,
        authority=fresh_authority,
        execute=lambda: {"ok": 2},
    )
    assert result.value == {"ok": 2}


def test_pc_revocation_epoch_survives_reactivation_and_rejects_old_authorization(tmp_path):
    state = accepted_state(tmp_path)
    job = pc_job()
    authorization = pc_authorization(job)
    first = HmacPCJobAuthority(
        authorization.issuer_id,
        b"a" * 32,
        key_id="pc-v1",
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=first.authority_id,
        role="PC",
        key_id=first.key_id,
        key_digest=first.key_digest,
        expected_registry_generation=0,
    )
    trust.revoke(
        authority_id=first.authority_id,
        role="PC",
        expected_registry_generation=1,
        expected_revocation_epoch=0,
    )

    second = HmacPCJobAuthority(
        authorization.issuer_id,
        b"b" * 32,
        key_id="pc-v2",
    )
    current = trust.reactivate(
        authority_id=second.authority_id,
        role="PC",
        key_id=second.key_id,
        key_digest=second.key_digest,
        expected_registry_generation=2,
        expected_authority_generation=1,
        expected_revocation_epoch=1,
    )
    assert current.revocation_epoch == 1

    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        pc_authority_verifier=second,
        clock=lambda: datetime(
            2026,
            8,
            1,
            20,
            5,
            tzinfo=timezone.utc,
        ),
    )
    prepared = runtime.prepare_pc_job(
        job=job,
        authorization=authorization,
    )
    proof = second.issue(
        job=job,
        authorization=authorization,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )
    calls = []
    with pytest.raises(OutboundAuthorityError):
        runtime.dispatch_pc_job(
            prepared,
            authority_proof=proof,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_qualified_runtime_audits_ambiguous_effect_reconciliation(tmp_path):
    state = accepted_state(tmp_path)
    provider = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"p" * 32,
    )
    recovery_authority = HmacEffectReconciliationAuthority(
        "recovery-authority",
        b"r" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=provider.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER,
        key_id=provider.key_id,
        key_digest=provider.key_digest,
        expected_registry_generation=0,
    )
    trust.register(
        authority_id=recovery_authority.authority_id,
        role="RECONCILIATION",
        key_id=recovery_authority.key_id,
        key_digest=recovery_authority.key_digest,
        expected_registry_generation=1,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: provider},
        reconciliation_verifier=recovery_authority,
    )
    prepared = runtime.prepare_provider_effect(
        effect_id="ambiguous-audit",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": "unknown"},
    )
    authority = provider.issue(
        effect_id=prepared.effect_id,
        operation=prepared.operation,
        request_digest=prepared.request_digest,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )
    with pytest.raises(RuntimeError):
        runtime.dispatch_provider_effect(
            prepared,
            authority=authority,
            execute=lambda: (_ for _ in ()).throw(
                RuntimeError("remote outcome unknown")
            ),
        )

    effect_id = "provider:example-provider:ambiguous-audit"
    assert [event.event_type for event in runtime.audit.events(effect_id)] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "ATTEMPTED_UNKNOWN",
    ]
    receipt = runtime.fence.read(effect_id)
    proof = recovery_authority.issue(
        receipt,
        effect_occurred=False,
        result_digest=None,
    )
    assert runtime.recovery is not None
    reconciled = runtime.recovery.reconcile(
        effect_id,
        proof=proof,
        effect_occurred=False,
        result_digest=None,
    )
    assert reconciled.state.value == "RECONCILED_NO_EFFECT"
    assert runtime.audit.latest(effect_id).event_type == "RECONCILED_NO_EFFECT"
    assert runtime.audit.verify_chain() == runtime.audit.head


def test_qualified_provider_execution_uses_host_injected_transport(tmp_path):
    state = accepted_state(tmp_path)
    verifier = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"p" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER,
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )
    transport = StubProviderTransport(PROVIDER)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
        provider_execution_transports={PROVIDER: transport},
    )
    prepared = runtime.prepare_provider_effect(
        effect_id="transport-bound-provider",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": 7},
    )
    authority = verifier.issue(
        effect_id=prepared.effect_id,
        operation=prepared.operation,
        request_digest=prepared.request_digest,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )

    result = runtime.execute_provider_effect(
        prepared,
        authority=authority,
    )

    assert transport.calls == [("WRITE", {"value": 7})]
    assert result.value["transport"] == "provider"
    assert runtime.audit.latest(
        "provider:example-provider:transport-bound-provider"
    ).event_type == "COMMITTED"


def test_qualified_pc_execution_uses_host_injected_transport(tmp_path):
    state = accepted_state(tmp_path)
    bound_job = pc_job()
    bound_authorization = pc_authorization(bound_job)
    verifier = HmacPCJobAuthority(
        bound_authorization.issuer_id,
        b"c" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PC",
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )
    transport = StubPCTransport(bound_job.host_id)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        pc_authority_verifier=verifier,
        pc_execution_transport=transport,
        clock=lambda: datetime(
            2026,
            8,
            1,
            20,
            5,
            tzinfo=timezone.utc,
        ),
    )
    prepared = runtime.prepare_pc_job(
        job=bound_job,
        authorization=bound_authorization,
    )
    proof = verifier.issue(
        job=bound_job,
        authorization=bound_authorization,
        lifecycle_permit_digest=prepared.permit.permit_digest,
    )

    result = runtime.execute_pc_job(
        prepared,
        authority_proof=proof,
    )

    assert transport.calls == [
        (bound_job.envelope_id, bound_authorization.envelope_id)
    ]
    assert result.value == {"transport": "pc", "operation": "PING"}


def test_execution_transport_requires_matching_trusted_authority(tmp_path):
    state = accepted_state(tmp_path)

    with pytest.raises(ValueError, match="trusted PC authority verifier"):
        QualifiedVeraRuntime.from_state_directory(
            state,
            pc_execution_transport=StubPCTransport(
                "00000000-0000-7000-8000-000000000003"
            ),
        )

    with pytest.raises(ValueError, match="trusted provider authority verifier"):
        QualifiedVeraRuntime.from_state_directory(
            state,
            provider_execution_transports={
                PROVIDER: StubProviderTransport(PROVIDER)
            },
        )


def test_provider_execution_transport_identity_mismatch_fails_at_composition(tmp_path):
    state = accepted_state(tmp_path)
    verifier = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"p" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER,
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        QualifiedVeraRuntime.from_state_directory(
            state,
            provider_authority_verifiers={PROVIDER: verifier},
            provider_execution_transports={
                PROVIDER: StubProviderTransport("wrong-provider")
            },
        )
