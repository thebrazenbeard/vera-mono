from dataclasses import dataclass, replace
import sqlite3

import pytest

from vera_assurance import EffectState
from vera_core import (
    HmacProviderAuthority,
    QualifiedVeraRuntime,
    SourceMutationBindingError,
    SourceMutationError,
    SourceMutationRequest,
    SourceMutationTransportResult,
    TaskExecutionError,
    TaskPacket,
    VeraStateDirectory,
    source_provider_id,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
REPOSITORY = "thebrazenbeard/vera-mono"
REF = "main"
PROVIDER_ID = source_provider_id(REPOSITORY)


@dataclass
class FakeSourceTransport:
    repository: str = REPOSITORY
    ref: str = REF
    provider_id: str = PROVIDER_ID
    bad_result: bool = False

    def __post_init__(self):
        self.calls = []

    def mutate(self, request_payload):
        self.calls.append(request_payload)
        return SourceMutationTransportResult(
            repository=self.repository,
            ref=self.ref,
            operation=request_payload["operation"],
            path=request_payload["path"],
            destination_path=request_payload["destination_path"],
            previous_ref_head=(
                "wrong-head"
                if self.bad_result
                else request_payload["expected_ref_head"]
            ),
            new_ref_head="head-after",
            result_id=f"result:{request_payload['mutation_id']}",
        )


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
            text="source mutation state",
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


def runtime_with_source(tmp_path, *, bad_result=False):
    state = accepted_state(tmp_path)
    verifier = HmacProviderAuthority(
        "source-authority",
        PROVIDER_ID,
        b"s" * 32,
        key_id="source-key-v1",
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER_ID,
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )
    transport = FakeSourceTransport(bad_result=bad_result)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER_ID: verifier},
        source_mutation_transports={(REPOSITORY, REF): transport},
    )
    return state, runtime, verifier, transport


def packet(*scopes):
    return TaskPacket(
        purpose="mutate scoped source safely",
        subject="source-mutation-test",
        completion_state="source mutation verified",
        evidence_requirements=("mutation result",),
        writable_scope=tuple(scopes),
        non_targets=("deployment",),
        forbidden_shortcuts_or_effects=("force push",),
        priority_order=("scope", "ownership", "CAS", "write"),
        unknowns=(),
        return_shape=("result",),
        relevant_surfaces=("source",),
    )


def write_request(
    *,
    mutation_id="mutation-1",
    path="packages/vera_core/src/vera_core/example.py",
    subject="example.py",
    actor_ref="vera",
):
    return SourceMutationRequest(
        mutation_id=mutation_id,
        repository=REPOSITORY,
        ref=REF,
        subject=subject,
        actor_ref=actor_ref,
        operation="WRITE_FILE",
        path=path,
        expected_ref_head="head-before",
        expected_blob_id="blob-before",
        content="print('qualified')\n",
    )


def authority_for(verifier, prepared):
    dispatch = prepared.provider_dispatch
    return verifier.issue(
        effect_id=dispatch.effect_id,
        operation=dispatch.operation,
        request_digest=dispatch.request_digest,
        lifecycle_permit_digest=dispatch.permit.permit_digest,
    )


