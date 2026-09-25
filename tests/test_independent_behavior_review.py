from dataclasses import dataclass
import base64
import hashlib
import hmac
import json

import pytest

from vera_core import (
    BehaviorEffectObservation,
    IndependentBehaviorReviewError,
    IndependentBehaviorReviewRequirement,
    IndependentBehaviorReviewSubject,
    IndependentReviewAuthoritySubject,
    JsonFileIndependentBehaviorReviewTransport,
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
PROBE = "heldout-candor-v1"
REVIEW = "review-1"
SUBJECT = "vera-runtime"
CURATOR = "heldout-curator"
EVALUATOR = "outside-evaluator"
AUTHORITY = "review-authority"
EVAL_KEY = "eval-key-v1"
AUTH_KEY = "authority-key-v1"
STIMULUS = "a" * 64
OUTCOME = "b" * 64
PROBE_SET = "c" * 64
DECLARATION = canonical_behavior_declaration_digest(
    {"schema": "TEST_BEHAVIOR_PROFILE_V1", "probe_id": PROBE, "claim": "bounded candor"}
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestVerifier:
    def __init__(self, actor_id: str, key_id: str, secret: bytes):
        self.actor_id = actor_id
        self.key_id = key_id
        self._secret = secret
        self.key_digest = digest(secret)

    def sign(self, subject: bytes) -> str:
        return hmac.new(self._secret, subject, hashlib.sha256).hexdigest()

    def verify(self, subject: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(subject), signature)


@dataclass
class FakeConsumptionTransport:
    consumer_id: str = CONSUMER
    process_instance_id: str = "process-1"
    state_digest: str = "d" * 64

    def observe(self, route_id, expected_target):
        return RuntimeConsumptionObservation(
            consumer_id=self.consumer_id,
            route_id=route_id,
            consumed_target=expected_target,
            route_digest="e" * 64,
            process_instance_id=self.process_instance_id,
            state_digest=self.state_digest,
            evidence_ref="runtime:test",
            available=True,
        )


@dataclass
class FakeBehaviorTransport:
    consumer_id: str = CONSUMER
    process_instance_id: str = "process-1"
    runtime_state_digest: str = "d" * 64

    def observe(self, probe_id, evidence_kind, expected_stimulus_digest, expected_outcome_digest):
        return BehaviorEffectObservation(
            consumer_id=self.consumer_id,
            probe_id=probe_id,
            evidence_kind=evidence_kind,
            process_instance_id=self.process_instance_id,
            runtime_state_digest=self.runtime_state_digest,
            stimulus_digest=expected_stimulus_digest,
            observed_outcome_digest=expected_outcome_digest,
            external_effect_id=None,
            external_effect_receipt_digest=None,
            external_evidence_digest="f" * 64,
            evidence_ref="behavior:test",
            available=True,
        )


def accepted_state(tmp_path):
    state = VeraStateDirectory(tmp_path / "state", project_id=PROJECT, identity_id=IDENTITY)
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m1",
            text="independent review state",
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
        runtime_id="review-runtime",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def packet(evaluator, authority):
    return TaskPacket(
        purpose="Verify held-out independent behavior review.",
        subject="live Vera held-out behavior review",
        completion_state="Independent review is verified-current.",
        evidence_requirements=(
            f"RUNTIME_CONSUME_VERIFY|{CONSUMER}|{ROUTE}|{TARGET}",
            f"BEHAVIOR_EFFECT_VERIFY|{CONSUMER}|{PROBE}|BEHAVIOR|{STIMULUS}|{OUTCOME}",
            (
                f"INDEPENDENT_BEHAVIOR_REVIEW_VERIFY|{CONSUMER}|{PROBE}|{REVIEW}|{SUBJECT}|"
                f"{DECLARATION}|{PROBE_SET}|{CURATOR}|{EVALUATOR}|{EVAL_KEY}|"
                f"{evaluator.key_digest}|{AUTHORITY}|{AUTH_KEY}|{authority.key_digest}"
            ),
        ),
        writable_scope=(),
        non_targets=("self-review", "attestation promoted to independent review"),
        forbidden_shortcuts_or_effects=("Vera must not mint the held-out verdict",),
        priority_order=("independence", "currentness", "provenance"),
        unknowns=(),
        return_shape=("independent review receipt",),
        relevant_surfaces=("runtime consumption", "behavior/effect"),
    )


def runtime_with_review(tmp_path):
    state = accepted_state(tmp_path)
    consumption = FakeConsumptionTransport()
    behavior = FakeBehaviorTransport()
    evaluator = TestVerifier(EVALUATOR, EVAL_KEY, b"external-evaluator-test-key")
    authority = TestVerifier(AUTHORITY, AUTH_KEY, b"external-authority-test-key")
    authority_path = tmp_path / "review-authority.json"
    review_path = tmp_path / "review-result.json"
    transport = JsonFileIndependentBehaviorReviewTransport(
        consumer_id=CONSUMER,
        review_id=REVIEW,
        authority_path=authority_path,
        review_path=review_path,
        authority_verifier=authority,
        evaluator_verifier=evaluator,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        runtime_consumption_transports={CONSUMER: consumption},
        behavior_effect_transports={CONSUMER: behavior},
        independent_behavior_review_transports={(CONSUMER, REVIEW): transport},
    )
    runtime.start_task("task-review", packet(evaluator, authority))
    runtime.verify_task_runtime_consumption("task-review", CONSUMER)
    behavior_receipt = runtime.verify_task_behavior_effect("task-review", CONSUMER, PROBE)
    return runtime, consumption, behavior, evaluator, authority, authority_path, review_path, behavior_receipt


def write_review(
    authority_path,
    review_path,
    evaluator,
    authority,
    behavior_receipt,
    *,
    authority_current=True,
    operationally_separate=True,
    probe_set=PROBE_SET,
    review_nonce="review-nonce-1",
    authority_nonce="authority-nonce-1",
    verdict="PASS",
    provenance=None,
    evaluator_signature_override=None,
):
    currentness = digest(b"evaluator-currentness-v1")
    a = IndependentReviewAuthoritySubject(
        review_id=REVIEW,
        subject_actor_id=SUBJECT,
        held_out_probe_set_digest=probe_set,
        probe_curator_id=CURATOR,
        evaluator_id=EVALUATOR,
        evaluator_key_id=EVAL_KEY,
        evaluator_key_digest=evaluator.key_digest,
        authority_id=AUTHORITY,
        authority_key_id=AUTH_KEY,
        authority_key_digest=authority.key_digest,
        evaluator_currentness_digest=currentness,
        operationally_separate=operationally_separate,
        current=authority_current,
        authority_nonce=authority_nonce,
    )
    authority_payload = a.canonical_body() | {"signature": authority.sign(a.canonical_bytes())}
    authority_raw = json.dumps(authority_payload, separators=(",", ":")).encode()
    authority_path.write_bytes(authority_raw)

    result = b'{"heldout":"result"}'
    result_receipt = b'{"review":"receipt"}'
    provenance = provenance or {"runner": "outside", "probe_visibility": "held-out"}
    r = IndependentBehaviorReviewSubject(
        consumer_id=CONSUMER,
        probe_id=PROBE,
        review_id=REVIEW,
        declaration_digest=DECLARATION,
        held_out_probe_set_digest=probe_set,
        probe_curator_id=CURATOR,
        behavior_effect_receipt_digest=behavior_receipt.receipt_digest,
        process_instance_id=behavior_receipt.observed_process_instance_id,
        runtime_state_digest=behavior_receipt.observed_runtime_state_digest,
        stimulus_digest=behavior_receipt.observed_stimulus_digest,
        outcome_digest=behavior_receipt.observed_outcome_digest,
        evaluator_id=EVALUATOR,
        evaluator_key_id=EVAL_KEY,
        evaluator_key_digest=evaluator.key_digest,
        evaluator_currentness_digest=currentness,
        authority_subject_digest=a.digest,
        authority_evidence_digest=digest(authority_raw),
        review_nonce=review_nonce,
        verdict=verdict,
        result_digest=digest(result),
        result_receipt_digest=digest(result_receipt),
        review_provenance_digest=digest(json.dumps(provenance, sort_keys=True, separators=(",", ":")).encode()),
    )
    signature = evaluator.sign(r.canonical_bytes()) if evaluator_signature_override is None else evaluator_signature_override
    body = r.canonical_body()
    review_payload = {
        "schema": "VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_EVIDENCE_V1",
        **{k: v for k, v in body.items() if k not in {"schema", "result_digest", "result_receipt_digest", "review_provenance_digest"}},
        "result_b64": base64.b64encode(result).decode(),
        "result_receipt_b64": base64.b64encode(result_receipt).decode(),
        "provenance": provenance,
        "signature": signature,
    }
    review_path.write_text(json.dumps(review_payload, separators=(",", ":")), encoding="utf-8")


def surfaces():
    return {"runtime consumption": "verified-current", "behavior/effect": "verified-current"}


def test_independent_review_binds_heldout_external_roles_and_closeout(tmp_path):
    runtime, _, _, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt)
    receipt = runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW)
    assert receipt.status == "PASS"
    assessment = runtime.assess_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW)
    assert assessment.passed is True
    assert assessment.current_operationally_separate is True
    assert assessment.current_signatures_valid is True
    assert runtime.assess_task_closeout("task-review", surfaces=surfaces()).ready is True
    closed = runtime.close_task(
        "task-review", "close-review", surfaces=surfaces(),
        evidence_refs=("operator requested independent review",),
        claim_ceiling="INDEPENDENT_HELD_OUT_BEHAVIOR_REVIEW",
        next_frontier="live external reviewer execution",
    )
    assert any(
        ref.startswith(f"task-independent-behavior-review:{CONSUMER}:{PROBE}:{REVIEW}:")
        for ref in closed.closeout.evidence_refs
    )


