from datetime import datetime, timezone
from types import SimpleNamespace
import sqlite3

import pytest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    InMemoryCoordinationRepository,
)
from pc_connection.contracts import AuthorizationEnvelope, JobEnvelope
from vera_assurance import EffectState
from vera_core import (
    HmacEffectReconciliationAuthority,
    HmacPCJobAuthority,
    HmacProviderAuthority,
    LifecycleActionDenied,
    OutboundAuthorityError,
    OutboundTrustError,
    ProviderExecutionBindingError,
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

    def attest(self):
        return SimpleNamespace(
            host_id=self.host_id,
            capability_digest="3" * 64,
            local_policy_digest="2" * 64,
            read_roots_digest="1" * 64,
        )

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


class MutatingProviderTransport:
    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.received = None

    def execute(self, operation, request_payload):
        self.received = request_payload
        request_payload["transport_mutated"] = True
        return {"operation": operation, "payload": request_payload}


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
    assert runtime.coordination is not None
    assert type(runtime.coordination.bus.repository).__name__ == (
        "SQLiteCoordinationRepository"
    )
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


def provider_runtime(state, *, secret=b"p" * 32):
    verifier = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        secret,
    )
    trust = state.outbound_trust_registry()
    if not trust.has_scope(role="PROVIDER", provider_id=PROVIDER):
        trust.register(
            authority_id=verifier.authority_id,
            role="PROVIDER",
            provider_id=PROVIDER,
            key_id=verifier.key_id,
            key_digest=verifier.key_digest,
            expected_registry_generation=trust.generation,
        )
    transport = StubProviderTransport(PROVIDER)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
        provider_execution_transports={PROVIDER: transport},
    )
    return runtime, verifier, transport


def test_provider_prepare_persists_metadata_without_request_payload(tmp_path):
    state = accepted_state(tmp_path)
    runtime, _, _ = provider_runtime(state)
    secret_payload = {
        "operation": "rotate",
        "api_key": "DO-NOT-PERSIST-THIS-SECRET",
    }

    prepared = runtime.prepare_provider_effect(
        effect_id="payload-safe-provider",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload=secret_payload,
    )

    binding = runtime.provider_execution_bindings.read(
        prepared.effect_id
    )
    assert binding.request_digest == prepared.request_digest
    assert binding.authority_subject == prepared.authority_subject
    assert binding.permit.permit_digest == prepared.permit.permit_digest

    with sqlite3.connect(runtime.provider_execution_bindings.path) as db:
        payload_json = db.execute(
            "SELECT payload_json FROM provider_execution_bindings "
            "WHERE effect_id=?",
            (prepared.effect_id,),
        ).fetchone()[0]
    assert "DO-NOT-PERSIST-THIS-SECRET" not in payload_json
    assert '"request_payload_persisted":false' in payload_json


def test_provider_effect_rehydrates_after_restart_from_matching_payload(tmp_path):
    state = accepted_state(tmp_path)
    runtime, verifier, _ = provider_runtime(state)
    payload = {"value": 41, "mode": "safe"}
    prepared = runtime.prepare_provider_effect(
        effect_id="provider-restart",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload=payload,
    )
    original_permit = prepared.permit.permit_digest
    original_subject = prepared.authority_subject

    restarted = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
        provider_execution_transports={
            PROVIDER: StubProviderTransport(PROVIDER)
        },
    )
    rehydrated = restarted.rehydrate_provider_effect(
        "provider-restart",
        request_payload=payload,
    )

    assert rehydrated.request_digest == prepared.request_digest
    assert rehydrated.permit.permit_digest == original_permit
    assert rehydrated.authority_subject == original_subject
    authority = verifier.issue(
        effect_id=rehydrated.effect_id,
        operation=rehydrated.operation,
        request_digest=rehydrated.request_digest,
        lifecycle_permit_digest=rehydrated.permit.permit_digest,
    )
    result = restarted.execute_provider_effect(
        rehydrated,
        authority=authority,
    )
    assert result.value["payload"] == payload


def test_provider_rehydrate_rejects_changed_payload(tmp_path):
    state = accepted_state(tmp_path)
    runtime, verifier, _ = provider_runtime(state)
    runtime.prepare_provider_effect(
        effect_id="provider-rehydrate-mismatch",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": 1},
    )
    restarted = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
    )

    with pytest.raises(ValueError, match="does not match durable binding"):
        restarted.rehydrate_provider_effect(
            "provider-rehydrate-mismatch",
            request_payload={"value": 2},
        )