def reserve_source_effect_without_dispatch(runtime, prepared):
    dispatch = prepared.provider_dispatch
    mechanical_effect_id = (
        f"provider:{dispatch.provider_id}:{dispatch.effect_id}"
    )
    effect_kind = (
        f"PROVIDER/{dispatch.provider_id}/{dispatch.operation}"
    )
    outer_payload = {
        "provider_request_digest": dispatch.request_digest,
        "request_payload": dispatch.request_payload,
        "authority_subject": dispatch.authority_subject,
    }
    request_digest = runtime.effects.effect_request_digest(
        permit=dispatch.permit,
        effect_id=mechanical_effect_id,
        effect_kind=effect_kind,
        request_payload=outer_payload,
    )
    mechanical_permit_digest = runtime.effects.mechanical_permit_digest(
        permit=dispatch.permit,
        effect_id=mechanical_effect_id,
        request_digest=request_digest,
    )
    authority_evidence_digest = "a" * 64
    runtime.audit.append(
        effect_id=mechanical_effect_id,
        effect_kind=effect_kind,
        event_type="AUTHORITY_VERIFIED",
        payload={
            "request_digest": request_digest,
            "mechanical_permit_digest": mechanical_permit_digest,
            "lifecycle_permit": {
                **dispatch.permit.canonical_body(),
                "permit_digest": dispatch.permit.permit_digest,
            },
            "authority_evidence_digest": authority_evidence_digest,
            "authority_details": {
                "kind": "TEST_PRE_DISPATCH_RESERVATION",
                "task_dependency": (
                    None
                    if dispatch.task_dependency is None
                    else dispatch.task_dependency.canonical_body()
                ),
            },
        },
    )
    reserved = runtime.fence.reserve(
        effect_id=mechanical_effect_id,
        request_digest=request_digest,
        mechanical_permit_digest=mechanical_permit_digest,
        authority_evidence_digest=authority_evidence_digest,
        currentness_evidence_digest=dispatch.permit.permit_digest,
    )
    runtime.audit.append(
        effect_id=mechanical_effect_id,
        effect_kind=effect_kind,
        event_type="RESERVED",
        payload={
            "request_digest": reserved.request_digest,
            "mechanical_permit_digest": reserved.mechanical_permit_digest,
            "authority_evidence_digest": reserved.authority_evidence_digest,
            "currentness_evidence_digest": (
                reserved.currentness_evidence_digest
            ),
        },
    )
    return mechanical_effect_id


def test_source_write_requires_task_packet_writable_scope_before_transport(tmp_path):
    _, runtime, verifier, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet(
            "SOURCE|thebrazenbeard/vera-mono|main|"
            "packages/vera_core/src/vera_core/**"
        ),
    )
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-1",
        "dep-source-1",
        write_request(),
    )
    result = adapter.execute(
        prepared,
        authority=authority_for(verifier, prepared),
    )
    assert len(transport.calls) == 1
    assert result.transport_result.previous_ref_head == "head-before"
    assert result.transport_result.new_ref_head == "head-after"
    receipt = runtime.fence.read(
        f"provider:{PROVIDER_ID}:mutation-1"
    )
    assert receipt.state is EffectState.COMMITTED


def test_source_write_outside_packet_scope_fails_before_any_source_write(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet(
            "SOURCE|thebrazenbeard/vera-mono|main|"
            "packages/vera_memory/**"
        ),
    )
    with pytest.raises(SourceMutationError):
        runtime.source_mutation_adapter().prepare(
            "task-1",
            "dep-source-1",
            write_request(),
        )
    assert transport.calls == []
    assert runtime.tasks.read("task-1").dependencies == ()


def test_active_delegation_requires_exact_owner_ref_before_source_write(tmp_path):
    _, runtime, verifier, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet(
            "SOURCE|thebrazenbeard/vera-mono|main|"
            "packages/vera_core/src/vera_core/**"
        ),
    )
    state = runtime.delegate_task_work(
        "task-1",
        "delegation-1",
        repository=REPOSITORY,
        ref=REF,
        subject="example.py",
        assignee_ref="worker:source",
        allowed_effects=("SOURCE_WRITE_FILE",),
        prohibited_effects=(),
        return_shape=("commit",),
        evidence_refs=("delegation:evidence",),
    )
    owner_ref = state.delegation_ref("delegation-1")
    adapter = runtime.source_mutation_adapter()
    request = write_request(actor_ref="worker:source")

    with pytest.raises(TaskExecutionError):
        adapter.prepare(
            "task-1",
            "dep-source-1",
            request,
        )
    assert transport.calls == []

    prepared = adapter.prepare(
        "task-1",
        "dep-source-2",
        replace(
            request,
            mutation_id="mutation-2",
        ),
        delegation_ref=owner_ref,
    )
    adapter.execute(
        prepared,
        authority=authority_for(verifier, prepared),
    )
    assert len(transport.calls) == 1


