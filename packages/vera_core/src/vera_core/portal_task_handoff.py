"""Read-only, exact-journal Vera task -> PORTAL route advisory handoff.

Vera Mono remains the durable task, lifecycle and effect-authority owner.
An external PORTAL assessment NEVER becomes authority or task closeout.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from .task_execution import TaskExecutionError, TaskExecutionLedger

REQUEST_SCHEMA = "VERA_PORTAL_TASK_ROUTE_REQUEST_V1"
ASSESSMENT_SCHEMA = "VERA_PORTAL_TASK_ROUTE_ASSESSMENT_V1"
ADVISORY_EFFECT = "NO_PROTECTED_EFFECT"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


def _hash(body: dict[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(body))


def _identity(value: str, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise TaskExecutionError(f"invalid exact {label}")
    return value


def _digest(value: str, label: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise TaskExecutionError(f"invalid {label}")
    return value


def _request_body(request: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema", "task_id", "task_packet_digest", "task_journal_head",
        "subject", "route", "requested_effect", "request_digest",
    }
    if type(request) is not dict or set(request) != expected:
        raise TaskExecutionError("unknown or missing route-request fields")
    if request["schema"] != REQUEST_SCHEMA or request["requested_effect"] != ADVISORY_EFFECT:
        raise TaskExecutionError("unsupported route-request schema or effect")
    _identity(request["task_id"], "task_id")
    _digest(request["task_packet_digest"], "task_packet_digest")
    _digest(request["task_journal_head"], "task_journal_head")
    _digest(request["request_digest"], "request_digest")
    if type(request["subject"]) is not str or not request["subject"].strip():
        raise TaskExecutionError("missing task subject")
    route = request["route"]
    if type(route) is not dict or set(route) != {
        "node_id", "target_kind", "target_id", "required_capabilities",
    }:
        raise TaskExecutionError("invalid route target")
    for label in ("node_id", "target_kind", "target_id"):
        _identity(route[label], label)
    caps = route["required_capabilities"]
    if type(caps) is not list or not 1 <= len(caps) <= 16 or any(
        type(x) is not str or not _ID.fullmatch(x) for x in caps
    ) or caps != sorted(set(caps)):
        raise TaskExecutionError("route capabilities must be sorted unique identifiers")
    body = {key: value for key, value in request.items() if key != "request_digest"}
    if _hash(body) != request["request_digest"]:
        raise TaskExecutionError("route-request digest mismatch")
    return body


def export_portal_route_request(
    ledger: TaskExecutionLedger,
    task_id: str,
    *,
    node_id: str,
    target_kind: str,
    target_id: str,
    required_capabilities: tuple[str, ...],
) -> dict[str, Any]:
    """Export advisory intent from the actual durable task, never from caller claims."""
    _identity(task_id, "task_id")
    state = ledger.read(task_id)
    if state.closed:
        raise TaskExecutionError("cannot route a closed task")
    body = {
        "schema": REQUEST_SCHEMA,
        "task_id": task_id,
        "task_packet_digest": state.packet.packet_digest,
        "task_journal_head": state.journal_head_digest,
        "subject": state.packet.subject,
        "route": {
            "node_id": node_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "required_capabilities": sorted(set(required_capabilities)),
        },
        "requested_effect": ADVISORY_EFFECT,
    }
    record = {**body, "request_digest": _hash(body)}
    _request_body(record)
    return record


def verify_portal_route_assessment(
    ledger: TaskExecutionLedger,
    request: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Validate returned advisory against current task; does not record acceptance."""
    _request_body(request)
    task = ledger.read(request["task_id"])
    if task.closed or task.packet.packet_digest != request["task_packet_digest"] or (
        task.journal_head_digest != request["task_journal_head"]
    ) or task.packet.subject != request["subject"]:
        raise TaskExecutionError("stale task or incompatible journal head")

    expected = {
        "schema", "task_id", "task_packet_digest", "task_journal_head",
        "request_digest", "state", "route", "reason", "assessment_digest",
    }
    if type(assessment) is not dict or set(assessment) != expected:
        raise TaskExecutionError("unknown or missing route-assessment fields")
    if assessment["schema"] != ASSESSMENT_SCHEMA:
        raise TaskExecutionError("unsupported route-assessment schema")
    for key in ("task_id", "task_packet_digest", "task_journal_head", "request_digest"):
        if assessment[key] != request[key]:
            raise TaskExecutionError(f"route-assessment {key} mismatch")
    _digest(assessment["assessment_digest"], "assessment_digest")
    body = {key: value for key, value in assessment.items() if key != "assessment_digest"}
    if _hash(body) != assessment["assessment_digest"]:
        raise TaskExecutionError("route-assessment digest mismatch")
    if assessment["state"] == "HELD":
        if assessment["route"] is not None or assessment["reason"] != "NO_QUALIFIED_ADVISORY_ROUTE":
            raise TaskExecutionError("malformed held assessment")
    elif assessment["state"] == "ROUTE_PROPOSED":
        route = assessment["route"]
        if type(route) is not dict or set(route) != {"adapter_id", "route_id"} or (
            assessment["reason"] is not None
        ):
            raise TaskExecutionError("invalid advisory route")
        for key in ("adapter_id", "route_id"):
            _identity(route[key], key)
    else:
        raise TaskExecutionError("unsupported advisory state")
    # Deliberately only advisory: no task checkpoint, effect, permit or closeout.
    return dict(assessment)
