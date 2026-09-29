from dataclasses import dataclass
import json

import pytest

from vera_core import (
    JsonFileRuntimeConsumptionTransport,
    QualifiedVeraRuntime,
    RouteObservation,
    RuntimeConsumptionObservation,
    RuntimeConsumptionVerificationError,
    TaskPacket,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
ROUTE = "vera-active"
TARGET = "vera-mono@0.1.0"
CONSUMER = "vera-process"


@dataclass
class FakeRouteTransport:
    route_id: str = ROUTE
    selected_target: str = TARGET
    route_digest: str = "a" * 64
    available: bool = True

    def observe(self, expected_target):
        del expected_target
        if not self.available:
            return RouteObservation(
                route_id=self.route_id,
                selected_target=None,
                route_digest=None,
                evidence_ref=None,
                available=False,
            )
        return RouteObservation(
            route_id=self.route_id,
            selected_target=self.selected_target,
            route_digest=self.route_digest,
            evidence_ref="route:test",
            available=True,
        )


@dataclass
class FakeConsumptionTransport:
    consumer_id: str = CONSUMER
    route_id: str = ROUTE
    consumed_target: str = TARGET
    route_digest: str = "a" * 64
    process_instance_id: str = "process-1"
    state_digest: str = "b" * 64
    available: bool = True

    def __post_init__(self):
        self.calls = []

    def observe(self, route_id, expected_target):
        self.calls.append((route_id, expected_target))
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
            route_id=self.route_id,
            consumed_target=self.consumed_target,
            route_digest=self.route_digest,
            process_instance_id=self.process_instance_id,
            state_digest=self.state_digest,
            evidence_ref="runtime:test",
            available=True,
        )


def packet(*, include_route=True):
    requirements = [
        f"RUNTIME_CONSUME_VERIFY|{CONSUMER}|{ROUTE}|{TARGET}",
    ]
    surfaces = ["runtime consumption"]
    if include_route:
        requirements.insert(0, f"ROUTE_VERIFY|{ROUTE}|{TARGET}")
        surfaces.insert(0, "current route")
    return TaskPacket(
        purpose="Verify the live Vera runtime consumes the selected target.",
        subject="active Vera runtime consumption",
        completion_state="Runtime consumption is verified-current.",
        evidence_requirements=tuple(requirements),
        writable_scope=(),
        non_targets=("behavioral qualification", "deployment"),
        forbidden_shortcuts_or_effects=(
            "do not infer runtime consumption from installation or route alone",
        ),
        priority_order=("currentness", "exactness"),
        unknowns=(),
        return_shape=("runtime consumption receipt",),
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
            text="runtime consumption verification state",
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
        runtime_id="runtime-consumption",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def runtime_with_transports(tmp_path, *, include_route=True):
    state = accepted_state(tmp_path)
    route = FakeRouteTransport()
    consumer = FakeConsumptionTransport()
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        route_verification_transports=(
            {ROUTE: route} if include_route else None
        ),
        runtime_consumption_transports={CONSUMER: consumer},
    )
    runtime.start_task("task-runtime", packet(include_route=include_route))
    return state, runtime, route, consumer


def surfaces(*, include_route=True):
    result = {"runtime consumption": "verified-current"}
    if include_route:
        result["current route"] = "verified-current"
    return result


def test_runtime_consumption_requires_declared_route_to_be_current(tmp_path):
    _, runtime, _, _ = runtime_with_transports(tmp_path)

    with pytest.raises(RuntimeConsumptionVerificationError):
        runtime.verify_task_runtime_consumption(
            "task-runtime",
            CONSUMER,
        )

    route_receipt = runtime.verify_task_route("task-runtime", ROUTE)
    assert route_receipt.status == "PASS"

    consumption = runtime.verify_task_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert consumption.status == "PASS"
    assert consumption.observed_route_id == ROUTE
    assert consumption.consumed_target == TARGET
    assert consumption.route_digest == route_receipt.route_digest

    assessment = runtime.assess_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert assessment.passed is True
    assert assessment.route_verification_required is True
    assert assessment.route_verified_current is True