def test_provider_effect_identity_cannot_rebind_different_request(tmp_path):
    state = accepted_state(tmp_path)
    runtime, _, _ = provider_runtime(state)
    runtime.prepare_provider_effect(
        effect_id="provider-single-binding",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": 1},
    )

    with pytest.raises(
        ProviderExecutionBindingError,
        match="already binds different request metadata",
    ):
        runtime.prepare_provider_effect(
            effect_id="provider-single-binding",
            provider_id=PROVIDER,
            operation="WRITE",
            request_payload={"value": 2},
        )


def test_provider_binding_restart_context_survives_without_payload(tmp_path):
    state = accepted_state(tmp_path)
    runtime, _, _ = provider_runtime(state)
    prepared = runtime.prepare_provider_effect(
        effect_id="provider-context",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"secret": "ephemeral-only"},
    )

    context = VeraStateDirectory(
        state.paths.root,
        project_id=PROJECT,
        identity_id=IDENTITY,
    ).resume_context()
    provider_context = context["provider_execution_bindings"]
    assert provider_context["binding_count"] == 1
    record = provider_context["bindings"][0]
    assert record["effect_id"] == prepared.effect_id
    assert record["request_digest"] == prepared.request_digest
    assert record["request_payload_persisted"] is False
    assert "ephemeral-only" not in str(provider_context)


def test_rehydrated_provider_binding_does_not_refresh_stale_lifecycle_permit(tmp_path):
    state = accepted_state(tmp_path)
    runtime, verifier, _ = provider_runtime(state)
    prepared = runtime.prepare_provider_effect(
        effect_id="provider-stale-permit",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": "old-cut"},
    )

    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m2",
            text="advance lifecycle after provider binding",
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
    lifecycle.checkpoint(
        checkpoint_id="cp2",
        runtime_id="runtime-2",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=0,
    )

    restarted = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
    )
    rehydrated = restarted.rehydrate_provider_effect(
        prepared.effect_id,
        request_payload={"value": "old-cut"},
    )
    authority = verifier.issue(
        effect_id=rehydrated.effect_id,
        operation=rehydrated.operation,
        request_digest=rehydrated.request_digest,
        lifecycle_permit_digest=rehydrated.permit.permit_digest,
    )
    calls = []
    with pytest.raises(LifecycleActionDenied):
        restarted.dispatch_provider_effect(
            rehydrated,
            authority=authority,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_provider_execution_uses_detached_payload_snapshot(tmp_path):
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
    transport = MutatingProviderTransport(PROVIDER)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
        provider_execution_transports={PROVIDER: transport},
    )
    caller_payload = {"value": {"nested": 9}}
    prepared = runtime.prepare_provider_effect(
        effect_id="provider-detached-payload",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload=caller_payload,
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

    assert transport.received is not caller_payload
    assert "transport_mutated" not in caller_payload
    assert result.value["payload"]["transport_mutated"] is True


def test_provider_recovery_assessment_distinguishes_prepared_ambiguous_and_terminal(tmp_path):
    state = accepted_state(tmp_path)
    runtime, verifier, _ = provider_runtime(state)
    prepared = runtime.prepare_provider_effect(
        effect_id="provider-assessment",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": 11},
    )

    prepared_assessment = runtime.assess_provider_effect(
        prepared.effect_id
    )
    assert prepared_assessment.fence_state is None
    assert prepared_assessment.lifecycle_permit_current is True
    assert prepared_assessment.dispatch_candidate_allowed is True
    assert prepared_assessment.recovery_required is False
    assert prepared_assessment.terminal is False

    authority = verifier.issue(
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
                RuntimeError("provider outcome unknown")
            ),
        )
    ambiguous = runtime.assess_provider_effect(prepared.effect_id)
    assert ambiguous.fence_state == "ATTEMPTED_UNKNOWN"
    assert ambiguous.dispatch_candidate_allowed is False
    assert ambiguous.recovery_required is True
    assert ambiguous.terminal is False

    recovery = HmacEffectReconciliationAuthority(
        "recovery-provider-assessment",
        b"r" * 32,
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=recovery.authority_id,
        role="RECONCILIATION",
        key_id=recovery.key_id,
        key_digest=recovery.key_digest,
        expected_registry_generation=trust.generation,
    )
    recovered_runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: verifier},
        reconciliation_verifier=recovery,
    )
    receipt = recovered_runtime.fence.read(
        "provider:example-provider:provider-assessment"
    )
    proof = recovery.issue(
        receipt,
        effect_occurred=False,
        result_digest=None,
    )
    assert recovered_runtime.recovery is not None
    recovered_runtime.recovery.reconcile(
        receipt.effect_id,
        proof=proof,
        effect_occurred=False,
        result_digest=None,
    )
    terminal = recovered_runtime.assess_provider_effect(
        prepared.effect_id
    )
    assert terminal.fence_state == "RECONCILED_NO_EFFECT"
    assert terminal.dispatch_candidate_allowed is False
    assert terminal.recovery_required is False
    assert terminal.terminal is True