def test_wrong_actor_or_stale_delegation_ref_cannot_write(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    state = runtime.delegate_task_work(
        "task-1",
        "delegation-1",
        repository=REPOSITORY,
        ref=REF,
        subject="example.py",
        assignee_ref="worker:one",
        allowed_effects=("SOURCE_MUTATION",),
        prohibited_effects=(),
        return_shape=("commit",),
        evidence_refs=("delegation:evidence",),
    )
    stale = state.delegation_ref("delegation-1")
    runtime.reassign_task_delegation(
        "task-1",
        "delegation-1",
        "reassign-1",
        new_assignee_ref="worker:two",
        evidence_refs=("reassign:evidence",),
    )
    request = write_request(actor_ref="worker:one")
    with pytest.raises(TaskExecutionError):
        runtime.source_mutation_adapter().prepare(
            "task-1",
            "dep-source-1",
            request,
            delegation_ref=stale,
        )
    assert transport.calls == []


def test_move_requires_both_source_and_destination_inside_writable_scope(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet(
            "SOURCE|thebrazenbeard/vera-mono|main|src/**",
        ),
    )
    request = SourceMutationRequest(
        mutation_id="move-1",
        repository=REPOSITORY,
        ref=REF,
        subject="src/a.py",
        actor_ref="vera",
        operation="MOVE_FILE",
        path="src/a.py",
        destination_path="docs/a.py",
        expected_ref_head="head-before",
        expected_blob_id="blob-a",
        expected_destination_blob_id="ABSENT",
    )
    with pytest.raises(SourceMutationError):
        runtime.source_mutation_adapter().prepare(
            "task-1",
            "dep-move-1",
            request,
        )
    assert transport.calls == []


def test_source_transport_result_mismatch_becomes_ambiguous_not_false_commit(tmp_path):
    _, runtime, verifier, transport = runtime_with_source(
        tmp_path,
        bad_result=True,
    )
    runtime.start_task(
        "task-1",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-1",
        "dep-source-1",
        write_request(),
    )
    with pytest.raises(SourceMutationError):
        adapter.execute(
            prepared,
            authority=authority_for(verifier, prepared),
        )
    assert len(transport.calls) == 1
    receipt = runtime.fence.read(
        f"provider:{PROVIDER_ID}:mutation-1"
    )
    assert receipt.state is EffectState.ATTEMPTED_UNKNOWN


def test_source_provider_cannot_escape_through_generic_provider_transport_path(tmp_path):
    _, runtime, verifier, _ = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    prepared = runtime.source_mutation_adapter().prepare(
        "task-1",
        "dep-source-1",
        write_request(),
    )
    with pytest.raises(ValueError, match="qualified source mutation adapter"):
        runtime.execute_provider_effect(
            prepared.provider_dispatch,
            authority=authority_for(verifier, prepared),
        )


def test_source_provider_cannot_escape_through_generic_callback_dispatch(tmp_path):
    _, runtime, verifier, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-1",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    prepared = runtime.source_mutation_adapter().prepare(
        "task-1",
        "dep-source-1",
        write_request(),
    )
    with pytest.raises(ValueError, match="qualified source mutation adapter"):
        runtime.dispatch_provider_effect(
            prepared.provider_dispatch,
            authority=authority_for(verifier, prepared),
            execute=lambda: transport.mutate(
                prepared.request.request_payload()
            ),
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    "path",
    (
        "src/../README.md",
        "src\\evil.py",
        "/src/absolute.py",
        "src//double.py",
    ),
)
def test_source_scope_rejects_path_normalization_bypasses_before_transport(
    tmp_path,
    path,
):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-path-bypass",
        packet("SOURCE|thebrazenbeard/vera-mono|main|src/**"),
    )
    with pytest.raises(SourceMutationError):
        runtime.source_mutation_adapter().prepare(
            "task-path-bypass",
            "dep-path-bypass",
            write_request(path=path),
        )
    assert transport.calls == []
    assert runtime.tasks.read("task-path-bypass").dependencies == ()


