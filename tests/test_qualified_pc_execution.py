from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pc_connection.contracts import AuthorizationEnvelope, JobEnvelope
from pc_connection.journal import (
    JobJournal,
    JournalConflict,
    JournalState,
    VerifiedJournalPath,
)
from vera_assurance import EffectFenceError, EffectState
from vera_core import (
    HmacPCJobAuthority,
    OutboundTrustError,
    PCExecutionBindingError,
    PCExecutionLease,
    PCJournalEventEvidence,
    QualifiedPCExecutionAdapter,
    QualifiedVeraRuntime,
    TaskPacket,
    VeraStateDirectory,
)
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
            text="qualified PC adapter state",
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


def job():
    return JobEnvelope.from_mapping(
        {
            "schema_version": "VERA_PCCC_JOB_V1",
            "envelope_id": "00000000-0000-7000-8000-000000000001",
            "request_id": "00000000-0000-7000-8000-000000000002",
            "idempotency_key": "qualified-pc-attempt",
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


def authorization(bound_job):
    return AuthorizationEnvelope.from_mapping(
        {
            "schema_version": "VERA_PCCC_AUTHORIZATION_V1",
            "envelope_id": "00000000-0000-7000-8000-000000000011",
            "job_id": "00000000-0000-7000-8000-000000000012",
            "issuer_id": "issuer/pccc-owner",
            "subject_user_id": "user/operator",
            "host_id": bound_job.host_id,
            "operation": bound_job.operation_id,
            "operation_version": bound_job.operation_version,
            "parameters_digest": bound_job.parameters_digest,
            "artifact_manifest_digest": bound_job.artifact_manifest_digest,
            "read_roots_digest": bound_job.read_roots_digest,
            "write_root_id": bound_job.write_root_id,
            "authorization_id": bound_job.authorization_id,
            "authorization_revision": bound_job.authorization_revision,
            "issued_at": "2026-08-01T19:59:00.000000Z",
            "not_before": bound_job.not_before,
            "expires_at": bound_job.expires_at,
            "nonce": "00000000-0000-7000-8000-000000000014",
            "max_attempts": bound_job.max_attempts,
            "lease_ttl_seconds": bound_job.lease_ttl_seconds,
            "protocol_min_version": bound_job.protocol_min_version,
            "agent_min_version": bound_job.agent_min_version,
            "issuer_revocation_epoch": bound_job.issuer_revocation_epoch,
            "host_revocation_epoch": bound_job.host_revocation_epoch,
        }
    )


def lease(**changes):
    values = {
        "job_id": "00000000-0000-7000-8000-000000000101",
        "attempt_id": "00000000-0000-7000-8000-000000000102",
        "claim_generation": 1,
        "lease_id": "00000000-0000-7000-8000-000000000104",
        "lease_fence": 1,
    }
    values.update(changes)
    return PCExecutionLease(**values)


class Events:
    def __init__(self):
        self.count = 0

    def __call__(self, stage):
        self.count += 1
        return PCJournalEventEvidence(
            local_event_id=f"00000000-0000-7000-8000-{200 + self.count:012d}",
            server_time_anchor="2026-08-01T20:05:00.000000Z",
            local_monotonic_ns=self.count,
            record_time=(
                f"2026-08-01T20:05:{self.count:02d}.000000Z"
            ),
        )


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


def runtime_and_adapter(tmp_path):
    state = accepted_state(tmp_path)
    bound_job = job()
    bound_authorization = authorization(bound_job)
    verifier = HmacPCJobAuthority(
        bound_authorization.issuer_id,
        b"c" * 32,
        key_id="pc-key-v1",
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
    journal = JobJournal(
        VerifiedJournalPath.for_test(tmp_path / "pc-local")
    )
    adapter = QualifiedPCExecutionAdapter(
        runtime=runtime,
        journal=journal,
    )
    return state, runtime, adapter, prepared, proof, verifier


def test_qualified_pc_executes_once_and_stops_at_local_result(tmp_path):
    _, runtime, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    calls = []
    events = Events()
    result = adapter.execute(
        prepared,
        authority_proof=proof,
        lease=lease(),
        event_source=events,
        execute=lambda: calls.append("pc") or {"pong": True},
    )
    assert calls == ["pc"]
    assert result.projection.local_state is JournalState.RESULT_OBSERVED
    assert result.projection.result_digest == result.outbound.result_digest
    assert runtime.fence.read(
        f"pc:{prepared.job.envelope_id}"
    ).state is EffectState.COMMITTED

    assessment = adapter.assess(prepared, lease())
    assert assessment is not None
    assert assessment.replay_allowed is False
    assert assessment.recovery_required is False

    with pytest.raises(EffectFenceError):
        adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=events,
            execute=lambda: calls.append("replayed"),
        )
    assert calls == ["pc"]


def test_local_result_requires_explicit_server_completion_and_readback(tmp_path):
    _, _, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    events = Events()
    executed = adapter.execute(
        prepared,
        authority_proof=proof,
        lease=lease(),
        event_source=events,
        execute=lambda: {"pong": True},
    )
    assert executed.projection.local_state is JournalState.RESULT_OBSERVED

    submitted = adapter.submit_completion(
        prepared,
        lease=lease(),
        receipt_id="00000000-0000-7000-8000-000000000106",
        receipt_digest="b" * 64,
        server_request_id="00000000-0000-7000-8000-000000000107",
        event_source=events,
    )
    assert submitted.local_state is JournalState.COMPLETING

    terminal = adapter.confirm_terminal_readback(
        prepared,
        lease=lease(),
        server_readback_receipt_id=(
            "00000000-0000-7000-8000-000000000108"
        ),
        server_readback_digest="c" * 64,
        event_source=events,
    )
    assert terminal.local_state is JournalState.TERMINAL_CONFIRMED


def test_executor_exception_marks_effect_unknown_and_journal_recovery_required(tmp_path):
    _, runtime, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    events = Events()
    with pytest.raises(RuntimeError):
        adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=events,
            execute=lambda: (_ for _ in ()).throw(
                RuntimeError("transport died after dispatch")
            ),
        )

    projection = adapter.journal.get(
        lease().job_id,
        lease().attempt_id,
    )
    assert projection is not None
    assert projection.local_state is JournalState.RECOVERY_REQUIRED
    assert runtime.fence.read(
        f"pc:{prepared.job.envelope_id}"
    ).state is EffectState.ATTEMPTED_UNKNOWN

    calls = []
    with pytest.raises(EffectFenceError):
        adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=events,
            execute=lambda: calls.append("unsafe-replay"),
        )
    assert calls == []


