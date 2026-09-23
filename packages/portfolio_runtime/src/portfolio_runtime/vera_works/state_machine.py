from __future__ import annotations

from collections.abc import Iterable

from .contracts import load_states, validate_event

HOLD_KINDS = {
    "VERA_DECISION_REQUIRED",
    "PATRICK_ACTION_REQUIRED",
    "PATRICK_DECISION_REQUIRED",
    "AUTOMATION_EXCEPTION",
}
HOLD_REQUIRED_FIELDS = (
    "hold_kind",
    "problem",
    "held_subject_type",
    "held_subject_id",
    "held_state",
    "required_from",
    "recommendation",
    "alternatives",
    "consequences",
    "inaction_effect",
    "resume_event_type",
)


def _subject_key(event: dict) -> tuple[str, str]:
    return event["subject_type"], event["subject_id"]


def validate_history(events: list[dict]) -> list[str]:
    errors: list[str] = []
    seen_event_ids: set[str] = set()
    seen_idempotency_keys: set[str] = set()
    states: dict[tuple[str, str], str] = {}
    open_hold_events: dict[str, dict] = {}
    leases: dict[str, dict] = {}
    states_doc = load_states()
    transitions = states_doc["transitions"]
    initial_states = states_doc["initial_states"]

    for event in events:
        event_errors = validate_event(event)
        if event_errors:
            errors.extend(event_errors)
            continue

        event_id = event["event_id"]
        idem = event["idempotency_key"]
        if event_id in seen_event_ids:
            errors.append(f"duplicate event_id: {event_id}")
        else:
            seen_event_ids.add(event_id)
        if idem in seen_idempotency_keys:
            errors.append(f"duplicate idempotency_key: {idem}")
        else:
            seen_idempotency_keys.add(idem)

        key = _subject_key(event)
        expected = states.get(key)
        supplied_from = event["from_state"]
        if expected != supplied_from:
            errors.append(
                f"stale from_state for {event['subject_type']} {event['subject_id']}: "
                f"expected {expected}, got {supplied_from}"
            )
        elif expected is None:
            allowed_initial = initial_states[event["subject_type"]]
            if event["to_state"] not in allowed_initial:
                errors.append(
                    f"illegal initial state for {event['subject_type']} {event['subject_id']}: "
                    f"{event['to_state']}"
                )
        else:
            allowed = transitions[event["subject_type"]].get(expected, [])
            if event["to_state"] not in allowed:
                errors.append(
                    f"illegal transition for {event['subject_type']} {event['subject_id']}: "
                    f"{expected} -> {event['to_state']}"
                )

        if event["subject_type"] == "assignment":
            assignment_id = event["subject_id"]
            payload = event["payload"]
            lease = leases.get(assignment_id)
            lease_action = payload.get("lease_action")
            holder = payload.get("holder")

            if lease_action == "CLAIM":
                if lease is not None:
                    errors.append(f"assignment {assignment_id} already leased to {lease['holder']}")
                elif not holder:
                    errors.append(f"assignment {assignment_id} claim missing holder")
                elif not payload.get("claimed_at"):
                    errors.append(f"assignment {assignment_id} claim missing claimed_at")
                else:
                    leases[assignment_id] = {
                        "holder": holder,
                        "claim_event_id": event_id,
                        "claimed_at": payload["claimed_at"],
                        "expires_at": payload.get("expires_at"),
                    }
            elif lease_action == "TRANSFER":
                if lease is None:
                    errors.append(f"assignment {assignment_id} transfer has no active lease")
                elif payload.get("previous_holder") != lease["holder"]:
                    errors.append(
                        f"assignment {assignment_id} transfer previous_holder mismatch: "
                        f"expected {lease['holder']}, got {payload.get('previous_holder')}"
                    )
                elif not holder:
                    errors.append(f"assignment {assignment_id} transfer missing holder")
                else:
                    leases[assignment_id] = {
                        "holder": holder,
                        "claim_event_id": event_id,
                        "claimed_at": event["recorded_at"],
                        "expires_at": payload.get("expires_at"),
                    }
            elif lease is not None and holder is not None and holder != lease["holder"]:
                errors.append(
                    f"assignment {assignment_id} lease holder mismatch: "
                    f"expected {lease['holder']}, got {holder}"
                )

            if event["to_state"] in {"COMPLETED", "CANCELLED", "FAILED"}:
                leases.pop(assignment_id, None)

        if event["subject_type"] == "hold":
            payload = event["payload"]
            if event["to_state"] == "OPEN":
                hold_errors: list[str] = []
                for field in HOLD_REQUIRED_FIELDS:
                    if field not in payload:
                        hold_errors.append(f"hold payload missing required field: {field}")
                kind = payload.get("hold_kind")
                if kind is not None and kind not in HOLD_KINDS:
                    hold_errors.append(f"unsupported hold_kind: {kind}")
                errors.extend(hold_errors)
                if not hold_errors:
                    open_hold_events[event_id] = event
            elif event["to_state"] in {"RESOLVED", "CANCELLED"}:
                resolution_of = payload.get("resolution_of")
                if not resolution_of:
                    errors.append(f"hold resolution {event_id} missing resolution_of")
                else:
                    opening = open_hold_events.get(resolution_of)
                    if opening is None:
                        errors.append(f"hold resolution {event_id} references non-open hold: {resolution_of}")
                    else:
                        resolution_errors: list[str] = []
                        opening_payload = opening["payload"]
                        expected_event_type = opening_payload["resume_event_type"]
                        if event["event_type"] != expected_event_type:
                            resolution_errors.append(
                                f"hold resolution {event_id} event_type mismatch: "
                                f"expected {expected_event_type}, got {event['event_type']}"
                            )
                        expected_actor = opening_payload["required_from"]
                        if event["actor"] != expected_actor:
                            resolution_errors.append(
                                f"hold resolution {event_id} actor mismatch: "
                                f"expected {expected_actor}, got {event['actor']}"
                            )
                        if event["causation_id"] != resolution_of:
                            resolution_errors.append(
                                f"hold resolution {event_id} causation_id mismatch: "
                                f"expected {resolution_of}, got {event['causation_id']}"
                            )
                        errors.extend(resolution_errors)
                        if not resolution_errors:
                            open_hold_events.pop(resolution_of, None)

        states[key] = event["to_state"]

    return errors


