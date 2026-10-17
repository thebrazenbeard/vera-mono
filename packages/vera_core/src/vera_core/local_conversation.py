"""Resident-local conversation correlation over the canonical Mono task ledger.

No extra memory/database, producer authentication, model admission, or effects.
A Pre-Active observation is evidence, never task closeout or permission.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .task_execution import TaskPacket, TaskExecutionError
from .portal_task_handoff import export_portal_route_request, verify_portal_route_assessment

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_PREFIX = "VERAOS_LOCAL_MESSAGE_V1:"
_ROUTE = "NO_PROTECTED_EFFECT"


class ConversationError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _ids(conversation_id: str, message_id: str) -> None:
    if any(type(v) is not str or _ID.fullmatch(v) is None
           for v in (conversation_id, message_id)):
        raise ConversationError("invalid untrusted conversation/message locator")


def _key(conversation_id: str, message_id: str) -> str:
    _ids(conversation_id, message_id)
    return "ui-" + _digest({"schema": "VERAOS_LOCAL_MESSAGE_KEY_V1",
                            "conversation_id": conversation_id, "message_id": message_id})


def open_message(ledger: Any, conversation_id: str, message_id: str, text: str) -> dict:
    """Open or replay exactly one actual task from a bounded local UI message."""
    _ids(conversation_id, message_id)
    if type(text) is not str or text != text.strip() or not text or len(text) > 2048:
        raise ConversationError("invalid literal task text")
    key = _key(conversation_id, message_id)
    source = _digest({"schema": "VERAOS_LOCAL_UI_INTAKE_SOURCE_V1",
                      "conversation_id": conversation_id, "message_id": message_id,
                      "text": text})
    packet = TaskPacket(
        purpose=_PREFIX + _json({"conversation_id": conversation_id, "message_id": message_id}),
        subject=text, completion_state="HELD_UNTIL_ADMITTED_PROVIDER_AND_RESULT",
        evidence_requirements=("actual task ledger head", "attributable external outcome"),
        writable_scope=(), non_targets=("governed long-term memory", "protected effects"),
        forbidden_shortcuts_or_effects=("route advice is not execution authority",
                                        "observed model text is not task completion"),
        priority_order=("task identity", "durable receipt", "non-redispatch"),
        unknowns=("client identity unverified", "model not admitted"),
        return_shape=("task status", "source-only observation"),
        relevant_surfaces=("source", "workspace/coordination"),
    )
    try:
        state = ledger.open_task(key, packet, lifecycle_evidence_digest=source)
        events = ledger.events(key)
    except (TaskExecutionError, ValueError) as exc:
        raise ConversationError("task identifier collision or invalid persisted ledger") from exc
    if (not events or events[0].event_type != "TASK_OPENED"
            or state.packet.packet_digest != packet.packet_digest
            or state.opened_lifecycle_evidence_digest != source):
        raise ConversationError("substituted task opening")
    return {"schema": "VERAOS_LOCAL_TASK_INTAKE_V1", "conversation_id": conversation_id,
            "message_id": message_id, "task_id": key, "text": text,
            "source_digest": source, "packet_digest": packet.packet_digest,
            "opened_head": events[0].event_digest, "origin_authenticated": False}


def _state(ledger: Any, intake: dict):
    state = ledger.read(intake["task_id"])
    events = ledger.events(intake["task_id"])
    if (not events or state.closed or state.active_dependencies
            or state.unresolved_correction_ids
            or state.packet.subject != intake["text"]
            or state.packet.packet_digest != intake["packet_digest"]
            or state.opened_lifecycle_evidence_digest != intake["source_digest"]
            or events[0].event_digest != intake["opened_head"]):
        raise ConversationError("task closed, changed, or unresolved")
    return state, events


def reserve_source_trial(ledger: Any, intake: dict, assessment: dict,
                         *, target_id: str, route_id: str) -> dict:
    """Task-scoped CAS: source fixture reservation, expressly NOT dispatch permit."""
    state, events = _state(ledger, intake)
    if len(events) != 1:
        raise ConversationError("source reservation already exists or task advanced")
    request = export_portal_route_request(
        ledger, intake["task_id"], node_id="veraos", target_kind="MODEL",
        target_id=target_id, required_capabilities=("text",),
    )
    verified = verify_portal_route_assessment(ledger, request, assessment)
    if (verified["state"] != "ROUTE_PROPOSED" or
            verified["route"]["route_id"] != route_id or
            request["requested_effect"] != _ROUTE or
            ledger.events(intake["task_id"])[-1].event_digest != intake["opened_head"]):
        raise ConversationError("unqualified or stale advisory")
    identity = "source-reservation-" + intake["message_id"]
    seed = {"schema": "VERAOS_SOURCE_RESERVATION_V1", "request_digest": request["request_digest"],
            "assessment_digest": verified["assessment_digest"], "route_id": route_id,
            "target_id": target_id, "message_id": intake["message_id"],
            "source_digest": intake["source_digest"], "effect": _ROUTE,
            "model_admitted": False, "dispatch_authorized": False}
    try:
        ledger.checkpoint(
            intake["task_id"], identity,
            completed_evidence=("source-reservation-json:" + _json(seed),),
            blockers=("TEST ONLY: provider and user not authenticated",),
            protected_effects_still_gated=("COGNITION_TURN",),
            next_frontier="reconcile one Pre-Active source observation",
            lifecycle_evidence_digest=_digest(seed),
            expected_task_head=intake["opened_head"],
        )
    except (TaskExecutionError, ValueError) as exc:
        raise ConversationError("stale expected-task-head reservation") from exc
    after = ledger.events(intake["task_id"])
    if len(after) != 2 or after[-1].event_id != intake["task_id"] + ":CHECKPOINT:" + identity:
        raise ConversationError("source reservation did not append exactly once")
    return {"reservation_head": after[-1].event_digest, "seed": seed}


def _source(store: Any, intake: dict, route_id: str):
    """Inspect only the existing exact Pre-Active event/run and singular route."""
    dedup = "veraos-text:" + intake["message_id"]
    events = store.connection.execute(
        "SELECT id,kind,status,payload_json,dedup_key FROM events WHERE dedup_key=?",
        (dedup,),
    ).fetchall()
    if not events:
        return None
    if len(events) != 1:
        raise ConversationError("duplicate dedup identities")
    e = events[0]
    runs = store.connection.execute(
        """SELECT id,task,status,capabilities_json,final_text,last_error,
                  source_event_id,failed_event_id,control_action FROM runs
           WHERE source_event_id=?""", (e["id"],),
    ).fetchall()
    if len(runs) > 1:
        raise ConversationError("multiple runs from one request")
    if (e["kind"] != "task.requested" or e["dedup_key"] != dedup
            or json.loads(e["payload_json"]) != {"task": intake["text"], "capabilities": []}):
        raise ConversationError("forged Pre-Active task source")
    if not runs:
        return None
    r = runs[0]
    if (e["status"] != "DONE" or r["status"] != "COMPLETED"):
        if r["status"] == "COMPLETED" or e["status"] == "DONE":
            raise ConversationError("terminal event and run disagree")
        return None
    routes = store.connection.execute(
        """SELECT payload_json FROM journal
           WHERE subject_id=? AND event_type='VERAOS_COGNITION_ROUTE_SELECTED'""",
        (e["id"],),
    ).fetchall()
    expected = {"adapter_id": "pre-active-offline-fixture",
                "route_id": route_id, "provider_id": route_id,
                "model": "offline-deterministic", "effect_class": "COGNITION_ONLY"}
    if (r["source_event_id"] != e["id"] or r["task"] != intake["text"]
            or json.loads(r["capabilities_json"]) != []
            or type(r["final_text"]) is not str or not r["final_text"].strip()
            or len(r["final_text"]) > 8192
            or r["last_error"] is not None or r["failed_event_id"] is not None
            or r["control_action"] is not None or len(routes) != 1
            or json.loads(routes[0]["payload_json"]) != expected):
        raise ConversationError("unattributable or altered Pre-Active observation")
    return {"schema": "VERAOS_SYNTHETIC_SOURCE_OBSERVATION_V1",
            "task_id": intake["task_id"], "conversation_id": intake["conversation_id"],
            "message_id": intake["message_id"], "source_digest": intake["source_digest"],
            "route_id": route_id, "event_id": e["id"], "run_id": r["id"],
            "text": r["final_text"], "synthetic": True,
            "model_authenticated": False, "accepted_as_task_result": False,
            "display_authorized": False, "protected_effect_authority": False}


def recover_message(ledger: Any, store: Any, intake: dict) -> dict:
    """Cold readback: never starts an executor, even after ambiguous crashes."""
    state, events = _state(ledger, intake)
    if len(events) == 1:
        return {"status": "PENDING_NO_ADMITTED_PROVIDER", "task_id": intake["task_id"]}
    if len(events) not in (2, 3) or events[1].event_type != "TASK_CHECKPOINT":
        return {"status": "HELD_TASK_CHANGED", "task_id": intake["task_id"]}
    source_seed = [x[len("source-reservation-json:"):] for x in
                   events[1].payload.get("completed_evidence", [])
                   if isinstance(x, str) and x.startswith("source-reservation-json:")]
    if len(source_seed) != 1:
        return {"status": "HELD_TASK_CHANGED", "task_id": intake["task_id"]}
    seed = json.loads(source_seed[0])
    if (seed.get("source_digest") != intake["source_digest"]
            or seed.get("message_id") != intake["message_id"]
            or seed.get("effect") != _ROUTE or seed.get("model_admitted") is not False
            or seed.get("dispatch_authorized") is not False
            or events[1].payload.get("lifecycle_evidence_digest") != _digest(seed)):
        raise ConversationError("forged or stale reservation")
    observed = _source(store, intake, seed["route_id"])
    if observed is None:
        return {"status": "OUTCOME_UNKNOWN_NO_REDISPATCH", "task_id": intake["task_id"]}
    fingerprint = _digest(observed)
    if len(events) == 2:
        # Pure recovery is read-only. Separate explicit reconciliation may seal.
        return {"status": "SOURCE_COMPLETED_UNSEALED_NO_REDISPATCH",
                "task_id": intake["task_id"], "observation_digest": fingerprint}
    evidence = [x for x in events[2].payload.get("completed_evidence", [])
                if isinstance(x, str) and x.startswith("source-observation-sha256:")]
    if (len(evidence) != 1 or evidence[0] != "source-observation-sha256:" + fingerprint
            or events[2].payload.get("lifecycle_evidence_digest") != fingerprint):
        raise ConversationError("persistent stores disagree on source result")
    return {"status": "SOURCE_OBSERVATION_REVALIDATED", "task_id": intake["task_id"],
            "observation_digest": fingerprint, "source": observed,
            "accepted_as_task_result": False, "display_authorized": False}


def seal_source_observation(ledger: Any, store: Any, intake: dict) -> dict:
    """One task-scoped result checkpoint. Never completes a task or writes memory."""
    recovered = recover_message(ledger, store, intake)
    if recovered["status"] == "SOURCE_OBSERVATION_REVALIDATED":
        return recovered
    if recovered["status"] != "SOURCE_COMPLETED_UNSEALED_NO_REDISPATCH":
        return recovered
    events = ledger.events(intake["task_id"])
    fingerprint = recovered["observation_digest"]
    try:
        ledger.checkpoint(
            intake["task_id"], "source-observation-" + intake["message_id"],
            completed_evidence=("source-observation-sha256:" + fingerprint,),
            blockers=("synthetic source evidence, not authorized completion",),
            protected_effects_still_gated=("COGNITION_TURN",),
            next_frontier="qualified provider admission remains held",
            lifecycle_evidence_digest=fingerprint,
            expected_task_head=events[1].event_digest,
        )
    except (TaskExecutionError, ValueError) as exc:
        raise ConversationError("stale result seal CAS") from exc
    return recover_message(ledger, store, intake)


def conversation_history(ledger: Any, conversation_id: str) -> list[dict]:
    """Reconstruct message identity and task statuses; not autobiographical memory."""
    _ids(conversation_id, "probe")
    result = []
    for task in ledger.tasks():
        purpose = task.packet.purpose
        if not purpose.startswith(_PREFIX):
            continue
        try:
            identity = json.loads(purpose[len(_PREFIX):])
        except ValueError as exc:
            raise ConversationError("corrupt conversation locator") from exc
        if identity.get("conversation_id") != conversation_id:
            continue
        message_id = identity.get("message_id")
        if task.task_id != _key(conversation_id, message_id):
            raise ConversationError("conversation history task identity differs")
        result.append({"conversation_id": conversation_id, "message_id": message_id,
                       "task_id": task.task_id, "text": task.packet.subject,
                       "closed": task.closed, "task_journal_head": task.journal_head_digest})
    return result
