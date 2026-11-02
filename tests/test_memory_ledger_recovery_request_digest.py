"""Synthetic regression: a receipt must bind to an actual admission request."""
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


def test_audit_rejects_impossible_request_digest_even_with_recomputed_local_chain(tmp_path):
    """A valid record hash and receipt head cannot substitute for request binding."""
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
    kwargs = {"project_id": "synthetic-project", "identity_id": "synthetic-agent"}
    assert audit_memory_ledger(path, **kwargs)["status"] == "CONSISTENT_LOCAL_STRUCTURE_ONLY"

    # Simulate a structurally coherent but API-impossible local ledger: change
    # the embedded request digest, then consistently recompute all *other*
    # record/receipt/head digests. No historical or personal data is involved.
    with sqlite3.connect(path) as db:
        payload = json.loads(db.execute(
            "SELECT payload_json FROM records WHERE record_id='synthetic-record'"
        ).fetchone()[0])
        payload["request_digest"] = "0" * 64
        new_record_digest = sha256_hex(canonical_json_bytes(payload))
        db.execute(
            "UPDATE records SET payload_json=?,record_digest=? WHERE record_id='synthetic-record'",
            (canonical_json(payload), new_record_digest),
        )
        receipt = json.loads(db.execute(
            "SELECT receipt_json FROM operations WHERE operation_id='synthetic-operation'"
        ).fetchone()[0])
        receipt["request_digest"] = payload["request_digest"]
        receipt["record_digest"] = new_record_digest
        new_head = sha256_hex(canonical_json_bytes({
            "previous_head": sha256_hex(b"vera-memory-genesis-v1"),
            "generation": 1,
            "record_id": "synthetic-record",
            "record_digest": new_record_digest,
            "supersedes": None,
        }))
        receipt["store_head"] = new_head
        db.execute(
            "UPDATE operations SET request_digest=?,receipt_json=? "
            "WHERE operation_id='synthetic-operation'",
            (payload["request_digest"], canonical_json(receipt)),
        )
        db.execute("UPDATE meta SET value=? WHERE key='head'", (new_head,))

    with pytest.raises(MemoryLedgerError, match="request digest"):
        audit_memory_ledger(path, **kwargs)