def test_source_scope_prefix_boundary_does_not_match_similar_sibling(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-prefix-boundary",
        packet("SOURCE|thebrazenbeard/vera-mono|main|src/**"),
    )
    with pytest.raises(SourceMutationError):
        runtime.source_mutation_adapter().prepare(
            "task-prefix-boundary",
            "dep-prefix-boundary",
            write_request(path="src2/escape.py"),
        )
    assert transport.calls == []
    assert runtime.tasks.read("task-prefix-boundary").dependencies == ()


def test_source_prepare_persists_nonsecret_restart_binding(tmp_path):
    state, runtime, _, _ = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-binding",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    prepared = runtime.source_mutation_adapter().prepare(
        "task-binding",
        "dep-binding",
        write_request(
            mutation_id="mutation-binding",
            path="src/binding.py",
        ),
    )

    binding = state.source_mutation_binding_store().read(
        "mutation-binding"
    )
    assert binding.task_id == "task-binding"
    assert binding.dependency_id == "dep-binding"
    assert binding.packet_digest == prepared.packet_digest
    assert binding.repository == REPOSITORY
    assert binding.ref == REF
    assert binding.path == "src/binding.py"
    assert binding.content_digest == prepared.request.content_digest
    assert (
        binding.provider_request_digest
        == prepared.provider_dispatch.request_digest
    )
    assert (
        binding.lifecycle_permit_digest
        == prepared.provider_dispatch.permit.permit_digest
    )

    with sqlite3.connect(state.paths.source_mutation_bindings) as db:
        payload_json = db.execute(
            """
            SELECT payload_json
            FROM source_mutation_bindings
            WHERE mutation_id='mutation-binding'
            """
        ).fetchone()[0]
    assert "print('qualified')" not in payload_json
    assert '"content_persisted":false' in payload_json


def test_source_binding_survives_restart_without_prepared_object(tmp_path):
    state, runtime, _, _ = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-restart-binding",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-restart-binding",
        "dep-restart-binding",
        write_request(
            mutation_id="mutation-restart-binding",
            path="src/restart.py",
        ),
    )

    reopened = VeraStateDirectory(
        state.paths.root,
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    context = reopened.resume_context()
    source = context["source_mutation_bindings"]
    assert source["binding_count"] == 1
    persisted = source["bindings"][0]
    assert persisted["mutation_id"] == "mutation-restart-binding"
    assert persisted["task_id"] == "task-restart-binding"
    assert persisted["path"] == "src/restart.py"
    assert persisted["content_persisted"] is False


def test_prepared_source_binding_is_restart_dispatch_candidate_with_rehydration(tmp_path):
    _, runtime, _, _ = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-recovery-candidate",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-recovery-candidate",
        "dep-recovery-candidate",
        write_request(
            mutation_id="mutation-recovery-candidate",
            path="src/recovery.py",
        ),
    )

    assessment = runtime.recover_source_mutations()[0]
    assert assessment.mutation_id == "mutation-recovery-candidate"
    assert assessment.provider_fence_state is None
    assert assessment.task_open is True
    assert assessment.packet_current is True
    assert assessment.writable_scope_current is True
    assert assessment.delegation_current is True
    assert assessment.provider_binding_current is True
    assert assessment.transport_available is True
    assert assessment.content_rehydration_required is True
    assert assessment.dispatch_candidate_allowed is True
    assert assessment.recovery_required is False


def test_ambiguous_source_mutation_is_restart_recovery_not_replay_candidate(tmp_path):
    _, runtime, verifier, _ = runtime_with_source(
        tmp_path,
        bad_result=True,
    )
    runtime.start_task(
        "task-ambiguous-source",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-ambiguous-source",
        "dep-ambiguous-source",
        write_request(
            mutation_id="mutation-ambiguous-source",
            path="src/ambiguous.py",
        ),
    )
    with pytest.raises(SourceMutationError):
        adapter.execute(
            prepared,
            authority=authority_for(verifier, prepared),
        )

    assessment = runtime.recover_source_mutations()[0]
    assert assessment.provider_fence_state == "ATTEMPTED_UNKNOWN"
    assert assessment.dispatch_candidate_allowed is False
    assert assessment.recovery_required is True
    assert assessment.terminal is False


