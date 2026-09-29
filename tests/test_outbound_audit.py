import sqlite3

import pytest

from vera_core import OutboundAuditError, OutboundExecutionAudit


def payload(stage):
    return {
        "stage": stage,
        "request_digest": "a" * 64,
        "authority_evidence_digest": "b" * 64,
        "currentness_evidence_digest": "c" * 64,
    }


def test_outbound_audit_enforces_order_and_verifies_chain(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    effect_id = "provider:test:e1"
    effect_kind = "PROVIDER/test/WRITE"
    for event_type in (
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "COMMITTED",
    ):
        audit.append(
            effect_id=effect_id,
            effect_kind=effect_kind,
            event_type=event_type,
            payload=payload(event_type),
        )
    assert audit.verify_chain() == audit.head
    events = audit.events(effect_id)
    assert [event.event_type for event in events] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "COMMITTED",
    ]
    assert audit.context()["effect_count"] == 1


def test_outbound_audit_accepts_attempted_unknown_terminal(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    for event_type in (
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "ATTEMPTED_UNKNOWN",
    ):
        audit.append(
            effect_id="pc:e1",
            effect_kind="PC/PING",
            event_type=event_type,
            payload=payload(event_type),
        )
    assert audit.latest("pc:e1").event_type == "ATTEMPTED_UNKNOWN"
    assert audit.verify_chain() == audit.head


def test_outbound_audit_rejects_stage_gap(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    audit.append(
        effect_id="provider:test:e1",
        effect_kind="PROVIDER/test/WRITE",
        event_type="AUTHORITY_VERIFIED",
        payload=payload("AUTHORITY_VERIFIED"),
    )
    audit.append(
        effect_id="provider:test:e1",
        effect_kind="PROVIDER/test/WRITE",
        event_type="EXECUTING",
        payload=payload("EXECUTING"),
    )
    with pytest.raises(OutboundAuditError):
        audit.verify_chain()


def test_outbound_audit_detects_persistent_tamper(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    audit.append(
        effect_id="coordination:c1",
        effect_kind="COORDINATION/coordination_post",
        event_type="AUTHORITY_VERIFIED",
        payload=payload("AUTHORITY_VERIFIED"),
    )
    with sqlite3.connect(audit.path) as db:
        db.execute(
            "UPDATE events SET payload_json='{}' WHERE sequence=1"
        )
    with pytest.raises(OutboundAuditError):
        audit.verify_chain()
