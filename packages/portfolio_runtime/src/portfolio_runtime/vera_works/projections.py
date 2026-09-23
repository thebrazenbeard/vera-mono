from __future__ import annotations

from decimal import Decimal

from .state_machine import open_holds


def _money(value: str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(value)


def financial_ledger(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    balance = Decimal("0.00")
    currency: str | None = None
    received_event_ids: set[str] = set()

    for event in events:
        if event.get("subject_type") != "financial":
            continue
        payload = event.get("payload", {})
        event_currency = payload.get("currency")
        if currency is None:
            currency = event_currency
        elif event_currency is not None and event_currency != currency:
            raise ValueError("mixed currencies require separate ledger projections")

        state = event.get("to_state")
        event_id = event.get("event_id")
        delta = Decimal("0.00")
        reference = None
        if state == "RECEIVED":
            delta = _money(payload.get("net"))
            if event_id:
                received_event_ids.add(event_id)
        elif state == "SPENT":
            amount = _money(payload.get("amount"))
            if amount > balance:
                raise ValueError(f"financial SPENT {event_id} exceeds available Vera Fund balance")
            delta = -amount
        elif state == "REFUNDED":
            reference = payload.get("reverses_event_id")
            if reference not in received_event_ids:
                raise ValueError(
                    f"financial REFUNDED {event_id} references unknown prior RECEIVED event {reference}"
                )
            delta = -_money(payload.get("amount"))

        balance += delta
        rows.append({
            "event_id": event_id,
            "subject_id": event.get("subject_id"),
            "state": state,
            "currency": event_currency,
            "delta": delta,
            "balance": balance,
            "reference": reference,
        })

    return rows


def available_balance(events: list[dict]) -> Decimal:
    rows = financial_ledger(events)
    return rows[-1]["balance"] if rows else Decimal("0.00")


def decision_queues(events: list[dict]) -> dict[str, list[dict]]:
    queues = {
        "vera_decisions": [],
        "patrick_actions": [],
        "patrick_decisions": [],
        "automation_exceptions": [],
    }
    mapping = {
        "VERA_DECISION_REQUIRED": "vera_decisions",
        "PATRICK_ACTION_REQUIRED": "patrick_actions",
        "PATRICK_DECISION_REQUIRED": "patrick_decisions",
        "AUTOMATION_EXCEPTION": "automation_exceptions",
    }
    for hold in open_holds(events):
        kind = hold.get("payload", {}).get("hold_kind")
        queue = mapping.get(kind)
        if queue is not None:
            queues[queue].append(hold)
    return queues
