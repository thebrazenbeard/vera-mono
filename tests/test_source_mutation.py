from dataclasses import dataclass

import pytest

from vera_assurance import EffectState
from vera_core import (
    HmacProviderAuthority,
    QualifiedVeraRuntime,
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
        SourceMutationRequest(
            **{
                **request.__dict__,
                "mutation_id": "mutation-2",
            }
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
