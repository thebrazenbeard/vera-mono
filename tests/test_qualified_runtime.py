from datetime import datetime, timezone

from coordination_bus import CoordinationBus, InMemoryCoordinationRepository
from pc_connection.contracts import AuthorizationEnvelope, JobEnvelope
from vera_core import (
    HmacEffectReconciliationAuthority,
    HmacPCJobAuthority,
    HmacProviderAuthority,
    QualifiedVeraRuntime,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
PROVIDER = "example-provider"


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
    assert runtime.resume_context()["effect_recovery_required"] is False


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


def test_qualified_runtime_does_not_invent_unconfigured_authority(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    assert runtime.coordination is None
    assert runtime.recovery is None
    assert runtime.outbound_trust.generation == 0
