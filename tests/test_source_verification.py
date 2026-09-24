from dataclasses import dataclass

import pytest

from vera_core import (
    HmacProviderAuthority,
    QualifiedVeraRuntime,
    SourceCheckObservation,
    SourceMutationRequest,
    SourceMutationTransportResult,
    SourceVerificationError,
    SourceVerificationTransportResult,
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
class FakeSourceMutationTransport:
    repository: str = REPOSITORY
    ref: str = REF
    provider_id: str = PROVIDER_ID

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
            previous_ref_head=request_payload["expected_ref_head"],
            new_ref_head="head-after",
            result_id=f"result:{request_payload['mutation_id']}",
        )


@dataclass
class FakeSourceVerificationTransport:
    repository: str = REPOSITORY
    ref: str = REF
    status: str = "PASS"
    observed_ref_head: str = "head-after"

    def __post_init__(self):
        self.calls = []

    def verify(self, commit_sha, required_checks):
        self.calls.append((commit_sha, required_checks))
        return SourceVerificationTransportResult(
            repository=self.repository,
            ref=self.ref,
            commit_sha=commit_sha,
            observed_ref_head=self.observed_ref_head,
            checks=tuple(
                SourceCheckObservation(
                    check_name=name,
                    status=self.status,
                    external_id=f"check:{name}",
                    details_ref=f"details:{name}",
                )
                for name in required_checks
            ),
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
            text="source verification state",
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


def build_runtime(tmp_path, verification_transport):
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
    mutation_transport = FakeSourceMutationTransport()
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER_ID: verifier},
        source_mutation_transports={
            (REPOSITORY, REF): mutation_transport,
        },
        source_verification_transports=(
            {}
            if verification_transport is None
            else {(REPOSITORY, REF): verification_transport}
        ),
    )
    return state, runtime, verifier, mutation_transport


def task_packet():
    return TaskPacket(
        purpose="mutate and verify exact committed source",
        subject="source-verification-test",
        completion_state="exact committed source passes required checks",
        evidence_requirements=(
            "mutation result",
            f"SOURCE_VERIFY|{REPOSITORY}|{REF}|ci",
        ),
        writable_scope=(
            f"SOURCE|{REPOSITORY}|{REF}|packages/vera_core/**",
        ),
        non_targets=("deployment",),
        forbidden_shortcuts_or_effects=("no inferred CI success",),
        priority_order=("exact commit", "verification", "closeout"),
        unknowns=(),
        return_shape=("commit", "verification"),
        relevant_surfaces=("source",),
    )


def mutation_request():
    return SourceMutationRequest(
        mutation_id="mutation-verify-1",
        repository=REPOSITORY,
        ref=REF,
        subject="verified.py",
        actor_ref="vera",
        operation="WRITE_FILE",
        path="packages/vera_core/src/vera_core/verified.py",
        expected_ref_head="head-before",
        expected_blob_id="blob-before",
        content="VERIFIED = True\n",
    )


def execute_mutation(runtime, verifier):
    runtime.start_task("task-verify", task_packet())
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-verify",
        "dep-source",
        mutation_request(),
    )
    dispatch = prepared.provider_dispatch
    authority = verifier.issue(
        effect_id=dispatch.effect_id,
        operation=dispatch.operation,
        request_digest=dispatch.request_digest,
        lifecycle_permit_digest=dispatch.permit.permit_digest,
    )
    adapter.execute(prepared, authority=authority)
    return prepared


def test_required_exact_commit_verification_gates_dependency_and_closeout(tmp_path):
    verification_transport = FakeSourceVerificationTransport()
    _, runtime, verifier, _ = build_runtime(
        tmp_path,
        verification_transport,
    )
    execute_mutation(runtime, verifier)

    before = runtime.assess_task_dependencies("task-verify")[0]
    assert before.status == "PENDING"
    assert "has not run" in before.reason
    closeout_before = runtime.assess_task_closeout(
        "task-verify",
        surfaces={"source": "changed-and-verified"},
    )
    assert closeout_before.ready is False

    receipt = runtime.verify_source_mutation("mutation-verify-1")
    assert receipt.status == "PASS"
    assert receipt.commit_sha == "head-after"
    assert verification_transport.calls == [
        ("head-after", ("ci",)),
    ]

    after = runtime.assess_task_dependencies("task-verify")[0]
    assert after.status == "SATISFIED"
    assert after.evidence_digest is not None
    assert "exact-commit verification" in after.reason

    closeout_after = runtime.assess_task_closeout(
        "task-verify",
        surfaces={"source": "changed-and-verified"},
    )
    assert closeout_after.ready is True


def test_failed_check_remains_pending_and_can_be_reverified(tmp_path):
    verification_transport = FakeSourceVerificationTransport(status="FAIL")
    _, runtime, verifier, _ = build_runtime(
        tmp_path,
        verification_transport,
    )
    execute_mutation(runtime, verifier)

    failed = runtime.verify_source_mutation("mutation-verify-1")
    assert failed.status == "FAIL"
    assessment = runtime.assess_task_dependencies("task-verify")[0]
    assert assessment.status == "PENDING"
    assert "FAIL" in assessment.reason

    verification_transport.status = "PASS"
    passed = runtime.verify_source_mutation("mutation-verify-1")
    assert passed.status == "PASS"
    assert runtime.assess_task_dependencies(
        "task-verify"
    )[0].status == "SATISFIED"


def test_stale_ref_head_is_provenance_mismatch_not_source_success(tmp_path):
    verification_transport = FakeSourceVerificationTransport(
        observed_ref_head="newer-head",
    )
    _, runtime, verifier, _ = build_runtime(
        tmp_path,
        verification_transport,
    )
    execute_mutation(runtime, verifier)

    receipt = runtime.verify_source_mutation("mutation-verify-1")
    assert receipt.status == "STALE_HEAD"
    assessment = runtime.assess_task_dependencies("task-verify")[0]
    assert assessment.status == "PROVENANCE_MISMATCH"
    assert assessment.evidence_digest == receipt.receipt_digest


def test_missing_verification_transport_surfaces_restart_blocker(tmp_path):
    state, runtime, verifier, _ = build_runtime(tmp_path, None)
    execute_mutation(runtime, verifier)

    assessment = runtime.assess_source_verification(
        "mutation-verify-1"
    )
    assert assessment.verification_required is True
    assert assessment.transport_available is False
    assert assessment.passed is False
    with pytest.raises(SourceVerificationError):
        runtime.verify_source_mutation("mutation-verify-1")

    restart = runtime.resume_context()
    source = next(
        item
        for item in restart["source_verification_recovery"]
        if item["mutation_id"] == "mutation-verify-1"
    )
    assert source["passed"] is False
    assert source["transport_available"] is False
    assert state.paths.source_verifications.is_file()
