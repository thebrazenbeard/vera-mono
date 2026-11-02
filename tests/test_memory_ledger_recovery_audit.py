"""Read-only recovery audit: exact local ledger structure, not memory authority."""
import sqlite3

import pytest

from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger
from vera_memory.audit import audit_memory_ledger
from vera_memory.ledger import MemoryLedgerError


def _ledger(tmp_path):
    return MemoryLedger(tmp_path / "memory.sqlite", project_id="vera-mono", identity_id="vera")


def _admit(ledger, rid, *, supersedes=None):
    req = AdmissionRequest(
        record_id=rid, text="synthetic-" + rid,
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="unit-test", authority_ref="unit-test:authority",
        privacy_ref="unit-test:privacy", provenance_refs=("unit-test:source",),
        operation_id="op-" + rid, project_id="vera-mono",
        governed_identity_id="vera", supersedes=supersedes,
    )
    return ledger.admit(req, expected_head=ledger.current_head)


def _scan(ledger):
    return audit_memory_ledger(ledger.path, project_id="vera-mono", identity_id="vera")


def test_empty_and_superseded_ledger_audits_without_mutation(tmp_path):
    ledger = _ledger(tmp_path)
    empty = _scan(ledger)
    assert empty["records"] == 0 and empty["operations"] == 0
    first = _admit(ledger, "one")
    second = _admit(ledger, "two", supersedes="one")
    assert first["store_head"] != second["store_head"]
    report = _scan(ledger)
    assert report["records"] == 2
    assert report["operations"] == 2
    assert report["generation"] == 2
    assert report["head"] == ledger.current_head
    assert report["authorization_effect"] == "NONE"
    assert report["claim_ceiling"] == "INTERNAL_STRUCTURE_ONLY_NOT_PROVENANCE_OR_AUTHORITY"
    assert ledger.read("one").superseded_by == "two"


def test_unrelated_poisoned_payload_is_detected_in_full_scan(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "safe")
    _admit(ledger, "poisoned")
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE records SET payload_json='{bad' WHERE record_id='poisoned'")
    assert ledger.read("safe").record_id == "safe"
    with pytest.raises(MemoryLedgerError):
        _scan(ledger)


def test_mutable_supersession_status_corruption_fails(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    _admit(ledger, "two", supersedes="one")
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE records SET status='CURRENT',superseded_by=NULL WHERE record_id='one'")
    with pytest.raises(MemoryLedgerError, match="status|successor"):
        _scan(ledger)


def test_corrupted_operation_receipt_fails(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE operations SET receipt_json='{}' WHERE operation_id='op-one'")
    with pytest.raises(MemoryLedgerError):
        _scan(ledger)


def test_receipt_privacy_ref_disagreement_fails(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    with sqlite3.connect(ledger.path) as db:
        old = db.execute("SELECT receipt_json FROM operations").fetchone()[0]
        # A different but canonical JSON document should not override the
        # admission request fields committed in the hashed record.
        import json
        receipt = json.loads(old)
        receipt["privacy_ref"] = "privacy:forged"
        db.execute("UPDATE operations SET receipt_json=?",
                   (json.dumps(receipt, sort_keys=True, separators=(",", ":")),))
    with pytest.raises(MemoryLedgerError, match="receipt"):
        _scan(ledger)


def test_extra_receipt_authority_field_fails_closed(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    import json
    with sqlite3.connect(ledger.path) as db:
        old = db.execute("SELECT receipt_json FROM operations").fetchone()[0]
        data = json.loads(old)
        data["authorization_effect"] = "TRAIN"
        db.execute("UPDATE operations SET receipt_json=?",
                   (json.dumps(data, sort_keys=True, separators=(",", ":")),))
    with pytest.raises(MemoryLedgerError, match="receipt"):
        _scan(ledger)


def test_rowid_reordering_does_not_invalidate_receipt_generation(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    _admit(ledger, "two", supersedes="one")
    expected_head = ledger.current_head
    with sqlite3.connect(ledger.path) as db:
        # SQLite rowid is a mutable storage locator, not admission order.
        db.execute("UPDATE operations SET rowid=100 WHERE operation_id='op-one'")
    report = _scan(ledger)
    assert report["head"] == expected_head
    assert report["generation"] == 2


def test_duplicate_receipt_generation_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    _admit(ledger, "two")
    import json
    with sqlite3.connect(ledger.path) as db:
        raw = db.execute("SELECT receipt_json FROM operations WHERE operation_id='op-two'").fetchone()[0]
        item = json.loads(raw)
        item["generation"] = 1
        db.execute("UPDATE operations SET receipt_json=? WHERE operation_id='op-two'",
                   (json.dumps(item, sort_keys=True, separators=(",", ":")),))
    with pytest.raises(MemoryLedgerError, match="generation"):
        _scan(ledger)


def test_missing_operation_fails(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    with sqlite3.connect(ledger.path) as db:
        db.execute("DELETE FROM operations WHERE operation_id='op-one'")
    with pytest.raises(MemoryLedgerError, match="operation|count"):
        _scan(ledger)


def test_metadata_head_tampering_fails(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE meta SET value='forged' WHERE key='head'")
    with pytest.raises(MemoryLedgerError, match="head"):
        _scan(ledger)


def test_missing_path_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises((OSError, MemoryLedgerError, sqlite3.Error)):
        audit_memory_ledger(path, project_id="vera-mono", identity_id="vera")
    assert not path.exists()


def test_claim_cannot_be_forged_by_caller_arguments(tmp_path):
    ledger = _ledger(tmp_path)
    _admit(ledger, "one")
    with pytest.raises(MemoryLedgerError, match="project|identity"):
        audit_memory_ledger(ledger.path, project_id="wrong", identity_id="vera")