def test_restart_detects_committed_effect_missing_local_result_and_requires_recovery(tmp_path):
    _, runtime, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    events = Events()
    identity = adapter.identity(prepared, lease())
    adapter.journal.record_claim(
        identity,
        **adapter._event(
            events,
            "CLAIM_RECORDED",
            {
                "stage": "CLAIM_RECORDED",
                "job_digest": prepared.job_digest,
            },
        ),
    )
    adapter.journal.start_preparation(
        identity,
        **adapter._event(
            events,
            "PREPARATION_STARTED",
            {
                "stage": "PREPARATION_STARTED",
                "job_digest": prepared.job_digest,
            },
        ),
    )
    runtime.dispatch_pc_job(
        prepared,
        authority_proof=proof,
        execute=lambda: {"pong": True},
    )

    reopened = QualifiedPCExecutionAdapter(
        runtime=runtime,
        journal=JobJournal(adapter.journal.verified_path),
    )
    assessment = reopened.assess(prepared, lease())
    assert assessment is not None
    assert assessment.recovery_required is True
    assert assessment.effect_state == "COMMITTED"

    calls = []
    with pytest.raises(EffectFenceError):
        reopened.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=events,
            execute=lambda: calls.append("replayed"),
        )
    assert calls == []
    projection = reopened.journal.get(lease().job_id, lease().attempt_id)
    assert projection is not None
    assert projection.local_state is JournalState.RECOVERY_REQUIRED


