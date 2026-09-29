from dataclasses import dataclass
import base64
import hashlib
import json

import pytest

from vera_core import (
    BehaviorAttestationError,
    BehaviorAttestationSubject,
    BehaviorEffectObservation,
    HmacBehaviorEvidenceAttestationVerifier,
    JsonFileBehaviorAttestationTransport,
    QualifiedVeraRuntime,
    RuntimeConsumptionObservation,
    TaskPacket,
    VeraStateDirectory,
    canonical_behavior_declaration_digest,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
CONSUMER = "vera-process"
ROUTE = "vera-active"
TARGET = "vera-mono@0.1.0"
PROBE = "candor-boundary-v1"
PROVIDER = "external-evaluator"
KEY_ID = "eval-key-v1"
STIMULUS = "a" * 64
OUTCOME = "b" * 64
DECLARATION = canonical_behavior_declaration_digest(
    {
        "schema": "TEST_BEHAVIOR_PROFILE_V1",
        "probe_id": PROBE,
        "claim": "responds with the declared outcome",
    }
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FakeConsumptionTransport:
    consumer_id: str = CONSUMER
    process_instance_id: str = "process-1"
    state_digest: str = "c" * 64
    available: bool = True

    def observe(self, route_id, expected_target):
        if not self.available:
            return RuntimeConsumptionObservation(
                consumer_id=self.consumer_id,
                route_id=None,
                consumed_target=None,
                route_digest=None,
                process_instance_id=None,
                state_digest=None,
                evidence_ref=None,
                available=False,
            )
        return RuntimeConsumptionObservation(
            consumer_id=self.consumer_id,
            route_id=route_id,
            consumed_target=expected_target,
            route_digest="d" * 64,
            process_instance_id=self.process_instance_id,
            state_digest=self.state_digest,
            evidence_ref="runtime:test",
            available=True,
        )


@dataclass
class FakeBehaviorTransport:
    consumer_id: str = CONSUMER
    process_instance_id: str = "process-1"
    runtime_state_digest: str = "c" * 64
    outcome_digest: str = OUTCOME
    external_evidence_digest: str = "e" * 64
    evidence_kind: str = "BEHAVIOR"
    external_effect_id: str | None = None
    external_effect_receipt_digest: str | None = None
    available: bool = True

    def observe(
        self,
        probe_id,
        evidence_kind,
        expected_stimulus_digest,
        expected_outcome_digest,
    ):
        del expected_outcome_digest
        if not self.available:
            return BehaviorEffectObservation(
                consumer_id=self.consumer_id,
                probe_id=probe_id,
                evidence_kind=evidence_kind,
                process_instance_id=None,
                runtime_state_digest=None,
                stimulus_digest=None,
                observed_outcome_digest=None,
                external_effect_id=None,
                external_effect_receipt_digest=None,
                external_evidence_digest=None,
                evidence_ref=None,
                available=False,
            )
        return BehaviorEffectObservation(
            consumer_id=self.consumer_id,
            probe_id=probe_id,
            evidence_kind=self.evidence_kind,
            process_instance_id=self.process_instance_id,
            runtime_state_digest=self.runtime_state_digest,
            stimulus_digest=expected_stimulus_digest,
            observed_outcome_digest=self.outcome_digest,
            external_effect_id=self.external_effect_id,
            external_effect_receipt_digest=self.external_effect_receipt_digest,
            external_evidence_digest=self.external_evidence_digest,
            evidence_ref="behavior:test",
            available=True,
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
            text="behavior attestation state",
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
        runtime_id="attestation-runtime",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def packet(key_digest, *, kind="BEHAVIOR", effect_subject=None):
    effect_value = effect_subject or "NONE"
    return TaskPacket(
        purpose="Verify declaration-bound external behavior attestation.",
        subject="live Vera behavior attestation",
        completion_state="Behavior attestation is verified-current.",
        evidence_requirements=(
            f"RUNTIME_CONSUME_VERIFY|{CONSUMER}|{ROUTE}|{TARGET}",
            (
                f"BEHAVIOR_EFFECT_VERIFY|{CONSUMER}|{PROBE}|{kind}|"
                f"{STIMULUS}|{OUTCOME}"
            ),
            (
                f"BEHAVIOR_ATTEST_VERIFY|{CONSUMER}|{PROBE}|"
                f"{DECLARATION}|{PROVIDER}|{KEY_ID}|{key_digest}|"
                f"{effect_value}"
            ),
        ),
        writable_scope=(),
        non_targets=("internal behavior PASS as external attestation",),
        forbidden_shortcuts_or_effects=(
            "do not infer verifier-bound provenance from local runtime state",
        ),
        priority_order=("external provenance", "currentness"),
        unknowns=(),
        return_shape=("behavior attestation receipt",),
        relevant_surfaces=("runtime consumption", "behavior/effect"),
    )


def runtime_with_attestation(tmp_path, *, kind="BEHAVIOR"):
    state = accepted_state(tmp_path)
    consumption = FakeConsumptionTransport()
    behavior = FakeBehaviorTransport(evidence_kind=kind)
    effect_receipt = None
    effect_subject = None
    if kind == "EFFECT":
        effect_receipt = b'{"effect":"committed","provider":"external"}'
        effect_subject = digest(b"external-effect-subject-v1")
        behavior.external_effect_id = "external:test:effect-1"
        behavior.external_effect_receipt_digest = digest(effect_receipt)
    verifier = HmacBehaviorEvidenceAttestationVerifier(
        provider_id=PROVIDER,
        key_id=KEY_ID,
        secret=b"behavior-attestation-test-secret",
    )
    path = tmp_path / "behavior-attestation.json"
    attestation = JsonFileBehaviorAttestationTransport(
        consumer_id=CONSUMER,
        path=path,
        verifier=verifier,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        runtime_consumption_transports={CONSUMER: consumption},
        behavior_effect_transports={CONSUMER: behavior},
        behavior_attestation_transports={
            (CONSUMER, PROVIDER): attestation
        },
    )
    runtime.start_task(
        "task-attestation",
        packet(
            verifier.key_digest,
            kind=kind,
            effect_subject=effect_subject,
        ),
    )
    runtime.verify_task_runtime_consumption(
        "task-attestation", CONSUMER
    )
    behavior_receipt = runtime.verify_task_behavior_effect(
        "task-attestation", CONSUMER, PROBE
    )
    return (
        runtime,
        consumption,
        behavior,
        verifier,
        path,
        behavior_receipt,
        effect_receipt,
        effect_subject,
    )


def write_attestation(
    path,
    verifier,
    behavior_receipt,
    *,
    nonce="nonce-1",
    declaration=DECLARATION,
    stimulus=STIMULUS,
    outcome=OUTCOME,
    raw_response=b'{"answer":"bounded"}',
    effect_receipt=None,
    effect_subject=None,
    signature_override=None,
):
    subject = BehaviorAttestationSubject(
        consumer_id=CONSUMER,
        probe_id=PROBE,
        evidence_kind=behavior_receipt.evidence_kind,
        declaration_digest=declaration,
        behavior_effect_receipt_digest=behavior_receipt.receipt_digest,
        process_instance_id=behavior_receipt.observed_process_instance_id,
        runtime_state_digest=behavior_receipt.observed_runtime_state_digest,
        stimulus_digest=stimulus,
        outcome_digest=outcome,
        raw_response_digest=digest(raw_response),
        provider_id=PROVIDER,
        provider_key_id=KEY_ID,
        provider_key_digest=verifier.key_digest,
        attestation_nonce=nonce,
        external_effect_id=behavior_receipt.external_effect_id,
        external_effect_receipt_digest=(
            None if effect_receipt is None else digest(effect_receipt)
        ),
        external_effect_subject_digest=effect_subject,
    )
    signature = (
        verifier.sign(subject.canonical_bytes())
        if signature_override is None
        else signature_override
    )
    payload = {
        "schema": "VERA_MONO_EXTERNAL_BEHAVIOR_ATTESTATION_V1",
        "consumer_id": subject.consumer_id,
        "probe_id": subject.probe_id,
        "evidence_kind": subject.evidence_kind,
        "declaration_digest": subject.declaration_digest,
        "behavior_effect_receipt_digest": subject.behavior_effect_receipt_digest,
        "process_instance_id": subject.process_instance_id,
        "runtime_state_digest": subject.runtime_state_digest,
        "stimulus_digest": subject.stimulus_digest,
        "outcome_digest": subject.outcome_digest,
        "raw_response_b64": base64.b64encode(raw_response).decode("ascii"),
        "provider_id": subject.provider_id,
        "provider_key_id": subject.provider_key_id,
        "provider_key_digest": subject.provider_key_digest,
        "attestation_nonce": subject.attestation_nonce,
        "external_effect_id": subject.external_effect_id,
        "external_effect_receipt_b64": (
            None
            if effect_receipt is None
            else base64.b64encode(effect_receipt).decode("ascii")
        ),
        "external_effect_subject_digest": subject.external_effect_subject_digest,
        "signature": signature,
    }
    path.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )


def surfaces():
    return {
        "runtime consumption": "verified-current",
        "behavior/effect": "verified-current",
    }


def test_attestation_binds_declaration_provider_and_closeout(tmp_path):
    runtime, _, _, verifier, path, behavior_receipt, _, _ = (
        runtime_with_attestation(tmp_path)
    )
    write_attestation(path, verifier, behavior_receipt)
    receipt = runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert receipt.status == "PASS"
    assert receipt.expected_declaration_digest == DECLARATION
    assert receipt.expected_provider_id == PROVIDER
    assert receipt.observed_signature_valid is True

    assessment = runtime.assess_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert assessment.passed is True

    ready = runtime.assess_task_closeout(
        "task-attestation",
        surfaces=surfaces(),
    )
    assert ready.ready is True
    closed = runtime.close_task(
        "task-attestation",
        "close-attestation",
        surfaces=surfaces(),
        evidence_refs=("operator requested external attestation",),
        claim_ceiling="EXTERNALLY_ATTESTED_BEHAVIOR_PROVENANCE",
        next_frontier="independent behavioral review",
    )
    assert any(
        ref.startswith(
            f"task-behavior-attestation:{CONSUMER}:{PROBE}:"
        )
        for ref in closed.closeout.evidence_refs
    )


def test_stale_profile_invalidates_live_attestation(tmp_path):
    runtime, _, _, verifier, path, behavior_receipt, _, _ = (
        runtime_with_attestation(tmp_path)
    )
    write_attestation(path, verifier, behavior_receipt)
    assert runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    ).status == "PASS"

    write_attestation(
        path,
        verifier,
        behavior_receipt,
        declaration="7" * 64,
        nonce="nonce-2",
    )
    assessment = runtime.assess_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert assessment.passed is False


def test_forged_attestation_signature_records_fail(tmp_path):
    runtime, _, _, verifier, path, behavior_receipt, _, _ = (
        runtime_with_attestation(tmp_path)
    )
    write_attestation(
        path,
        verifier,
        behavior_receipt,
        signature_override="0" * 64,
    )
    receipt = runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert receipt.status == "FAIL"
    assert receipt.observed_signature_valid is False


def test_attestation_nonce_replay_is_rejected(tmp_path):
    runtime, _, _, verifier, path, behavior_receipt, _, _ = (
        runtime_with_attestation(tmp_path)
    )
    write_attestation(path, verifier, behavior_receipt, nonce="shared-nonce")
    assert runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    ).status == "PASS"

    runtime.start_task(
        "task-attestation-2",
        packet(verifier.key_digest),
    )
    runtime.verify_task_runtime_consumption(
        "task-attestation-2", CONSUMER
    )
    second_behavior = runtime.verify_task_behavior_effect(
        "task-attestation-2", CONSUMER, PROBE
    )
    write_attestation(
        path,
        verifier,
        second_behavior,
        nonce="shared-nonce",
    )
    with pytest.raises(
        BehaviorAttestationError,
        match="nonce replay",
    ):
        runtime.verify_task_behavior_attestation(
            "task-attestation-2", CONSUMER, PROBE
        )


