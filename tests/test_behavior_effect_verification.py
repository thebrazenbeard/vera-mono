from dataclasses import dataclass
import json

import pytest

from vera_core import (
    BehaviorEffectObservation,
    BehaviorEffectVerificationError,
    JsonFileBehaviorEffectVerificationTransport,
    QualifiedVeraRuntime,
    RuntimeConsumptionObservation,
    TaskPacket,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
CONSUMER = "vera-process"
ROUTE = "vera-active"
TARGET = "vera-mono@0.1.0"
PROBE = "candor-boundary-v1"
STIMULUS = "a" * 64
OUTCOME = "b" * 64


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
            external_effect_receipt_digest=(
                self.external_effect_receipt_digest
            ),
            external_evidence_digest=self.external_evidence_digest,
            evidence_ref="behavior:test",
            available=True,
        )


def packet(*, kind="BEHAVIOR", include_runtime=True):
    requirements = [
        (
            f"BEHAVIOR_EFFECT_VERIFY|{CONSUMER}|{PROBE}|{kind}|"
            f"{STIMULUS}|{OUTCOME}"
        )
    ]
    surfaces = ["behavior/effect"]
    if include_runtime:
        requirements.insert(
            0,
            f"RUNTIME_CONSUME_VERIFY|{CONSUMER}|{ROUTE}|{TARGET}",
        )
        surfaces.insert(0, "runtime consumption")
    return TaskPacket(
        purpose="Verify live behavior/effect from exact host evidence.",
        subject="live Vera behavior qualification",
        completion_state="Behavior/effect is verified-current.",
        evidence_requirements=tuple(requirements),
        writable_scope=(),
        non_targets=("runtime consumption as behavioral qualification",),
        forbidden_shortcuts_or_effects=(
            "do not infer behavior/effect PASS from runtime consumption",
        ),
        priority_order=("behavioral evidence", "currentness"),
        unknowns=(),
        return_shape=("behavior/effect receipt",),
        relevant_surfaces=tuple(surfaces),
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
            text="behavior verification state",
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
        runtime_id="behavior-runtime",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def runtime_with_transports(tmp_path, *, kind="BEHAVIOR"):
    state = accepted_state(tmp_path)
    consumption = FakeConsumptionTransport()
    behavior = FakeBehaviorTransport(evidence_kind=kind)
    if kind == "EFFECT":
        behavior.external_effect_id = "external:test:effect-1"
        behavior.external_effect_receipt_digest = "f" * 64
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        runtime_consumption_transports={CONSUMER: consumption},
        behavior_effect_transports={CONSUMER: behavior},
    )
    runtime.start_task("task-behavior", packet(kind=kind))
    return state, runtime, consumption, behavior


def surfaces():
    return {
        "runtime consumption": "verified-current",
        "behavior/effect": "verified-current",
    }


def test_runtime_consumption_pass_does_not_imply_behavior_pass(tmp_path):
    _, runtime, _, _ = runtime_with_transports(tmp_path)

    runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    before = runtime.assess_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert before.passed is False
    assert before.latest_status is None

    closeout = runtime.assess_task_closeout(
        "task-behavior",
        surfaces=surfaces(),
    )
    assert closeout.ready is False
    assert any(
        "behavior/effect probes are not verified-current" in reason
        for reason in closeout.reasons
    )


def test_behavior_pass_requires_same_live_consumed_process_and_external_evidence(
    tmp_path,
):
    _, runtime, _, behavior = runtime_with_transports(tmp_path)
    runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    receipt = runtime.verify_task_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert receipt.status == "PASS"
    assert receipt.observed_process_instance_id == "process-1"
    assert receipt.observed_runtime_state_digest == "c" * 64
    assert receipt.external_evidence_digest == "e" * 64

    assessment = runtime.assess_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert assessment.passed is True
    assert assessment.runtime_consumption_current is True
    assert assessment.current_matches_receipt is True

    behavior.external_evidence_digest = "9" * 64
    changed = runtime.assess_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert changed.passed is False
    assert changed.current_matches_receipt is False


def test_consumed_runtime_change_invalidates_behavior_qualification(tmp_path):
    _, runtime, consumption, behavior = runtime_with_transports(tmp_path)
    runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    runtime.verify_task_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )

    consumption.process_instance_id = "process-2"
    consumption.state_digest = "7" * 64
    behavior.process_instance_id = "process-2"
    behavior.runtime_state_digest = "7" * 64

    assessment = runtime.assess_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert assessment.passed is False
    assert assessment.runtime_consumption_current is False
    assert "historical evidence only" in assessment.reason