def test_forged_evaluator_verdict_fails(tmp_path):
    runtime, _, _, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt, evaluator_signature_override="0" * 64)
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "FAIL"


def test_stale_evaluator_currentness_invalidates_stored_pass(tmp_path):
    runtime, _, _, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt)
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "PASS"
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt,
                 authority_current=False, authority_nonce="authority-nonce-2", review_nonce="review-nonce-2")
    assessment = runtime.assess_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW)
    assert assessment.passed is False
    assert assessment.current_authority_current is False


def test_wrong_heldout_probe_set_fails(tmp_path):
    runtime, _, _, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt, probe_set="9" * 64)
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "FAIL"


def test_independent_review_nonce_replay_is_rejected(tmp_path):
    runtime, _, _, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt, review_nonce="shared-review-nonce")
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "PASS"
    runtime.start_task("task-review-2", packet(evaluator, authority))
    runtime.verify_task_runtime_consumption("task-review-2", CONSUMER)
    second = runtime.verify_task_behavior_effect("task-review-2", CONSUMER, PROBE)
    write_review(authority_path, review_path, evaluator, authority, second,
                 review_nonce="shared-review-nonce", authority_nonce="authority-nonce-2")
    with pytest.raises(IndependentBehaviorReviewError, match="nonce replay"):
        runtime.verify_task_independent_behavior_review("task-review-2", CONSUMER, PROBE, REVIEW)


