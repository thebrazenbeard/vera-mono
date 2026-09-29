from dataclasses import dataclass
import json

import pytest

from vera_core import (
    JsonFileRouteVerificationTransport,
    QualifiedVeraRuntime,
    RouteObservation,
    RouteVerificationError,
    TaskPacket,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
ROUTE = "vera-active"
TARGET = "vera-mono@0.1.0"


@dataclass
class FakeRouteTransport:
    route_id: str = ROUTE
    selected_target: str = TARGET
    route_digest: str = "a" * 64
    available: bool = True

    def __post_init__(self):
        self.calls = []

    def observe(self, expected_target):
        self.calls.append(expected_target)
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


def packet():
    return TaskPacket(
        purpose="Verify exact selected Vera route.",
        subject="active Vera route",
        completion_state="Declared route is verified-current.",
        evidence_requirements=(f"ROUTE_VERIFY|{ROUTE}|{TARGET}",),
        writable_scope=(),
        non_targets=("runtime consumption", "deployment"),
        forbidden_shortcuts_or_effects=(
            "do not infer route from installation",
        ),
        priority_order=("currentness", "exactness"),
        unknowns=(),
        return_shape=("route receipt",),
        relevant_surfaces=("current route",),
    )


def surfaces():
    return {"current route": "verified-current"}


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
            text="route verification state",
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
        runtime_id="runtime-route",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def runtime_with_transport(tmp_path, transport):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        route_verification_transports={transport.route_id: transport},
    )
    runtime.start_task("task-route", packet())
    return state, runtime


def test_required_route_verification_gates_closeout(tmp_path):
    transport = FakeRouteTransport()
    _, runtime = runtime_with_transport(tmp_path, transport)

    before = runtime.assess_task_closeout(
        "task-route",
        surfaces=surfaces(),
    )
    assert before.ready is False
    assert any(
        "required routes are not verified-current" in reason
        for reason in before.reasons
    )

    receipt = runtime.verify_task_route("task-route", ROUTE)
    assert receipt.status == "PASS"
    assert receipt.selected_target == TARGET
    assert transport.calls == [TARGET]

    assessment = runtime.assess_route_verification(
        "task-route",
        ROUTE,
    )
    assert assessment.passed is True
    assert assessment.current_matches_receipt is True
    assert assessment.latest_receipt_digest == receipt.receipt_digest

    ready = runtime.assess_task_closeout(
        "task-route",
        surfaces=surfaces(),
    )
    assert ready.ready is True

    closed = runtime.close_task(
        "task-route",
        "close-route",
        surfaces=surfaces(),
        evidence_refs=("operator requested route verification",),
        claim_ceiling="ROUTE_VERIFIED_NOT_RUNTIME_CONSUMPTION_NOT_BEHAVIOR",
        next_frontier="verify runtime consumption separately",
    )
    assert closed.closed is True
    assert any(
        ref == f"task-route:{ROUTE}:{receipt.receipt_digest}"
        for ref in closed.closeout.evidence_refs
    )

    with pytest.raises(RouteVerificationError):
        runtime.verify_task_route("task-route", ROUTE)


def test_live_route_change_invalidates_stored_pass(tmp_path):
    transport = FakeRouteTransport()
    _, runtime = runtime_with_transport(tmp_path, transport)
    runtime.verify_task_route("task-route", ROUTE)
    assert runtime.assess_task_closeout(
        "task-route",
        surfaces=surfaces(),
    ).ready is True

    transport.route_digest = "b" * 64
    assessment = runtime.assess_route_verification(
        "task-route",
        ROUTE,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.passed is False
    assert assessment.current_matches_receipt is False
    assert runtime.assess_task_closeout(
        "task-route",
        surfaces=surfaces(),
    ).ready is False


def test_stored_route_pass_without_live_transport_is_not_current_after_restart(tmp_path):
    transport = FakeRouteTransport()
    state, runtime = runtime_with_transport(tmp_path, transport)
    receipt = runtime.verify_task_route("task-route", ROUTE)
    assert receipt.status == "PASS"

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    assessment = restarted.assess_route_verification(
        "task-route",
        ROUTE,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.transport_available is False
    assert assessment.passed is False
    assert restarted.assess_task_closeout(
        "task-route",
        surfaces=surfaces(),
    ).ready is False

    recovery = restarted.resume_context()["route_verification_recovery"]
    assert len(recovery) == 1
    assert recovery[0]["task_id"] == "task-route"
    assert recovery[0]["passed"] is False
    assert recovery[0]["transport_available"] is False


def test_route_requirement_cannot_close_out_of_scope(tmp_path):
    transport = FakeRouteTransport()
    _, runtime = runtime_with_transport(tmp_path, transport)
    runtime.verify_task_route("task-route", ROUTE)

    assessment = runtime.assess_task_closeout(
        "task-route",
        surfaces={"current route": "out-of-scope"},
    )
    assert assessment.ready is False
    assert any(
        "cannot close a current route surface" in reason
        for reason in assessment.reasons
    )


def test_wrong_selected_route_is_fail(tmp_path):
    transport = FakeRouteTransport(selected_target="other-runtime")
    _, runtime = runtime_with_transport(tmp_path, transport)
    receipt = runtime.verify_task_route("task-route", ROUTE)
    assert receipt.status == "FAIL"
    assert runtime.assess_route_verification(
        "task-route",
        ROUTE,
    ).passed is False


def test_json_route_transport_observes_canonical_route_file(tmp_path):
    route_file = tmp_path / "route.json"
    route_file.write_text(
        json.dumps({"target": TARGET, "generation": 4}),
        encoding="utf-8",
    )
    transport = JsonFileRouteVerificationTransport(
        route_id=ROUTE,
        path=route_file,
    )
    observation = transport.observe(TARGET)
    assert observation.available is True
    assert observation.selected_target == TARGET
    assert observation.route_digest is not None
    assert len(observation.route_digest) == 64
    assert observation.evidence_ref == str(route_file.resolve())