def test_changed_lease_fence_conflicts_before_external_execution(tmp_path):
    _, _, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    events = Events()
    identity = adapter.identity(prepared, lease())
    adapter.journal.record_claim(
        identity,
        **adapter._event(
            events,
            "CLAIM_RECORDED",
            {"stage": "CLAIM_RECORDED", "job_digest": prepared.job_digest},
        ),
    )
    calls = []
    with pytest.raises(JournalConflict):
        adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(lease_fence=2),
            event_source=events,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []


def test_trust_revocation_after_prepare_blocks_callback_before_effect(tmp_path):
    state, runtime, adapter, prepared, proof, verifier = runtime_and_adapter(tmp_path)
    events = Events()
    identity = adapter.identity(prepared, lease())
    adapter.journal.record_claim(
        identity,
        **adapter._event(
            events,
            "CLAIM_RECORDED",
            {"stage": "CLAIM_RECORDED", "job_digest": prepared.job_digest},
        ),
    )
    adapter.journal.start_preparation(
        identity,
        **adapter._event(
            events,
            "PREPARATION_STARTED",
            {"stage": "PREPARATION_STARTED", "job_digest": prepared.job_digest},
        ),
    )

    trust = state.outbound_trust_registry()
    trust.revoke(
        authority_id=verifier.authority_id,
        role="PC",
        expected_registry_generation=trust.generation,
        expected_revocation_epoch=0,
    )

    calls = []
    with pytest.raises(OutboundTrustError):
        adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=events,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []
    with pytest.raises(KeyError):
        runtime.fence.read(f"pc:{prepared.job.envelope_id}")
    projection = adapter.journal.get(lease().job_id, lease().attempt_id)
    assert projection is not None
    assert projection.local_state is JournalState.PREPARING


def test_restart_recovers_bound_pc_attempt_without_conversation_prepared_object(tmp_path):
    state, _, adapter, prepared, proof, verifier = runtime_and_adapter(tmp_path)
    bindings = state.pc_execution_binding_store()
    journal_path = adapter.journal.verified_path
    bound_adapter = QualifiedPCExecutionAdapter(
        runtime=adapter.runtime,
        journal=adapter.journal,
        bindings=bindings,
    )
    bound_adapter.execute(
        prepared,
        authority_proof=proof,
        lease=lease(),
        event_source=Events(),
        execute=lambda: {"pong": True},
    )
    del prepared
    del proof
    del bound_adapter

    restarted_runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        pc_authority_verifier=verifier,
        clock=lambda: datetime(
            2026,
            8,
            1,
            20,
            5,
            tzinfo=timezone.utc,
        ),
    )
    restarted = QualifiedPCExecutionAdapter(
        runtime=restarted_runtime,
        journal=JobJournal(journal_path),
        bindings=state.pc_execution_binding_store(),
    )
    recovered = restarted.recover_bound_attempts()
    assert len(recovered) == 1
    binding, assessment = recovered[0]
    assert binding.lease == lease()
    assert binding.effect_id == f"pc:{binding.prepared.job.envelope_id}"
    assert assessment is not None
    assert assessment.recovery_required is False
    assert assessment.replay_allowed is False
    assert assessment.effect_state == "COMMITTED"


