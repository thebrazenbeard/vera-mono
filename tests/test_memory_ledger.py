import sqlite3

import pytest

from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger, StaleMemoryHead
from vera_memory.ledger import MemoryLedgerError


def _admit_test_record(ledger: MemoryLedger, record_id: str) -> None:
    ledger.admit(AdmissionRequest(
        record_id=record_id,
        text=f"text-{record_id}",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id=f"op-{record_id}",
        project_id="vera-mono",
        governed_identity_id="vera",
    ), expected_head=ledger.current_head)


def test_unrelated_malformed_payload_does_not_poison_valid_indexed_record_read(tmp_path):
    database = tmp_path / "memory.sqlite"
    ledger = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    _admit_test_record(ledger, "good")
    _admit_test_record(ledger, "unrelated")

    # Simulate repairing an existing JSON1 expression index in a current-schema
    # ledger. Real legacy schema migration is tested separately below.
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX IF EXISTS idx_vera_memory_supersedes_v1")
        db.execute("UPDATE records SET payload_json=? WHERE record_id=?",
                   ("{invalid", "unrelated"))

    restored = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    assert restored.read("good").text == "text-good"


def test_successor_lookup_uses_partial_index_not_full_ledger_json_scan(tmp_path):
    database = tmp_path / "memory.sqlite"
    ledger = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    _admit_test_record(ledger, "good")

    with sqlite3.connect(database) as db:
        plan = db.execute(
            """EXPLAIN QUERY PLAN SELECT payload_json,record_digest FROM records
               WHERE json_valid(payload_json)
                 AND json_extract(payload_json, '$.supersedes')=?""",
            ("good",),
        ).fetchall()
    assert any("USING INDEX idx_vera_memory_supersedes_v1" in str(row[-1])
               for row in plan), plan


def test_memory_ledger_cas_and_supersession(tmp_path):
    ledger = MemoryLedger(tmp_path / "memory.sqlite", project_id="vera-mono", identity_id="vera")
    head0 = ledger.current_head

    first = AdmissionRequest(
        record_id="m1",
        text="first",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id="vera-mono",
        governed_identity_id="vera",
    )
    receipt1 = ledger.admit(first, expected_head=head0)
    assert receipt1["store_head"] != head0
    assert ledger.read("m1").status == "CURRENT"

    second = AdmissionRequest(
        record_id="m2",
        text="corrected",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test", "correction:test"),
        operation_id="op2",
        project_id="vera-mono",
        governed_identity_id="vera",
        supersedes="m1",
    )
    receipt2 = ledger.admit(second, expected_head=receipt1["store_head"])
    assert ledger.read("m1").status == "SUPERSEDED"
    assert ledger.read("m2").status == "CURRENT"
    assert ledger.read("m1").superseded_by == "m2"

    try:
        ledger.admit(second, expected_head=head0)
    except Exception:
        raise AssertionError("idempotent replay should return the original receipt")
    assert ledger.admit(second, expected_head=head0) == receipt2


def test_duplicate_successor_json_key_cannot_revive_superseded_memory(tmp_path):
    """SQLite JSON1 chooses the first duplicate key; json.loads uses the last.

    A tampered successor must not escape the successor index merely because
    its duplicate earlier key points elsewhere while the canonical digest of
    the parsed object is unchanged.
    """
    database = tmp_path / "memory.sqlite"
    ledger = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    _admit_test_record(ledger, "old")
    ledger.admit(AdmissionRequest(
        record_id="new", text="corrected", memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test", authority_ref="authority:test", privacy_ref="privacy:test",
        provenance_refs=("source:test",), operation_id="op-new",
        project_id="vera-mono", governed_identity_id="vera", supersedes="old",
    ), expected_head=ledger.current_head)
    assert ledger.read("old").status == "SUPERSEDED"
    unchanged_head = ledger.current_head

    with sqlite3.connect(database) as db:
        old_payload, old_digest = db.execute(
            "SELECT payload_json,record_digest FROM records WHERE record_id='new'"
        ).fetchone()
        poisoned = old_payload.replace('"supersedes":',
                                       '"supersedes":"unrelated","supersedes":', 1)
        assert poisoned != old_payload
        db.execute("UPDATE records SET payload_json=? WHERE record_id='new'", (poisoned,))
        db.execute(
            "UPDATE records SET status='CURRENT',superseded_by=NULL WHERE record_id='old'"
        )
        assert db.execute(
            "SELECT record_digest FROM records WHERE record_id='new'"
        ).fetchone()[0] == old_digest

    assert ledger.current_head == unchanged_head
    with pytest.raises(MemoryLedgerError, match="successor|canonical|corrupt|duplicate"):
        ledger.read("old")


def test_real_legacy_schema_migrates_indexed_successor_relation(tmp_path):
    database = tmp_path / "memory.sqlite"
    ledger = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    _admit_test_record(ledger, "old")
    ledger.admit(AdmissionRequest(
        record_id="new", text="new", memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test", authority_ref="authority:test", privacy_ref="privacy:test",
        provenance_refs=("source:test",), operation_id="op-new",
        project_id="vera-mono", governed_identity_id="vera", supersedes="old",
    ), expected_head=ledger.current_head)
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX idx_vera_memory_supersedes_rel_v2")
        db.execute("ALTER TABLE records DROP COLUMN supersedes_id")

    migrated = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    assert migrated.read("old").superseded_by == "new"
    with sqlite3.connect(database) as db:
        assert db.execute(
            "SELECT supersedes_id FROM records WHERE record_id='new'"
        ).fetchone()[0] == "old"
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT record_id FROM records WHERE supersedes_id=?",
            ("old",),
        ).fetchall()
        assert any("idx_vera_memory_supersedes_rel_v2" in str(row[-1])
                   for row in plan), plan


def test_corrupt_legacy_duplicate_key_blocks_migration(tmp_path):
    database = tmp_path / "memory.sqlite"
    ledger = MemoryLedger(database, project_id="vera-mono", identity_id="vera")
    _admit_test_record(ledger, "old")
    with sqlite3.connect(database) as db:
        db.execute("DROP INDEX idx_vera_memory_supersedes_rel_v2")
        db.execute("ALTER TABLE records DROP COLUMN supersedes_id")
        db.execute(
            "UPDATE records SET payload_json=replace(payload_json, "
            "'\"supersedes\":', '\"supersedes\":\"decoy\",\"supersedes\":') "
            "WHERE record_id='old'"
        )
    with pytest.raises(MemoryLedgerError, match="duplicate"):
        MemoryLedger(database, project_id="vera-mono", identity_id="vera")


def test_stale_head_fails_closed(tmp_path):
    ledger = MemoryLedger(tmp_path / "memory.sqlite", project_id="vera-mono", identity_id="vera")
    request = AdmissionRequest(
        record_id="m1",
        text="first",
        memory_class=MemoryClass.HISTORICAL_AUDIT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id="vera-mono",
        governed_identity_id="vera",
    )
    try:
        ledger.admit(request, expected_head="wrong")
    except StaleMemoryHead:
        pass
    else:
        raise AssertionError("stale head was accepted")
