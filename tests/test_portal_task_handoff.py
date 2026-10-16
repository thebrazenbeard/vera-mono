"""Portable advisory task handoff; never a Vera authority or closeout."""
from copy import deepcopy
import pytest

from vera_core.task_execution import TaskExecutionLedger, TaskPacket, TaskExecutionError
from vera_core.portal_task_handoff import (
    export_portal_route_request,
    verify_portal_route_assessment,
)
from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex


def packet() -> TaskPacket:
    return TaskPacket(
        purpose="Recover the integration handoff after worker restart",
        subject="thebrazenbeard/portal@main",
        completion_state="A verified receipt is recorded by Vera",
        evidence_requirements=("route currentness",),
        writable_scope=(),
        non_targets=("no deployment",),
        forbidden_shortcuts_or_effects=("no effect permission",),
        priority_order=("recovery", "correctness"),
        unknowns=("live route is not installed",),
        return_shape=("route", "evidence"),
        relevant_surfaces=("current route", "workspace/coordination"),
    )


def opened(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task("task-001", packet(), lifecycle_evidence_digest="a" * 64)
    return ledger


def request(ledger):
    return export_portal_route_request(
        ledger, "task-001", node_id="repo-native",
        target_kind="repository", target_id="thebrazenbeard/portal",
        required_capabilities=("repository_read", "repository_read"),
    )


def assessment(request, state="ROUTE_PROPOSED"):
    body = {
        "schema": "VERA_PORTAL_TASK_ROUTE_ASSESSMENT_V1",
        "task_id": request["task_id"],
        "task_packet_digest": request["task_packet_digest"],
        "task_journal_head": request["task_journal_head"],
        "request_digest": request["request_digest"],
        "state": state,
        "route": {"adapter_id": "github", "route_id": "readonly"} if state == "ROUTE_PROPOSED" else None,
        "reason": None if state == "ROUTE_PROPOSED" else "NO_QUALIFIED_ADVISORY_ROUTE",
    }
    return {**body, "assessment_digest": sha256_hex(canonical_json_bytes(body))}


def test_real_ledger_export_uses_exact_current_task_and_replays_deterministically(tmp_path):
    ledger=opened(tmp_path)
    first=request(ledger)
    assert request(ledger)==first
    assert first["task_packet_digest"]==packet().packet_digest
    assert first["task_journal_head"]==ledger.read("task-001").journal_head_digest
    assert first["requested_effect"]=="NO_PROTECTED_EFFECT"
    assert first["route"]["required_capabilities"]==["repository_read"]
    assert verify_portal_route_assessment(ledger,first,assessment(first))["state"]=="ROUTE_PROPOSED"
    assert ledger.read("task-001").latest_checkpoint is None  # No write side effect.
    assert len(ledger.events("task-001"))==1


def test_held_advisory_does_not_mutate_task_or_grant_authority(tmp_path):
    ledger=opened(tmp_path)
    req=request(ledger)
    result=verify_portal_route_assessment(ledger,req,assessment(req,"HELD"))
    assert result["route"] is None
    assert len(ledger.events("task-001"))==1


def test_tampered_request_response_and_identity_mismatch_are_denied(tmp_path):
    ledger=opened(tmp_path)
    req=request(ledger)
    good=assessment(req)
    tampered=deepcopy(req)
    tampered["route"]["target_id"]="attacker/repo"
    with pytest.raises(TaskExecutionError):
        verify_portal_route_assessment(ledger,tampered,good)
    bad=deepcopy(good)
    bad["route"]["route_id"]="another"
    with pytest.raises(TaskExecutionError,match="digest"):
        verify_portal_route_assessment(ledger,req,bad)
    bad=deepcopy(good)
    bad["task_id"]="other-task"
    bad["assessment_digest"]=sha256_hex(canonical_json_bytes({k:v for k,v in bad.items() if k!="assessment_digest"}))
    with pytest.raises(TaskExecutionError,match="task_id"):
        verify_portal_route_assessment(ledger,req,bad)
    bad=deepcopy(good)
    bad["state"]="EXECUTED"
    bad["assessment_digest"]=sha256_hex(canonical_json_bytes({k:v for k,v in bad.items() if k!="assessment_digest"}))
    with pytest.raises(TaskExecutionError,match="unsupported advisory state"):
        verify_portal_route_assessment(ledger,req,bad)


def test_stale_task_journal_rejected_even_if_advisory_digest_valid(tmp_path):
    ledger=opened(tmp_path)
    req=request(ledger)
    receipt=assessment(req)
    ledger.bind_dependency(
        "task-001", "dep:live-change",
        kind="COORDINATION_COMMAND", target_id="command:changed",
    )
    with pytest.raises(TaskExecutionError,match="stale task"):
        verify_portal_route_assessment(ledger,req,receipt)


def test_bad_task_or_effect_cannot_be_minted_from_forged_packet(tmp_path):
    ledger=opened(tmp_path)
    with pytest.raises(KeyError):
        export_portal_route_request(
            ledger,"not-open",node_id="repo-native",
            target_kind="repository",target_id="x/y",required_capabilities=("repository_read",),
        )
    req=request(ledger)
    forged=deepcopy(req)
    forged["requested_effect"]="SOURCE_WRITE"
    forged["request_digest"]=sha256_hex(canonical_json_bytes({k:v for k,v in forged.items() if k!="request_digest"}))
    with pytest.raises(TaskExecutionError,match="unsupported"):
        verify_portal_route_assessment(ledger,forged,assessment(forged))


def test_independent_golden_wire_vector(tmp_path):
    """Can verify the exact PORTAL response without importing PORTAL code."""
    import json
    from pathlib import Path

    fixture=json.loads(
        (Path(__file__).parent/"fixtures/vera_portal_task_route_v1.json").read_text(encoding="utf-8")
    )
    ledger=TaskExecutionLedger(tmp_path/"golden-tasks.sqlite")
    body=fixture["task_packet"]
    source=TaskPacket(
        **{key:tuple(value) if isinstance(value,list) else value for key,value in body.items()}
    )
    ledger.open_task(
        fixture["task_id"],source,
        lifecycle_evidence_digest=fixture["lifecycle_evidence_digest"],
    )
    generated=export_portal_route_request(
        ledger,fixture["task_id"],node_id="repo-native",
        target_kind="repository",target_id="thebrazenbeard/portal",
        required_capabilities=("repository_read",),
    )
    assert generated==fixture["request"]
    assert verify_portal_route_assessment(ledger,generated,fixture["proposed"])["state"]=="ROUTE_PROPOSED"
    assert verify_portal_route_assessment(ledger,generated,fixture["held"])["state"]=="HELD"
