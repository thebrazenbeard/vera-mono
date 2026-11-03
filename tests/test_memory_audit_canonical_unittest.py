"""Synthetic regression for bounded canonical current-ledger structural audit."""
from __future__ import annotations

from contextlib import closing
import json
import os
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex
from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger, StaleMemoryHead
from vera_memory.integrity import CurrentMemoryAuditError, audit_current_memory_ledger


def _request() -> AdmissionRequest:
    return AdmissionRequest(
        record_id="one", text="synthetic-only", memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="fixture", authority_ref="fixture:unverified",
        privacy_ref="fixture:private", provenance_refs=("fixture:source",),
        operation_id="operation-one", project_id="project", governed_identity_id="identity",
    )


def _rewrite_consistent_invalid_payload(path: Path, change) -> None:
    """Re-seal every internal hash/head, simulating a fully coherent malicious writer.

    The audit must still reject payloads that the public AdmissionRequest API
    would reject, even if the internal hashes and receipt chain agree.
    """
    with closing(sqlite3.connect(path)) as db, db:
        payload = json.loads(db.execute("SELECT payload_json FROM records").fetchone()[0])
        change(payload)
        request_fields = {k: v for k, v in payload.items() if k != "request_digest"}
        payload["request_digest"] = sha256_hex(canonical_json_bytes(request_fields))
        digest = sha256_hex(canonical_json_bytes(payload))
        db.execute("UPDATE records SET payload_json=?,record_digest=?",
                   (canonical_json(payload), digest))
        receipt = json.loads(db.execute("SELECT receipt_json FROM operations").fetchone()[0])
        receipt["request_digest"] = payload["request_digest"]
        receipt["record_digest"] = digest
        receipt["memory_class"] = payload["memory_class"]
        receipt["provenance_refs"] = payload["provenance_refs"]
        genesis = sha256_hex(b"vera-memory-genesis-v1")
        new_head = sha256_hex(canonical_json_bytes({
            "previous_head": genesis, "generation": 1,
            "record_id": payload["record_id"], "record_digest": digest,
            "supersedes": None,
        }))
        receipt["store_head"] = new_head
        db.execute("UPDATE operations SET request_digest=?,receipt_json=?",
                   (payload["request_digest"], canonical_json(receipt)))
        db.execute("UPDATE meta SET value=? WHERE key='head'", (new_head,))


class CanonicalMemoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vera-audit-synthetic-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.sqlite"
        self.ledger = MemoryLedger(self.path, project_id="project", identity_id="identity")

    def _audit(self, **kw):
        return audit_current_memory_ledger(
            self.path, project_id="project", identity_id="identity", **kw,
        )

    def test_empty_ledger_reads_without_mutation(self):
        before = self.path.read_bytes()
        result = self._audit()
        self.assertEqual(result["record_count"], 0)
        self.assertEqual(result["claim_ceiling"],
                         "LOCAL_STRUCTURAL_CONSISTENCY_NOT_EXTERNAL_ATTESTATION")
        self.assertEqual(self.path.read_bytes(), before)

    def test_valid_single_admission(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        result = self._audit()
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["generation"], 1)

    def test_supersession_chain_and_privacy(self):
        first = _request()
        self.ledger.admit(first, expected_head=self.ledger.current_head)
        second = replace(first, record_id="second", text="SECRET_FIXTURE_MARKER",
                         operation_id="operation-two", supersedes="one")
        self.ledger.admit(second, expected_head=self.ledger.current_head)
        before = self.path.read_bytes()
        result = self._audit()
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["superseded_count"], 1)
        self.assertEqual(result["generation"], 2)
        self.assertNotIn("SECRET_FIXTURE_MARKER", json.dumps(result))
        self.assertEqual(self.path.read_bytes(), before)

    def test_record_digest_and_receipt_mutations_fail(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE records SET record_digest='wrong'")
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()
        # Independently produce a healthy ledger, then poison its receipt.
        fresh = Path(self.tmp.name) / "receipt.sqlite"
        ledger = MemoryLedger(fresh, project_id="project", identity_id="identity")
        ledger.admit(_request(), expected_head=ledger.current_head)
        with closing(sqlite3.connect(fresh)) as db, db:
            db.execute("UPDATE operations SET request_digest='wrong'")
        with self.assertRaises(CurrentMemoryAuditError):
            audit_current_memory_ledger(fresh, project_id="project", identity_id="identity")

    def test_schema_and_binding_mutations_fail(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        with self.assertRaises(CurrentMemoryAuditError):
            audit_current_memory_ledger(self.path, project_id="project", identity_id="wrong")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE meta SET value=? WHERE key='head'", ("f" * 64,))
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()

    def test_wal_header_refused_without_creating_sidecars(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.assertEqual(self.path.read_bytes()[18:20], bytes((2, 2)))
        before = self.path.read_bytes()
        before_sidecars = {
            suffix: Path(str(self.path) + suffix).read_bytes()
            for suffix in ("-wal", "-shm")
            if Path(str(self.path) + suffix).exists()
        }
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()
        self.assertEqual(self.path.read_bytes(), before)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            self.assertEqual(sidecar.exists(), suffix in before_sidecars)
            if sidecar.exists():
                self.assertEqual(sidecar.read_bytes(), before_sidecars[suffix])

    def test_memory_ledger_closes_every_connection(self):
        # Unlike a file-unlink check, this catches the leak deterministically
        # on Linux too: SQLite's connection context manager only commits.
        underlying_connect = sqlite3.connect
        connections = []

        class TrackingConnection(sqlite3.Connection):
            closed_explicitly = False

            def close(self):
                self.closed_explicitly = True
                super().close()

        def tracked_connect(*args, **kwargs):
            connection = underlying_connect(*args, factory=TrackingConnection, **kwargs)
            connections.append(connection)
            return connection

        tracked_path = Path(self.tmp.name) / "tracked.sqlite"
        with patch("vera_memory.ledger.sqlite3.connect", side_effect=tracked_connect):
            ledger = MemoryLedger(tracked_path, project_id="project", identity_id="identity")
            ledger.admit(_request(), expected_head=ledger.current_head)
            ledger.read("one")
            with self.assertRaises(StaleMemoryHead):
                ledger.admit(replace(_request(), record_id="two",
                                     operation_id="operation-stale"), expected_head="stale")
        self.assertEqual(len(connections), 5)
        self.assertTrue(all(conn.closed_explicitly for conn in connections))

    def test_connect_setup_exception_closes_connection(self):
        underlying_connect = sqlite3.connect
        connections = []

        class FailingSetupConnection(sqlite3.Connection):
            closed_explicitly = False

            def execute(self, sql, *args, **kwargs):
                if sql == "PRAGMA foreign_keys = ON":
                    raise sqlite3.OperationalError("synthetic PRAGMA failure")
                return super().execute(sql, *args, **kwargs)

            def close(self):
                self.closed_explicitly = True
                super().close()

        def failing_connect(*args, **kwargs):
            connection = underlying_connect(*args, factory=FailingSetupConnection, **kwargs)
            connections.append(connection)
            return connection

        with patch("vera_memory.ledger.sqlite3.connect", side_effect=failing_connect):
            with self.assertRaises(sqlite3.OperationalError):
                MemoryLedger(Path(self.tmp.name) / "setup-failure.sqlite",
                             project_id="project", identity_id="identity")
        self.assertEqual(len(connections), 1)
        self.assertTrue(connections[0].closed_explicitly)

    @unittest.skipUnless(os.name == "nt", "Windows file-lock semantics required")
    def test_windows_completed_audit_releases_ledger_file(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        self._audit()
        # Windows refuses unlink when a SQLite connection still holds the file.
        self.path.unlink()
        self.assertFalse(self.path.exists())

    def test_symlink_and_missing_file_refused(self):
        with self.assertRaises(CurrentMemoryAuditError):
            audit_current_memory_ledger(Path(self.tmp.name) / "absent.sqlite",
                                        project_id="project", identity_id="identity")
        link = Path(self.tmp.name) / "ledger-link.sqlite"
        try:
            link.symlink_to(self.path)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem does not support symlink fixtures")
        with self.assertRaises(CurrentMemoryAuditError):
            audit_current_memory_ledger(link, project_id="project", identity_id="identity")

    def test_unexpected_meta_key_fails_closed(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO meta(key,value) VALUES('unrecognized-future-key','synthetic')")
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()

    def test_dangling_symlink_sidecars_are_not_ignored(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(self.path) + suffix)
            try:
                sidecar.symlink_to(Path(self.tmp.name) / "nonexistent-target")
            except (OSError, NotImplementedError):
                self.skipTest("filesystem cannot create symlink fixtures")
            try:
                self.assertTrue(sidecar.is_symlink())
                self.assertFalse(sidecar.exists())
                with self.assertRaises(CurrentMemoryAuditError):
                    self._audit()
            finally:
                sidecar.unlink()

    def test_deeply_nested_invalid_json_returns_declared_audit_error(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        nested = "[" * 10_000 + "0" + "]" * 10_000
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE records SET payload_json=?", (nested,))
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()

        fresh = Path(self.tmp.name) / "bad-receipt.sqlite"
        ledger = MemoryLedger(fresh, project_id="project", identity_id="identity")
        ledger.admit(_request(), expected_head=ledger.current_head)
        with closing(sqlite3.connect(fresh)) as db, db:
            db.execute("UPDATE operations SET receipt_json=?", (nested,))
        with self.assertRaises(CurrentMemoryAuditError):
            audit_current_memory_ledger(fresh, project_id="project", identity_id="identity")

    def test_self_consistent_empty_text_is_rejected(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        _rewrite_consistent_invalid_payload(self.path, lambda p: p.update(text=""))
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()

    def test_self_consistent_unknown_memory_class_is_rejected(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        _rewrite_consistent_invalid_payload(self.path,
                                            lambda p: p.update(memory_class="UNKNOWN_CLASS"))
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()

    def test_self_consistent_duplicate_provenance_is_rejected(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        _rewrite_consistent_invalid_payload(self.path,
                                            lambda p: p.update(provenance_refs=["same", "same"]))
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()

    def test_hard_row_cap_and_sidecar_refusal(self):
        self.ledger.admit(_request(), expected_head=self.ledger.current_head)
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit(max_records=0)
        sidecar = Path(str(self.path) + "-wal")
        sidecar.write_bytes(b"synthetic")
        with self.assertRaises(CurrentMemoryAuditError):
            self._audit()


if __name__ == "__main__":
    unittest.main()
