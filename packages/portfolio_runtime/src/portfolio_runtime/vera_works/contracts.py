from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
_STATES_PATH = _BASE / "contracts" / "states-v1.json"
_REQUIRED_EVENT_FIELDS = (
    "schema_version",
    "event_id",
    "event_type",
    "subject_type",
    "subject_id",
    "actor",
    "recorded_at",
    "correlation_id",
    "causation_id",
    "idempotency_key",
    "from_state",
    "to_state",
    "payload",
    "external_effect",
)
_HOLD_REQUIRED_FROM = {
    "VERA_DECISION_REQUIRED": "vera",
    "PATRICK_ACTION_REQUIRED": "patrick",
    "PATRICK_DECISION_REQUIRED": "patrick",
    "AUTOMATION_EXCEPTION": "automation",
}


def load_states() -> dict:
    with _STATES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_utc_iso8601(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _decimal(value: object) -> Decimal | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _positive_money(payload: dict, field: str, state: str, errors: list[str]) -> Decimal | None:
    amount = _decimal(payload.get(field))
    if amount is None or amount <= 0:
        errors.append(f"financial {state} {field} must be greater than zero")
        return None
    return amount


def _nonnegative_money(payload: dict, field: str, state: str, errors: list[str]) -> Decimal | None:
    amount = _decimal(payload.get(field))
    if amount is None or amount < 0:
        errors.append(f"financial {state} {field} must be a non-negative decimal string")
        return None
    return amount


def _validate_financial_payload(state: str, payload: dict, errors: list[str]) -> None:
    currency = payload.get("currency")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha() or currency.upper() != currency:
        errors.append(f"financial {state} currency must be a three-letter uppercase code")

    if state in {"EARNED", "RECEIVABLE"}:
        _nonnegative_money(payload, "gross", state, errors)
    elif state == "RECEIVED":
        gross = _nonnegative_money(payload, "gross", state, errors)
        fees = _nonnegative_money(payload, "fees", state, errors)
        tax_reserve = _nonnegative_money(payload, "tax_reserve", state, errors)
        net = _nonnegative_money(payload, "net", state, errors)
        if None not in {gross, fees, tax_reserve, net} and net != gross - fees - tax_reserve:
            errors.append("financial RECEIVED net must equal gross - fees - tax_reserve")
    elif state == "REFUNDED":
        _positive_money(payload, "amount", state, errors)
        reference = payload.get("reverses_event_id")
        if not isinstance(reference, str) or not reference:
            errors.append("financial REFUNDED reverses_event_id must be a non-empty string")
    elif state == "SPENT":
        _positive_money(payload, "amount", state, errors)
        purpose = payload.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            errors.append("financial SPENT purpose must be a non-empty string")


def _validate_hold_payload(state: str, payload: dict, errors: list[str]) -> None:
    if state != "OPEN":
        return
    kind = payload.get("hold_kind")
    expected_actor = _HOLD_REQUIRED_FROM.get(kind)
    if expected_actor is not None and payload.get("required_from") != expected_actor:
        errors.append(f"{kind} required_from must equal {expected_actor}")
    if "alternatives" in payload and not isinstance(payload["alternatives"], list):
        errors.append("hold alternatives must be an array")
    if "consequences" in payload and not isinstance(payload["consequences"], list):
        errors.append("hold consequences must be an array")


def validate_event(event: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(event, dict):
        return ["event must be an object"]

    for field in _REQUIRED_EVENT_FIELDS:
        if field not in event:
            errors.append(f"missing required field: {field}")

    if errors:
        return errors

    if event["schema_version"] != "event-v1":
        errors.append("schema_version must equal event-v1")

    states_doc = load_states()
    subject_type = event["subject_type"]
    if subject_type not in states_doc["states"]:
        errors.append(f"unsupported subject_type: {subject_type}")
    elif event["to_state"] not in states_doc["states"][subject_type]:
        errors.append(f"unsupported to_state for {subject_type}: {event['to_state']}")

    if not _is_utc_iso8601(event["recorded_at"]):
        errors.append("recorded_at must be an ISO-8601 UTC timestamp ending in Z")

    if not isinstance(event["external_effect"], bool):
        errors.append("external_effect must be boolean")

    payload = event["payload"]
    if not isinstance(payload, dict):
        errors.append("payload must be an object")

    for field in (
        "event_id",
        "event_type",
        "subject_id",
        "actor",
        "correlation_id",
        "idempotency_key",
    ):
        if not isinstance(event[field], str) or not event[field]:
            errors.append(f"{field} must be a non-empty string")

    if event["causation_id"] is not None and not isinstance(event["causation_id"], str):
        errors.append("causation_id must be a string or null")
    if event["from_state"] is not None and not isinstance(event["from_state"], str):
        errors.append("from_state must be a string or null")

    if isinstance(payload, dict) and subject_type == "financial" and event["to_state"] in states_doc["states"].get("financial", []):
        _validate_financial_payload(event["to_state"], payload, errors)
    if isinstance(payload, dict) and subject_type == "hold" and event["to_state"] in states_doc["states"].get("hold", []):
        _validate_hold_payload(event["to_state"], payload, errors)

    return errors