def test_restart_recovers_ambiguous_bound_attempt_as_recovery_required(tmp_path):
    state, _, adapter, prepared, proof, verifier = runtime_and_adapter(tmp_path)
    bound_adapter = QualifiedPCExecutionAdapter(
        runtime=adapter.runtime,
        journal=adapter.journal,
        bindings=state.pc_execution_binding_store(),
    )
    with pytest.raises(RuntimeError):
        bound_adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=Events(),
            execute=lambda: (_ for _ in ()).throw(
                RuntimeError("unknown remote outcome")
            ),
        )

    restarted_runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        pc_authority_verifier=verifier,
        clock=lambda: datetime(
            2026,
            8,
            1,
            20,
            5,
            tzinfo=timezone.utc,
        ),
    )
    restarted = QualifiedPCExecutionAdapter(
        runtime=restarted_runtime,
        journal=JobJournal(adapter.journal.verified_path),
        bindings=state.pc_execution_binding_store(),
    )
    binding, assessment = restarted.recover_bound_attempts()[0]
    assert binding.binding_digest
    assert assessment is not None
    assert assessment.recovery_required is True
    assert assessment.replay_allowed is False
    assert assessment.effect_state == "ATTEMPTED_UNKNOWN"
    assert assessment.projection.local_state is JournalState.RECOVERY_REQUIRED


def test_pc_binding_attempt_identity_is_append_only(tmp_path):
    state, _, adapter, prepared, _, _ = runtime_and_adapter(tmp_path)
    bindings = state.pc_execution_binding_store()
    first = bindings.bind(prepared, lease())
    assert bindings.bind(prepared, lease()) == first

    with pytest.raises(PCExecutionBindingError):
        bindings.bind(
            prepared,
            lease(lease_fence=2),
        )


def test_reserved_pre_dispatch_effect_can_only_cancel_and_abandon(tmp_path):
    _, runtime, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    events = Events()
    identity = adapter.identity(prepared, lease())
    adapter.journal.record_claim(
        identity,
        **adapter._event(
            events,
            "CLAIM_RECORDED",
            {"stage": "CLAIM_RECORDED", "job_digest": prepared.job_digest},
        ),
    )
    adapter.journal.start_preparation(
        identity,
        **adapter._event(
            events,
            "PREPARATION_STARTED",
            {"stage": "PREPARATION_STARTED", "job_digest": prepared.job_digest},
        ),
    )
    effect_id = f"pc:{prepared.job.envelope_id}"
    runtime.audit.append(
        effect_id=effect_id,
        effect_kind="PC/PING",
        event_type="AUTHORITY_VERIFIED",
        payload={
            "request_digest": "a" * 64,
            "mechanical_permit_digest": "b" * 64,
            "lifecycle_permit": {
                **prepared.permit.canonical_body(),
                "permit_digest": prepared.permit.permit_digest,
            },
            "authority_evidence_digest": "c" * 64,
            "authority_details": {"kind": "PC", "test": True},
        },
    )
    runtime.fence.reserve(
        effect_id=effect_id,
        request_digest="a" * 64,
        mechanical_permit_digest="b" * 64,
        authority_evidence_digest="c" * 64,
        currentness_evidence_digest=prepared.permit.permit_digest,
    )
    runtime.audit.append(
        effect_id=effect_id,
        effect_kind="PC/PING",
        event_type="RESERVED",
        payload={
            "request_digest": "a" * 64,
            "mechanical_permit_digest": "b" * 64,
            "authority_evidence_digest": "c" * 64,
            "currentness_evidence_digest": prepared.permit.permit_digest,
        },
    )
    assessment = adapter.assess(prepared, lease())
    assert assessment is not None
    assert assessment.pre_dispatch_cancel_allowed is True
    assert assessment.recovery_required is False
    assert assessment.replay_allowed is False

    calls = []
    with pytest.raises(EffectFenceError):
        adapter.execute(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=events,
            execute=lambda: calls.append("escaped"),
        )
    assert calls == []

    abandoned = adapter.cancel_reserved_attempt(
        prepared,
        lease=lease(),
        event_source=events,
    )
    assert abandoned.local_state is JournalState.ABANDONED
    assert runtime.fence.read(effect_id).state is EffectState.CANCELLED_PRE_DISPATCH
    assert runtime.audit.latest(effect_id).event_type == "CANCELLED_PRE_DISPATCH"