def current_state(events: Iterable[dict], subject_type: str, subject_id: str) -> str | None:
    state: str | None = None
    for event in events:
        if event.get("subject_type") == subject_type and event.get("subject_id") == subject_id:
            state = event.get("to_state")
    return state


def open_holds(events: list[dict]) -> list[dict]:
    opens: dict[str, dict] = {}
    for event in events:
        if event.get("subject_type") != "hold":
            continue
        if event.get("to_state") == "OPEN":
            opens[event["event_id"]] = event
        elif event.get("to_state") in {"RESOLVED", "CANCELLED"}:
            resolution_of = event.get("payload", {}).get("resolution_of")
            if resolution_of:
                opens.pop(resolution_of, None)
    return list(opens.values())


def active_lease(events: list[dict], assignment_id: str) -> dict | None:
    lease: dict | None = None
    for event in events:
        if event.get("subject_type") != "assignment" or event.get("subject_id") != assignment_id:
            continue
        payload = event.get("payload", {})
        action = payload.get("lease_action")
        if action == "CLAIM" and lease is None and payload.get("holder"):
            lease = {
                "holder": payload["holder"],
                "claim_event_id": event.get("event_id"),
                "claimed_at": payload.get("claimed_at"),
                "expires_at": payload.get("expires_at"),
            }
        elif action == "TRANSFER" and lease is not None and payload.get("holder"):
            if payload.get("previous_holder") == lease.get("holder"):
                lease = {
                    "holder": payload["holder"],
                    "claim_event_id": event.get("event_id"),
                    "claimed_at": event.get("recorded_at"),
                    "expires_at": payload.get("expires_at"),
                }
        if event.get("to_state") in {"COMPLETED", "CANCELLED", "FAILED"}:
            lease = None
    return lease