def test_source_restart_rehydrates_exact_write_without_persisting_content(tmp_path):
    _, runtime, verifier, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-rehydrate",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-rehydrate",
        "dep-rehydrate",
        write_request(
            mutation_id="mutation-rehydrate",
            path="src/rehydrate.py",
        ),
    )

    adapter = runtime.source_mutation_adapter()
    restored = adapter.rehydrate_mutation(
        "mutation-rehydrate",
        content="print('qualified')\n",
    )
    assert restored.request.content_digest == (
        runtime.source_mutation_bindings.read(
            "mutation-rehydrate"
        ).content_digest
    )
    result = adapter.execute(
        restored,
        authority=authority_for(verifier, restored),
    )
    assert result.transport_result.new_ref_head == "head-after"
    assert len(transport.calls) == 1


def test_source_restart_rejects_wrong_rehydrated_content_before_transport(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-rehydrate-wrong",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-rehydrate-wrong",
        "dep-rehydrate-wrong",
        write_request(
            mutation_id="mutation-rehydrate-wrong",
            path="src/rehydrate-wrong.py",
        ),
    )

    with pytest.raises(
        SourceMutationError,
        match="does not match durable content digest",
    ):
        runtime.source_mutation_adapter().rehydrate_mutation(
            "mutation-rehydrate-wrong",
            content="print('different')\n",
        )
    assert transport.calls == []



def test_source_restart_rejects_prepared_mutation_after_lifecycle_moves(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-stale-lifecycle",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-stale-lifecycle",
        "dep-stale-lifecycle",
        write_request(
            mutation_id="mutation-stale-lifecycle",
            path="src/stale-lifecycle.py",
        ),
    )

    admitted = runtime.lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m2",
            text="advance canonical memory after source preparation",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op2",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=runtime.lifecycle.memory.current_head,
    )
    assert admitted["store_head"] == runtime.lifecycle.memory.current_head

    assessment = runtime.recover_source_mutations()[0]
    assert assessment.lifecycle_permit_current is False
    assert assessment.dispatch_candidate_allowed is False

    with pytest.raises(
        SourceMutationError,
        match="not a current dispatch candidate",
    ):
        runtime.source_mutation_adapter().rehydrate_mutation(
            "mutation-stale-lifecycle",
            content="print('qualified')\n",
        )
    assert transport.calls == []


def test_source_restart_rejects_stale_delegation_after_reassignment(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-delegation-restart",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    delegated = runtime.delegate_task_work(
        "task-delegation-restart",
        "delegation-restart",
        repository=REPOSITORY,
        ref=REF,
        subject="restart-owned.py",
        assignee_ref="worker:one",
        allowed_effects=("SOURCE_WRITE_FILE",),
        prohibited_effects=(),
        return_shape=("commit",),
        evidence_refs=("delegation:evidence",),
    )
    owner_ref = delegated.delegation_ref("delegation-restart")
    runtime.source_mutation_adapter().prepare(
        "task-delegation-restart",
        "dep-delegation-restart",
        write_request(
            mutation_id="mutation-delegation-restart",
            path="src/restart-owned.py",
            subject="restart-owned.py",
            actor_ref="worker:one",
        ),
        delegation_ref=owner_ref,
    )
    runtime.reassign_task_delegation(
        "task-delegation-restart",
        "delegation-restart",
        "reassign-restart",
        new_assignee_ref="worker:two",
        evidence_refs=("reassign:evidence",),
    )

    assessment = runtime.recover_source_mutations()[0]
    assert assessment.delegation_current is False
    assert assessment.dispatch_candidate_allowed is False

    with pytest.raises(
        SourceMutationError,
        match="not a current dispatch candidate",
    ):
        runtime.source_mutation_adapter().rehydrate_mutation(
            "mutation-delegation-restart",
            content="print('qualified')\n",
        )
    assert transport.calls == []