def test_runtime_consumption_and_route_jointly_gate_closeout(tmp_path):
    _, runtime, _, _ = runtime_with_transports(tmp_path)

    before = runtime.assess_task_closeout(
        "task-runtime",
        surfaces=surfaces(),
    )
    assert before.ready is False

    runtime.verify_task_route("task-runtime", ROUTE)
    still_blocked = runtime.assess_task_closeout(
        "task-runtime",
        surfaces=surfaces(),
    )
    assert still_blocked.ready is False
    assert any(
        "runtime consumers are not verified-current" in reason
        for reason in still_blocked.reasons
    )

    receipt = runtime.verify_task_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    ready = runtime.assess_task_closeout(
        "task-runtime",
        surfaces=surfaces(),
    )
    assert ready.ready is True

    closed = runtime.close_task(
        "task-runtime",
        "close-runtime",
        surfaces=surfaces(),
        evidence_refs=("operator requested runtime verification",),
        claim_ceiling="RUNTIME_CONSUMPTION_VERIFIED_NOT_BEHAVIOR",
        next_frontier="verify behavior/effect separately",
    )
    assert closed.closed is True
    assert (
        f"task-runtime-consumption:{CONSUMER}:{receipt.receipt_digest}"
        in closed.closeout.evidence_refs
    )


def test_process_or_runtime_state_change_invalidates_stored_pass(tmp_path):
    _, runtime, _, consumer = runtime_with_transports(tmp_path)
    runtime.verify_task_route("task-runtime", ROUTE)
    runtime.verify_task_runtime_consumption("task-runtime", CONSUMER)
    assert runtime.assess_runtime_consumption(
        "task-runtime",
        CONSUMER,
    ).passed is True

    consumer.process_instance_id = "process-2"
    consumer.state_digest = "c" * 64
    assessment = runtime.assess_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.current_matches_receipt is False
    assert assessment.passed is False


def test_route_digest_change_invalidates_runtime_consumption_even_if_target_same(tmp_path):
    _, runtime, route, consumer = runtime_with_transports(tmp_path)
    runtime.verify_task_route("task-runtime", ROUTE)
    runtime.verify_task_runtime_consumption("task-runtime", CONSUMER)

    route.route_digest = "d" * 64
    # The running consumer still reports the old route digest.
    assert consumer.route_digest == "a" * 64
    assessment = runtime.assess_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert assessment.current_matches_receipt is True
    assert assessment.route_verified_current is False
    assert assessment.passed is False


def test_stored_consumption_pass_without_live_transport_is_not_current(tmp_path):
    state, runtime, _, _ = runtime_with_transports(tmp_path)
    runtime.verify_task_route("task-runtime", ROUTE)
    receipt = runtime.verify_task_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert receipt.status == "PASS"

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    assessment = restarted.assess_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.transport_available is False
    assert assessment.passed is False

    recovery = restarted.resume_context()["runtime_consumption_recovery"]
    assert len(recovery) == 1
    assert recovery[0]["consumer_id"] == CONSUMER
    assert recovery[0]["passed"] is False


def test_runtime_consumption_can_be_verified_without_route_requirement(tmp_path):
    _, runtime, _, _ = runtime_with_transports(
        tmp_path,
        include_route=False,
    )
    receipt = runtime.verify_task_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert receipt.status == "PASS"
    assessment = runtime.assess_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assert assessment.route_verification_required is False
    assert assessment.route_verified_current is None
    assert assessment.passed is True
    assert runtime.assess_task_closeout(
        "task-runtime",
        surfaces=surfaces(include_route=False),
    ).ready is True


def test_runtime_consumption_surface_cannot_close_out_of_scope(tmp_path):
    _, runtime, _, _ = runtime_with_transports(
        tmp_path,
        include_route=False,
    )
    runtime.verify_task_runtime_consumption(
        "task-runtime",
        CONSUMER,
    )
    assessment = runtime.assess_task_closeout(
        "task-runtime",
        surfaces={"runtime consumption": "out-of-scope"},
    )
    assert assessment.ready is False
    assert any(
        "cannot close a runtime consumption surface" in reason
        for reason in assessment.reasons
    )


def test_json_runtime_consumption_transport_reads_host_state(tmp_path):
    state_file = tmp_path / "runtime.json"
    state_file.write_text(
        json.dumps(
            {
                "route_id": ROUTE,
                "target": TARGET,
                "route_digest": "e" * 64,
                "process_instance_id": "pid-123",
                "generation": 7,
            }
        ),
        encoding="utf-8",
    )
    transport = JsonFileRuntimeConsumptionTransport(
        consumer_id=CONSUMER,
        path=state_file,
    )
    observation = transport.observe(ROUTE, TARGET)
    assert observation.available is True
    assert observation.route_id == ROUTE
    assert observation.consumed_target == TARGET
    assert observation.route_digest == "e" * 64
    assert observation.process_instance_id == "pid-123"
    assert observation.state_digest is not None
    assert len(observation.state_digest) == 64
    assert observation.evidence_ref == str(state_file.resolve())
