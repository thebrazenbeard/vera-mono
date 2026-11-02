"""Historical-kernel-inspired audit for the current governed ledger: tests first."""
from __future__ import annotations

import json
import sqlite3

import pytest

from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger
from vera_memory.integrity import audit_current_memory_ledger, CurrentMemoryAuditError


def admission(record_id: str, *, supersedes: str | None = None) -> AdmissionRequest:
    return AdmissionRequest(
        record_id=record_id,
        text=f"PRIVATE_DIAGNOSTIC_CONTENT_{record_id}",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="synthetic-test",
        authority_ref="synthetic:authority",
        privacy_ref="synthetic:private",
        provenance_refs=("test:only",),
        operation_id=f"op-{record_id}",
        project_id="vera-mono",
        governed_identity_id="vera",
        supersedes=supersedes,
    )


def setup_two(tmp_path):
    path = tmp_path / "memory.sqlite"
    store = MemoryLedger(path, project_id="vera-mono", identity_id="vera")
    store.admit(admission("old"), expected_head=store.current_head)
    store.admit(admission("new", supersedes="old"), expected_head=store.current_head)
    return path, store


def audit(path, **kw):
    return audit_current_memory_ledger(
        path, project_id="vera-mono", identity_id="vera", **kw)


def test_empty_readonly_audit_is_not_memory_admission(tmp_path):
    path = tmp_path / "empty.sqlite"
    store = MemoryLedger(path, project_id="vera-mono", identity_id="vera")
    prior = path.read_bytes()
    result = audit(path)
    assert result["ok"] is True
    assert result["record_count"] == 0
    assert result["generation"] == 0
    assert result["head"] == store.current_head
    assert result["evidence_class"].endswith("NOT_AUTHENTICATED")
    assert path.read_bytes() == prior
    assert not (tmp_path / "empty.sqlite-wal").exists()


def test_audit_reconstructs_admission_and_supersession_without_private_data(tmp_path):
    path, store = setup_two(tmp_path)
    prior = path.read_bytes()
    result = audit(path)
    assert result["ok"] is True
    assert result["record_count"] == 2
    assert result["operation_count"] == 2
    assert result["generation"] == 2
    assert result["superseded_count"] == 1
    assert result["head"] == store.current_head
    assert "PRIVATE_DIAGNOSTIC_CONTENT" not in json.dumps(result)
    assert path.read_bytes() == prior


def test_corrupted_status_cannot_pass(tmp_path):
    path, _ = setup_two(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE records SET status='CURRENT',superseded_by=NULL WHERE record_id='old'")
    with pytest.raises(CurrentMemoryAuditError, match="supersession"):
        audit(path)


def test_corrupted_record_digest_or_duplicate_json_key_cannot_pass(tmp_path):
    path, _ = setup_two(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE records SET record_digest='wrong' WHERE record_id='new'")
    with pytest.raises(CurrentMemoryAuditError, match="record"):
        audit(path)


def test_noncanonical_receipt_and_header_mismatch_fail(tmp_path):
    path, _ = setup_two(tmp_path)
    with sqlite3.connect(path) as db:
        receipt = db.execute("SELECT receipt_json FROM operations WHERE operation_id='op-new'").fetchone()[0]
        db.execute("UPDATE operations SET receipt_json=? WHERE operation_id='op-new'",
                   ('{"generation":999,' + receipt[1:],))
    with pytest.raises(CurrentMemoryAuditError, match="receipt"):
        audit(path)


def test_missing_operation_and_forged_meta_fail(tmp_path):
    path, _ = setup_two(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM operations WHERE operation_id='op-new'")
    with pytest.raises(CurrentMemoryAuditError, match="count|operation"):
        audit(path)

    db2 = tmp_path / "forged.sqlite"
    store = MemoryLedger(db2, project_id="vera-mono", identity_id="vera")
    store.admit(admission("old"), expected_head=store.current_head)
    with sqlite3.connect(db2) as db:
        db.execute("UPDATE meta SET value=? WHERE key='head'", ("f" * 64,))
    with pytest.raises(CurrentMemoryAuditError, match="head"):
        audit(db2)


def test_wrong_identity_rejects_and_oversize_fails_closed(tmp_path):
    path, _ = setup_two(tmp_path)
    with pytest.raises(CurrentMemoryAuditError, match="identity|project"):
        audit_current_memory_ledger(path, project_id="vera-mono", identity_id="other")
    with pytest.raises(CurrentMemoryAuditError, match="limit"):
        audit(path, max_records=1)
    with pytest.raises(CurrentMemoryAuditError, match="size"):
        audit(path, max_database_bytes=1)


def test_missing_file_and_symlink_rejected(tmp_path):
    with pytest.raises(CurrentMemoryAuditError, match="file"):
        audit(tmp_path / "missing.sqlite")
    path, _ = setup_two(tmp_path)
    link = tmp_path / "symlink.sqlite"
    try:
        link.symlink_to(path)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem cannot create symlinks")
    with pytest.raises(CurrentMemoryAuditError, match="symlink"):
        audit(link)


def test_record_json_duplicate_key_fails_closed(tmp_path):
    path, _ = setup_two(tmp_path)
    with sqlite3.connect(path) as db:
        raw = db.execute("SELECT payload_json FROM records WHERE record_id='new'").fetchone()[0]
        poisoned = raw.replace('"supersedes":', '"supersedes":"old","supersedes":', 1)
        db.execute("UPDATE records SET payload_json=? WHERE record_id='new'", (poisoned,))
    with pytest.raises(CurrentMemoryAuditError, match="record"):
        audit(path)