def test_source_restart_without_transport_is_not_dispatch_candidate(tmp_path):
    state, runtime, verifier, _ = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-no-transport",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-no-transport",
        "dep-no-transport",
        write_request(
            mutation_id="mutation-no-transport",
            path="src/no-transport.py",
        ),
    )

    reopened = QualifiedVeraRuntime.from_state_directory(
        VeraStateDirectory(
            state.paths.root,
            project_id=PROJECT,
            identity_id=IDENTITY,
        ),
        provider_authority_verifiers={PROVIDER_ID: verifier},
    )
    assessment = reopened.recover_source_mutations()[0]
    assert assessment.transport_available is False
    assert assessment.dispatch_candidate_allowed is False
    assert assessment.recovery_required is False


def test_source_binding_tamper_fails_closed_on_read(tmp_path):
    state, runtime, _, _ = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-binding-tamper",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-binding-tamper",
        "dep-binding-tamper",
        write_request(
            mutation_id="mutation-binding-tamper",
            path="src/binding-tamper.py",
        ),
    )

    with sqlite3.connect(state.paths.source_mutation_bindings) as db:
        db.execute(
            """
            UPDATE source_mutation_bindings
            SET payload_json='{}'
            WHERE mutation_id='mutation-binding-tamper'
            """
        )

    with pytest.raises(SourceMutationBindingError):
        state.source_mutation_binding_store().read(
            "mutation-binding-tamper"
        )


def test_source_recovery_detects_tampered_provider_binding_cross_store(tmp_path):
    state, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-provider-binding-tamper",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-provider-binding-tamper",
        "dep-provider-binding-tamper",
        write_request(
            mutation_id="mutation-provider-binding-tamper",
            path="src/provider-binding-tamper.py",
        ),
    )

    with sqlite3.connect(state.paths.provider_execution_bindings) as db:
        db.execute(
            """
            UPDATE provider_execution_bindings
            SET payload_json='{}'
            WHERE effect_id='mutation-provider-binding-tamper'
            """
        )

    assessment = runtime.recover_source_mutations()[0]
    assert assessment.provider_binding_current is False
    assert assessment.dispatch_candidate_allowed is False
    assert assessment.recovery_required is True
    assert transport.calls == []



def test_source_restart_candidate_dies_when_provider_verifier_rotates(tmp_path):
    state, runtime, verifier, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-provider-rotation",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    runtime.source_mutation_adapter().prepare(
        "task-provider-rotation",
        "dep-provider-rotation",
        write_request(
            mutation_id="mutation-provider-rotation",
            path="src/provider-rotation.py",
        ),
    )

    rotated = HmacProviderAuthority(
        verifier.authority_id,
        PROVIDER_ID,
        b"r" * 32,
        key_id="source-key-v2",
    )
    trust = state.outbound_trust_registry()
    trust.rotate(
        authority_id=rotated.authority_id,
        role="PROVIDER",
        provider_id=PROVIDER_ID,
        key_id=rotated.key_id,
        key_digest=rotated.key_digest,
        expected_registry_generation=1,
        expected_authority_generation=1,
    )

    assessment = runtime.recover_source_mutations()[0]
    assert assessment.provider_authority_current is False
    assert assessment.dispatch_candidate_allowed is False
    assert "provider authority currentness" in assessment.reason

    with pytest.raises(
        SourceMutationError,
        match="not a current dispatch candidate",
    ):
        runtime.source_mutation_adapter().rehydrate_mutation(
            "mutation-provider-rotation",
            content="print('qualified')\n",
        )
    assert transport.calls == []



def test_reserved_source_effect_can_cancel_dependency_without_reusing_identity(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-cancel-reserved",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-cancel-reserved",
        "dep-cancel-reserved",
        write_request(
            mutation_id="mutation-cancel-reserved",
            path="src/cancel-reserved.py",
        ),
    )
    mechanical_effect_id = reserve_source_effect_without_dispatch(
        runtime,
        prepared,
    )

    cancelled = adapter.cancel_reserved_mutation(
        "mutation-cancel-reserved",
        actor_ref="vera",
        reason="restart proved transport callback never began",
    )
    assert cancelled.mechanical_effect_id == mechanical_effect_id
    assert (
        cancelled.effect_receipt.state
        is EffectState.CANCELLED_PRE_DISPATCH
    )
    assert cancelled.task_state.active_dependencies == ()
    assert "dep-cancel-reserved" in (
        cancelled.task_state.cancelled_dependency_ids
    )
    assert transport.calls == []

    old = runtime.assess_provider_effect(
        "mutation-cancel-reserved"
    )
    assert old.terminal is True
    assert old.dispatch_candidate_allowed is False
    assert old.fence_state == "CANCELLED_PRE_DISPATCH"

    replacement = adapter.prepare(
        "task-cancel-reserved",
        "dep-cancel-replacement",
        write_request(
            mutation_id="mutation-cancel-replacement",
            path="src/cancel-reserved.py",
        ),
    )
    assert replacement.request.mutation_id == (
        "mutation-cancel-replacement"
    )


