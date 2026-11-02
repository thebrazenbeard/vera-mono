"""Synthetic negative controls for impossible stored admission schemas.

All records are generated in a temporary database; no archived or personal
content is used. Recompute every other digest so only API-shape validation
can reject the coherent but impossible record.
"""
import json
import sqlite3

import pytest

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)
from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger
from vera_memory.audit import audit_memory_ledger
from vera_memory.ledger import MemoryLedgerError


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "missing_field",
        "empty_text",
        "invalid_class",
        "duplicate_provenance",
        "nonlist_provenance",
    ),
)
def test_audit_rejects_api_impossible_coherent_record(tmp_path, mutation):
    path = tmp_path / "synthetic.sqlite"
    ledger = MemoryLedger(path, project_id="synthetic-project", identity_id="synthetic-agent")
    ledger.admit(
        AdmissionRequest(
            record_id="synthetic-record",
            text="synthetic content only",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="synthetic-test",
            authority_ref="synthetic:authority",
            privacy_ref="synthetic:privacy",
            provenance_refs=("synthetic:source",),
            operation_id="synthetic-operation",
            project_id="synthetic-project",
            governed_identity_id="synthetic-agent",
        ),
        expected_head=ledger.current_head,
    )
    scope = {"project_id": "synthetic-project", "identity_id": "synthetic-agent"}
    assert audit_memory_ledger(path, **scope)["status"] == "CONSISTENT_LOCAL_STRUCTURE_ONLY"

    with sqlite3.connect(path) as db:
        payload = json.loads(db.execute(
            "SELECT payload_json FROM records WHERE record_id='synthetic-record'"
        ).fetchone()[0])
        if mutation == "extra_field":
            payload["forged_extra"] = "synthetic"
        elif mutation == "missing_field":
            del payload["source_actor"]
        elif mutation == "empty_text":
            payload["text"] = ""
        elif mutation == "invalid_class":
            payload["memory_class"] = "NOT_A_MEMORY_CLASS"
        elif mutation == "duplicate_provenance":
            payload["provenance_refs"] = ["synthetic:source", "synthetic:source"]
        elif mutation == "nonlist_provenance":
            payload["provenance_refs"] = "synthetic:source"

        request_fields = {key: value for key, value in payload.items()
                          if key != "request_digest"}
        payload["request_digest"] = sha256_hex(canonical_json_bytes(request_fields))
        record_digest = sha256_hex(canonical_json_bytes(payload))
        db.execute(
            "UPDATE records SET payload_json=?,record_digest=? "
            "WHERE record_id='synthetic-record'",
            (canonical_json(payload), record_digest),
        )
        receipt = json.loads(db.execute(
            "SELECT receipt_json FROM operations WHERE operation_id='synthetic-operation'"
        ).fetchone()[0])
        receipt["request_digest"] = payload["request_digest"]
        receipt["record_digest"] = record_digest
        if "memory_class" in payload:
            receipt["memory_class"] = payload["memory_class"]
        if "provenance_refs" in payload:
            receipt["provenance_refs"] = payload["provenance_refs"]
        head = sha256_hex(canonical_json_bytes({
            "previous_head": sha256_hex(b"vera-memory-genesis-v1"),
            "generation": 1,
            "record_id": "synthetic-record",
            "record_digest": record_digest,
            "supersedes": None,
        }))
        receipt["store_head"] = head
        db.execute(
            "UPDATE operations SET request_digest=?,receipt_json=? "
            "WHERE operation_id='synthetic-operation'",
            (payload["request_digest"], canonical_json(receipt)),
        )
        db.execute("UPDATE meta SET value=? WHERE key='head'", (head,))

    with pytest.raises(MemoryLedgerError, match="stored admission payload"):
        audit_memory_ledger(path, **scope)