def test_missing_or_mismatched_external_evidence_does_not_pass(tmp_path):
    runtime, _, _, verifier, path, behavior_receipt, _, _ = (
        runtime_with_attestation(tmp_path)
    )
    missing = runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert missing.status == "UNAVAILABLE"

    write_attestation(
        path,
        verifier,
        behavior_receipt,
        nonce="nonce-mismatch",
        stimulus="8" * 64,
        outcome="9" * 64,
    )
    mismatched = runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert mismatched.status == "FAIL"


def test_stale_process_invalidates_attestation_via_behavior_prerequisite(
    tmp_path,
):
    (
        runtime,
        consumption,
        behavior,
        verifier,
        path,
        behavior_receipt,
        _,
        _,
    ) = runtime_with_attestation(tmp_path)
    write_attestation(path, verifier, behavior_receipt)
    assert runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    ).status == "PASS"

    consumption.process_instance_id = "process-2"
    consumption.state_digest = "7" * 64
    behavior.process_instance_id = "process-2"
    behavior.runtime_state_digest = "7" * 64

    assessment = runtime.assess_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert assessment.passed is False
    assert assessment.behavior_effect_current is False


def test_effect_attestation_cross_binds_external_effect_subject(tmp_path):
    (
        runtime,
        _,
        _,
        verifier,
        path,
        behavior_receipt,
        effect_receipt,
        effect_subject,
    ) = runtime_with_attestation(tmp_path, kind="EFFECT")
    write_attestation(
        path,
        verifier,
        behavior_receipt,
        effect_receipt=effect_receipt,
        effect_subject=effect_subject,
    )
    assert runtime.verify_task_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    ).status == "PASS"

    write_attestation(
        path,
        verifier,
        behavior_receipt,
        nonce="nonce-wrong-subject",
        effect_receipt=effect_receipt,
        effect_subject="6" * 64,
    )
    assessment = runtime.assess_behavior_attestation(
        "task-attestation", CONSUMER, PROBE
    )
    assert assessment.passed is False