def test_missing_evidence_is_unavailable(tmp_path):
    runtime, _, _, _, _, _, _, _ = runtime_with_review(tmp_path)
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "UNAVAILABLE"


def test_stale_process_invalidates_independent_review(tmp_path):
    runtime, consumption, behavior, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt)
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "PASS"
    consumption.process_instance_id = "process-2"
    consumption.state_digest = "7" * 64
    behavior.process_instance_id = "process-2"
    behavior.runtime_state_digest = "7" * 64
    assessment = runtime.assess_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW)
    assert assessment.passed is False
    assert assessment.behavior_effect_current is False


def test_changed_review_provenance_invalidates_exact_stored_pass(tmp_path):
    runtime, _, _, evaluator, authority, authority_path, review_path, behavior_receipt = runtime_with_review(tmp_path)
    write_review(authority_path, review_path, evaluator, authority, behavior_receipt)
    assert runtime.verify_task_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).status == "PASS"
    write_review(
        authority_path, review_path, evaluator, authority, behavior_receipt,
        review_nonce="review-nonce-2", authority_nonce="authority-nonce-2",
        provenance={"runner": "outside", "probe_visibility": "held-out", "revision": 2},
    )
    assert runtime.assess_independent_behavior_review("task-review", CONSUMER, PROBE, REVIEW).passed is False


def test_requirement_rejects_collapsed_review_roles():
    evaluator = TestVerifier(EVALUATOR, EVAL_KEY, b"external-evaluator-test-key")
    authority = TestVerifier(AUTHORITY, AUTH_KEY, b"external-authority-test-key")
    raw = (
        f"INDEPENDENT_BEHAVIOR_REVIEW_VERIFY|{CONSUMER}|{PROBE}|{REVIEW}|{SUBJECT}|"
        f"{DECLARATION}|{PROBE_SET}|{SUBJECT}|{EVALUATOR}|{EVAL_KEY}|{evaluator.key_digest}|"
        f"{AUTHORITY}|{AUTH_KEY}|{authority.key_digest}"
    )
    with pytest.raises(IndependentBehaviorReviewError, match="distinct subject"):
        IndependentBehaviorReviewRequirement.parse(raw)