def test_provider_recovery_assessment_marks_stale_prepared_binding_non_dispatchable(tmp_path):
    state = accepted_state(tmp_path)
    runtime, _, _ = provider_runtime(state)
    prepared = runtime.prepare_provider_effect(
        effect_id="provider-assessment-stale",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload={"value": "old"},
    )

    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m3",
            text="advance provider assessment lifecycle",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op3",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp3",
        runtime_id="runtime-3",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=0,
    )

    restarted, _, _ = provider_runtime(state)
    assessment = restarted.assess_provider_effect(
        prepared.effect_id
    )
    assert assessment.fence_state is None
    assert assessment.lifecycle_permit_current is False
    assert assessment.dispatch_candidate_allowed is False
    assert assessment.recovery_required is False
    assert assessment.terminal is False

    context = restarted.resume_context()
    provider_recovery = {
        item["effect_id"]: item
        for item in context["provider_execution_recovery"]
    }
    assert (
        provider_recovery["provider-assessment-stale"][
            "dispatch_candidate_allowed"
        ]
        is False
    )


def test_native_coordination_write_survives_runtime_restart(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    actor = ActorContext("workstream/memory", ALL_PERMISSIONS)
    target = ActorContext("workstream/time", ALL_PERMISSIONS)
    draft = CoordinationEventDraft(
        thread_key="native-runtime-coordination",
        source_branch="workstream/memory",
        target_branch="workstream/time",
        event_type="STATUS",
        status="IN_PROGRESS",
        objective="Persist native runtime coordination",
        summary="Coordination must survive process reconstruction.",
    )
    permit = runtime.accepted_permit()

    written = runtime.coordination.invoke(
        "coordination_post",
        permit=permit,
        actor=actor,
        command_id="native-coordination-command-1",
        args=(draft,),
    )
    event = written.value.events[0]
    assert written.fence_receipt.state is EffectState.COMMITTED
    assert state.coordination_repository().get(event.event_id) == event

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    read = restarted.coordination.invoke(
        "coordination_read_inbox",
        permit=restarted.accepted_permit(),
        actor=target,
    )
    assert [item.event_id for item in read.events] == [event.event_id]
    context = restarted.resume_context()
    assert context["coordination"]["persistent_native"] is True
    assert state.resume_context()["coordination"]["event_sequence"] == 1


class LegacyPCTransportWithoutAttestation:
    def __init__(self, host_id):
        self.host_id = host_id
        self.calls = []

    def execute(self, job, authorization):
        self.calls.append((job.envelope_id, authorization.envelope_id))
        return {"transport": "legacy", "operation": job.operation_id}


class DirectMismatchPCTransport(StubPCTransport):
    def attest(self):
        return SimpleNamespace(
            host_id=self.host_id,
            capability_digest="9" * 64,
            local_policy_digest="2" * 64,
            read_roots_digest="1" * 64,
        )


def _trusted_pc_runtime_parts(tmp_path, transport):
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
    return state, bound_job, runtime, prepared, proof


def test_direct_runtime_pc_execution_rejects_capability_mismatch_before_effect(tmp_path):
    bound_job = pc_job()
    transport = DirectMismatchPCTransport(bound_job.host_id)
    state, _, runtime, prepared, proof = _trusted_pc_runtime_parts(
        tmp_path,
        transport,
    )

    with pytest.raises(ValueError, match="capability digest"):
        runtime.execute_pc_job(prepared, authority_proof=proof)

    assert transport.calls == []
    with pytest.raises(KeyError):
        runtime.fence.read(f"pc:{prepared.job.envelope_id}")
    assert state.pc_execution_binding_store().all() == ()


def test_runtime_composition_rejects_legacy_pc_transport_without_attestation(tmp_path):
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

    with pytest.raises(TypeError, match="PCExecutionTransport"):
        QualifiedVeraRuntime.from_state_directory(
            state,
            pc_authority_verifier=verifier,
            pc_execution_transport=LegacyPCTransportWithoutAttestation(
                bound_job.host_id
            ),
        )