def test_behavior_verification_refuses_missing_runtime_consumption_prerequisite(
    tmp_path,
):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        runtime_consumption_transports={CONSUMER: FakeConsumptionTransport()},
        behavior_effect_transports={CONSUMER: FakeBehaviorTransport()},
    )
    runtime.start_task(
        "task-behavior",
        packet(include_runtime=False),
    )
    with pytest.raises(
        BehaviorEffectVerificationError,
        match="RUNTIME_CONSUME_VERIFY",
    ):
        runtime.verify_task_behavior_effect(
            "task-behavior",
            CONSUMER,
            PROBE,
        )


def test_effect_qualification_requires_exact_external_effect_receipt(tmp_path):
    _, runtime, _, behavior = runtime_with_transports(
        tmp_path,
        kind="EFFECT",
    )
    runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    receipt = runtime.verify_task_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert receipt.status == "PASS"
    assert receipt.external_effect_id == "external:test:effect-1"
    assert receipt.external_effect_receipt_digest == "f" * 64

    behavior.external_effect_receipt_digest = None
    with pytest.raises(
        BehaviorEffectVerificationError,
        match="external_effect_receipt_digest",
    ):
        runtime.assess_behavior_effect(
            "task-behavior",
            CONSUMER,
            PROBE,
        )


def test_stored_behavior_pass_without_live_external_transport_is_historical(
    tmp_path,
):
    state, runtime, _, _ = runtime_with_transports(tmp_path)
    runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    receipt = runtime.verify_task_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert receipt.status == "PASS"

    restarted = QualifiedVeraRuntime.from_state_directory(
        state,
        runtime_consumption_transports={CONSUMER: FakeConsumptionTransport()},
    )
    assessment = restarted.assess_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.transport_available is False
    assert assessment.passed is False
    assert "historical evidence only" not in assessment.reason
    assert "no host/external evidence transport" in assessment.reason

    recovery = restarted.resume_context()["behavior_effect_recovery"]
    assert len(recovery) == 1
    assert recovery[0]["probe_id"] == PROBE
    assert recovery[0]["passed"] is False


def test_behavior_effect_jointly_gates_closeout_and_evidence_refs(tmp_path):
    _, runtime, _, _ = runtime_with_transports(tmp_path)
    runtime_receipt = runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    behavior_receipt = runtime.verify_task_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    ready = runtime.assess_task_closeout(
        "task-behavior",
        surfaces=surfaces(),
    )
    assert ready.ready is True

    closed = runtime.close_task(
        "task-behavior",
        "close-behavior",
        surfaces=surfaces(),
        evidence_refs=("operator requested behavioral qualification",),
        claim_ceiling=(
            "LIVE_BEHAVIOR_EFFECT_VERIFIED_FROM_EXTERNAL_EVIDENCE"
        ),
        next_frontier="none",
    )
    assert closed.closed is True
    assert (
        f"task-runtime-consumption:{CONSUMER}:"
        f"{runtime_receipt.receipt_digest}"
        in closed.closeout.evidence_refs
    )
    assert (
        f"task-behavior-effect:{CONSUMER}:{PROBE}:"
        f"{behavior_receipt.receipt_digest}"
        in closed.closeout.evidence_refs
    )


def test_behavior_surface_cannot_close_out_of_scope_when_required(tmp_path):
    _, runtime, _, _ = runtime_with_transports(tmp_path)
    runtime.verify_task_runtime_consumption(
        "task-behavior",
        CONSUMER,
    )
    runtime.verify_task_behavior_effect(
        "task-behavior",
        CONSUMER,
        PROBE,
    )
    assessment = runtime.assess_task_closeout(
        "task-behavior",
        surfaces={
            "runtime consumption": "verified-current",
            "behavior/effect": "out-of-scope",
        },
    )
    assert assessment.ready is False
    assert any(
        "behavior/effect evidence cannot close" in reason
        for reason in assessment.reasons
    )


def test_json_behavior_transport_hashes_exact_host_evidence_bytes(tmp_path):
    state_file = tmp_path / "behavior.json"
    payload = {
        "consumer_id": CONSUMER,
        "probe_id": PROBE,
        "evidence_kind": "BEHAVIOR",
        "process_instance_id": "process-1",
        "runtime_state_digest": "c" * 64,
        "stimulus_digest": STIMULUS,
        "outcome_digest": OUTCOME,
    }
    state_file.write_text(
        json.dumps(payload, separators=(",", ":")),
        encoding="utf-8",
    )
    transport = JsonFileBehaviorEffectVerificationTransport(
        consumer_id=CONSUMER,
        path=state_file,
    )
    first = transport.observe(
        PROBE,
        "BEHAVIOR",
        STIMULUS,
        OUTCOME,
    )
    assert first.available is True
    assert first.external_evidence_digest is not None
    assert len(first.external_evidence_digest) == 64
    assert first.evidence_ref == str(state_file.resolve())

    state_file.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    second = transport.observe(
        PROBE,
        "BEHAVIOR",
        STIMULUS,
        OUTCOME,
    )
    assert second.external_evidence_digest != first.external_evidence_digest
