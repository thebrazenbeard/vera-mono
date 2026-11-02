"""Regression tests for read-only historical v0.2.3 kernel event audits."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from vera_memory.legacy_kernel_audit import (
    LegacyKernelAuditError,
    audit_legacy_kernel_database,
)


def make_legacy(path: Path) -> Path:
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE sources(
                source_id TEXT PRIMARY KEY, content TEXT NOT NULL,
                lineage_id TEXT NOT NULL);
            CREATE TABLE memories(
                memory_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
                lineage_id TEXT NOT NULL, content TEXT NOT NULL);
            CREATE TABLE events(
                event_id TEXT PRIMARY KEY, event_seq INTEGER UNIQUE,
                event_type TEXT NOT NULL, subject_id TEXT NOT NULL,
                payload_json TEXT NOT NULL);
            CREATE TABLE projection_versions(
                projection_name TEXT PRIMARY KEY, projection_version TEXT NOT NULL,
                reducer_version TEXT NOT NULL, schema_version TEXT NOT NULL);
            CREATE TABLE relationships(
                relation_id TEXT PRIMARY KEY, source_memory_id TEXT NOT NULL,
                target_memory_id TEXT NOT NULL);
            CREATE TABLE migration_records(
                migration_id TEXT PRIMARY KEY,
                legacy_event_id TEXT UNIQUE NOT NULL,
                canonical_source_id TEXT NOT NULL,
                canonical_source_hash TEXT NOT NULL,
                migration_version TEXT NOT NULL);
        """)
        con.execute("INSERT INTO projection_versions VALUES(?,?,?,?)",
                    ("logical_memory", "1.0.0", "1.0.0", "1.0.0"))
        con.execute("INSERT INTO sources VALUES(?,?,?)",
                    ("src1", "PRIVATE_DONT_LEAK", "lineage1"))
        con.execute("INSERT INTO memories VALUES(?,?,?,?)",
                    ("mem1", "src1", "lineage1", "PRIVATE_DONT_LEAK"))
        con.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                    ("evt1", 1, "source_created", "src1", "{}"))
        con.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                    ("evt2", 2, "memory_created", "mem1",
                     json.dumps({"record": {"source_id": "src1", "lineage_id": "lineage1",
                                             "content": "PRIVATE_DONT_LEAK"}})))
    return path


def test_valid_legacy_database_audits_without_leaking_or_mutating(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    before = db.read_bytes()
    result = audit_legacy_kernel_database(db)
    assert result["ok"] is True
    assert result["counts"]["sources"] == 1
    assert result["counts"]["memories"] == 1
    assert result["counts"]["events"] == 2
    assert result["findings"] == {}
    assert "NOT_MEMORY_ADMISSION" in result["evidence_class"]
    assert "PRIVATE_DONT_LEAK" not in json.dumps(result)
    assert db.read_bytes() == before
    assert not (tmp_path / "legacy.sqlite-wal").exists()
    assert not (tmp_path / "legacy.sqlite-shm").exists()


def test_unhandled_event_gaps_or_unreplayable_payload_reported(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                    ("evt3", 4, "unknown_legacy", "unknown", "{}"))
        con.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                    ("evt4", 5, "memory_created", "another", "{bad-json"))
    report = audit_legacy_kernel_database(db)
    assert report["ok"] is False
    assert report["findings"]["unhandled_event_type"] == 1
    assert report["findings"]["noncontiguous_event_sequence"] >= 1
    assert report["findings"]["invalid_event_payload"] >= 1


def test_orphan_lineage_and_projection_without_origin_detected(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO memories VALUES(?,?,?,?)",
                    ("orphan", "missing", "other", "PRIVATE_DONT_LEAK"))
    findings = audit_legacy_kernel_database(db)["findings"]
    assert findings["orphaned_memory_source"] == 1
    assert findings["projection_without_origin_event"] == 1


def test_invalid_projection_version_is_not_promoted(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("UPDATE projection_versions SET reducer_version='9.9.9'")
    result = audit_legacy_kernel_database(db)
    assert not result["ok"]
    assert result["findings"]["incompatible_projection_version"] == 1


def test_legacy_identifier_only_memory_event_is_not_replayable(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("UPDATE events SET payload_json=? WHERE event_id='evt2'",
                    (json.dumps({"source_id": "src1"}),))
    result = audit_legacy_kernel_database(db)
    assert not result["ok"]
    assert result["findings"]["unreplayable_legacy_memory_event"] == 1


def test_deny_symlink_wal_wrong_schema_and_non_sqlite(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    try:
        (tmp_path / "alias.sqlite").symlink_to(db)
    except (OSError, NotImplementedError):
        pass
    else:
        with pytest.raises(LegacyKernelAuditError, match="symbolic"):
            audit_legacy_kernel_database(tmp_path / "alias.sqlite")

    (tmp_path / "legacy.sqlite-wal").write_bytes(b"placeholder")
    with pytest.raises(LegacyKernelAuditError, match="sidecar"):
        audit_legacy_kernel_database(db)
    (tmp_path / "legacy.sqlite-wal").unlink()

    invalid = tmp_path / "not-sqlite.db"
    invalid.write_bytes(b"this is not sqlite")
    with pytest.raises(LegacyKernelAuditError, match="SQLite"):
        audit_legacy_kernel_database(invalid)

    with sqlite3.connect(db) as con:
        con.execute("DROP TABLE projection_versions")
    with pytest.raises(LegacyKernelAuditError, match="schema"):
        audit_legacy_kernel_database(db)


def test_reject_duplicate_json_keys_and_wrong_payload_shape(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("UPDATE events SET payload_json=? WHERE event_id='evt2'",
                    ('{"record":{"source_id":"src1","source_id":"src2"}}',))
    findings = audit_legacy_kernel_database(db)["findings"]
    assert findings["invalid_event_payload"] == 1


def test_size_limit_and_batch_bound(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with pytest.raises(LegacyKernelAuditError, match="size"):
        audit_legacy_kernel_database(db, max_db_bytes=100)
    with pytest.raises(LegacyKernelAuditError, match="limit"):
        audit_legacy_kernel_database(db, max_rows=1)



def test_reject_wal_header_even_if_no_sidecar_exists(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    # A detached WAL-mode database may omit uncheckpointed transactions.
    # The auditor must reject the mode before trusting immutable=1 reads.
    raw = bytearray(db.read_bytes())
    raw[18] = 2
    raw[19] = 2
    db.write_bytes(raw)
    with pytest.raises(LegacyKernelAuditError, match="WAL"):
        audit_legacy_kernel_database(db)


def test_relationship_projection_without_origin_event_is_visible(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO relationships VALUES(?,?,?)",
                    ("rel-orphan", "mem1", "mem1"))
    report = audit_legacy_kernel_database(db)
    assert report["ok"] is False
    assert report["findings"]["relationship_without_origin_event"] == 1
    assert "rel-orphan" not in json.dumps(report)


def test_relationship_with_origin_event_and_known_endpoints_is_supported(tmp_path):
    db = make_legacy(tmp_path / "legacy.sqlite")
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO relationships VALUES(?,?,?)",
                    ("rel1", "mem1", "mem1"))
        con.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                    ("evt3", 3, "relationship_created", "rel1",
                     json.dumps({"record": {"relation_id": "rel1",
                                            "source_memory_id": "mem1",
                                            "target_memory_id": "mem1"}})))
    report = audit_legacy_kernel_database(db)
    assert report["ok"] is True
    assert report["counts"]["relationships"] == 1
    assert report["findings"] == {}