def test_reserved_source_cancellation_follows_current_delegation_owner(tmp_path):
    _, runtime, _, transport = runtime_with_source(tmp_path)
    runtime.start_task(
        "task-cancel-delegated",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    delegated = runtime.delegate_task_work(
        "task-cancel-delegated",
        "delegation-cancel",
        repository=REPOSITORY,
        ref=REF,
        subject="cancel-owned.py",
        assignee_ref="worker:one",
        allowed_effects=("SOURCE_WRITE_FILE",),
        prohibited_effects=(),
        return_shape=("commit",),
        evidence_refs=("delegation:evidence",),
    )
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-cancel-delegated",
        "dep-cancel-delegated",
        write_request(
            mutation_id="mutation-cancel-delegated",
            path="src/cancel-owned.py",
            subject="cancel-owned.py",
            actor_ref="worker:one",
        ),
        delegation_ref=delegated.delegation_ref(
            "delegation-cancel"
        ),
    )
    reserve_source_effect_without_dispatch(runtime, prepared)

    reassigned = runtime.reassign_task_delegation(
        "task-cancel-delegated",
        "delegation-cancel",
        "reassign-cancel",
        new_assignee_ref="worker:two",
        evidence_refs=("reassign:evidence",),
    )
    current_ref = reassigned.delegation_ref("delegation-cancel")

    with pytest.raises(TaskExecutionError):
        adapter.cancel_reserved_mutation(
            "mutation-cancel-delegated",
            actor_ref="worker:one",
            delegation_ref=prepared.delegation_ref,
            reason="stale owner must not cancel",
        )

    cancelled = adapter.cancel_reserved_mutation(
        "mutation-cancel-delegated",
        actor_ref="worker:two",
        delegation_ref=current_ref,
        reason="current delegated owner abandons pre-dispatch attempt",
    )
    assert (
        cancelled.effect_receipt.state
        is EffectState.CANCELLED_PRE_DISPATCH
    )
    assert transport.calls == []



def test_source_cancellation_refuses_ambiguous_dispatched_effect(tmp_path):
    _, runtime, verifier, transport = runtime_with_source(
        tmp_path,
        bad_result=True,
    )
    runtime.start_task(
        "task-cancel-ambiguous",
        packet("SOURCE|thebrazenbeard/vera-mono|main|**"),
    )
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-cancel-ambiguous",
        "dep-cancel-ambiguous",
        write_request(
            mutation_id="mutation-cancel-ambiguous",
            path="src/cancel-ambiguous.py",
        ),
    )
    with pytest.raises(SourceMutationError):
        adapter.execute(
            prepared,
            authority=authority_for(verifier, prepared),
        )
    assert len(transport.calls) == 1

    with pytest.raises(
        SourceMutationError,
        match="only a RESERVED pre-dispatch",
    ):
        adapter.cancel_reserved_mutation(
            "mutation-cancel-ambiguous",
            actor_ref="vera",
            reason="must not erase ambiguous dispatch",
        )

    dependency_ids = {
        item.dependency_id
        for item in runtime.tasks.read(
            "task-cancel-ambiguous"
        ).active_dependencies
    }
    assert "dep-cancel-ambiguous" in dependency_ids
    assert runtime.fence.read(
        f"provider:{PROVIDER_ID}:mutation-cancel-ambiguous"
    ).state is EffectState.ATTEMPTED_UNKNOWN