def test_qualified_pc_journal_path_uses_runtime_injected_transport(tmp_path):
    state = accepted_state(tmp_path)
    bound_job = job()
    bound_authorization = authorization(bound_job)
    verifier = HmacPCJobAuthority(
        bound_authorization.issuer_id,
        b"c" * 32,
        key_id="pc-key-v1",
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
    adapter = QualifiedPCExecutionAdapter(
        runtime=runtime,
        journal=JobJournal(
            VerifiedJournalPath.for_test(tmp_path / "pc-transport-local")
        ),
        bindings=state.pc_execution_binding_store(),
    )

    result = adapter.execute_via_runtime_transport(
        prepared,
        authority_proof=proof,
        lease=lease(),
        event_source=Events(),
    )

    assert transport.calls == [
        (bound_job.envelope_id, bound_authorization.envelope_id)
    ]
    assert result.projection.local_state is JournalState.RESULT_OBSERVED
    assert result.outbound.value == {
        "transport": "pc",
        "operation": "PING",
    }


def test_qualified_pc_adapter_uses_runtime_binding_store_by_default(tmp_path):
    state, runtime, adapter, prepared, proof, _ = runtime_and_adapter(tmp_path)
    assert adapter.bindings.path == runtime.pc_execution_bindings.path

    adapter.execute(
        prepared,
        authority_proof=proof,
        lease=lease(),
        event_source=Events(),
        execute=lambda: {"pong": True},
    )

    resume = runtime.resume_context()
    assert resume["pc_execution_bindings"]["binding_count"] == 1
    binding = resume["pc_execution_bindings"]["bindings"][0]
    assert binding["effect_id"] == f"pc:{prepared.job.envelope_id}"
    assert binding["attempt_id"] == lease().attempt_id
    assert binding["lifecycle_permit_digest"] == prepared.permit.permit_digest


def test_task_pc_execution_binding_persists_task_provenance(tmp_path):
    state, runtime, _, prepared, _, _ = runtime_and_adapter(tmp_path)
    runtime.start_task(
        "task-pc-provenance",
        TaskPacket(
            purpose="Bind exact PC execution to task ownership.",
            subject="pc-task-provenance",
            completion_state="PC task binding is durable.",
            evidence_requirements=("PC binding digest",),
            writable_scope=("local-test-state",),
            non_targets=("deployment",),
            forbidden_shortcuts_or_effects=("no post-hoc task claim",),
            priority_order=("correctness", "evidence"),
            unknowns=(),
            return_shape=("binding",),
            relevant_surfaces=("source",),
        ),
    )
    task_prepared = runtime.prepare_task_pc_job(
        "task-pc-provenance",
        "dep-pc-provenance",
        job=prepared.job,
        authorization=prepared.authorization,
    )
    assert task_prepared.task_dependency is not None
    assert task_prepared.task_dependency.task_id == "task-pc-provenance"

    store = state.pc_execution_binding_store()
    binding = store.bind(task_prepared, lease())
    reopened = state.pc_execution_binding_store().read(
        lease().job_id,
        lease().attempt_id,
    )
    assert reopened.binding_digest == binding.binding_digest
    assert (
        reopened.prepared.task_dependency
        == task_prepared.task_dependency
    )


def test_task_pc_dependency_rejects_non_task_execution_binding(tmp_path):
    state, runtime, _, prepared, _, _ = runtime_and_adapter(tmp_path)
    runtime.start_task(
        "task-pc-launder",
        TaskPacket(
            purpose="Reject PC evidence laundering.",
            subject="pc-task-launder",
            completion_state="Only task-bound PC evidence may satisfy dependency.",
            evidence_requirements=("task provenance",),
            writable_scope=("local-test-state",),
            non_targets=("deployment",),
            forbidden_shortcuts_or_effects=("no post-hoc provenance",),
            priority_order=("correctness", "evidence"),
            unknowns=(),
            return_shape=("assessment",),
            relevant_surfaces=("source",),
        ),
    )
    runtime.bind_task_dependency(
        "task-pc-launder",
        "dep-pc-launder",
        kind="EFFECT",
        target_id=f"pc:{prepared.job.envelope_id}",
    )

    # Persist the same PC attempt through the non-task prepared object.
    state.pc_execution_binding_store().bind(prepared, lease())

    assessment = runtime.assess_task_dependencies("task-pc-launder")[0]
    assert assessment.status == "PROVENANCE_MISMATCH"
    assert assessment.satisfied is False
    assert assessment.cancellation_allowed is False


class _ObservedPCAttestation:
    def __init__(
        self,
        *,
        host_id,
        capability_digest,
        local_policy_digest,
        read_roots_digest,
    ):
        self.host_id = host_id
        self.capability_digest = capability_digest
        self.local_policy_digest = local_policy_digest
        self.read_roots_digest = read_roots_digest


class MismatchedCapabilityPCTransport(StubPCTransport):
    def attest(self):
        return _ObservedPCAttestation(
            host_id=self.host_id,
            capability_digest="9" * 64,
            local_policy_digest="2" * 64,
            read_roots_digest="1" * 64,
        )


def test_runtime_transport_rejects_live_capability_mismatch_before_dispatch(tmp_path):
    state = accepted_state(tmp_path)
    bound_job = job()
    bound_authorization = authorization(bound_job)
    verifier = HmacPCJobAuthority(
        bound_authorization.issuer_id,
        b"c" * 32,
        key_id="pc-key-v1",
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PC",
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )
    transport = MismatchedCapabilityPCTransport(bound_job.host_id)
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
    adapter = QualifiedPCExecutionAdapter(
        runtime=runtime,
        journal=JobJournal(
            VerifiedJournalPath.for_test(tmp_path / "pc-attestation-local")
        ),
        bindings=state.pc_execution_binding_store(),
    )

    with pytest.raises(ValueError, match="capability digest"):
        adapter.execute_via_runtime_transport(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=Events(),
        )

    assert transport.calls == []
    assert adapter.journal.get(lease().job_id, lease().attempt_id) is None


class MismatchedPolicyPCTransport(StubPCTransport):
    def attest(self):
        return _ObservedPCAttestation(
            host_id=self.host_id,
            capability_digest="3" * 64,
            local_policy_digest="9" * 64,
            read_roots_digest="1" * 64,
        )


class MismatchedReadRootsPCTransport(StubPCTransport):
    def attest(self):
        return _ObservedPCAttestation(
            host_id=self.host_id,
            capability_digest="3" * 64,
            local_policy_digest="2" * 64,
            read_roots_digest="9" * 64,
        )


@pytest.mark.parametrize(
    ("transport_type", "error_fragment"),
    [
        (MismatchedPolicyPCTransport, "local policy digest"),
        (MismatchedReadRootsPCTransport, "read roots digest"),
    ],
)
def test_runtime_transport_rejects_other_live_surface_mismatch_before_dispatch(
    tmp_path,
    transport_type,
    error_fragment,
):
    state = accepted_state(tmp_path)
    bound_job = job()
    bound_authorization = authorization(bound_job)
    verifier = HmacPCJobAuthority(
        bound_authorization.issuer_id,
        b"c" * 32,
        key_id="pc-key-v1",
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PC",
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )
    transport = transport_type(bound_job.host_id)
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
    adapter = QualifiedPCExecutionAdapter(
        runtime=runtime,
        journal=JobJournal(
            VerifiedJournalPath.for_test(tmp_path / "pc-surface-local")
        ),
        bindings=state.pc_execution_binding_store(),
    )

    with pytest.raises(ValueError, match=error_fragment):
        adapter.execute_via_runtime_transport(
            prepared,
            authority_proof=proof,
            lease=lease(),
            event_source=Events(),
        )

    assert transport.calls == []
    assert adapter.journal.get(lease().job_id, lease().attempt_id) is None