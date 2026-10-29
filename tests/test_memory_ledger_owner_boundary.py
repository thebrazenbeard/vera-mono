"""Synthetic owner-rebinding negatives for the local memory ledger.

No production state, private content, model gateway, or network is used.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger
from vera_memory.ledger import MemoryLedgerError


def admission(project, identity, record, *, supersedes=None):
    return AdmissionRequest(
        record_id=record, text=f"synthetic-{record}",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test-only", authority_ref="not-an-authority",
        privacy_ref="synthetic", provenance_refs=("synthetic:test",),
        operation_id=f"operation-{record}", project_id=project,
        governed_identity_id=identity, supersedes=supersedes,
    )


class MemoryOwnerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "memory.sqlite"

    def test_reopening_nonempty_root_with_another_project_denied(self):
        alice = MemoryLedger(self.db, project_id="A", identity_id="Alice")
        alice.admit(admission("A", "Alice", "A-private"), expected_head=alice.current_head)
        with self.assertRaises(MemoryLedgerError):
            MemoryLedger(self.db, project_id="B", identity_id="Bob")

    def test_reopening_empty_root_with_another_identity_denied(self):
        MemoryLedger(self.db, project_id="A", identity_id="Alice")
        with self.assertRaises(MemoryLedgerError):
            MemoryLedger(self.db, project_id="A", identity_id="Bob")

    def test_same_owner_restart_and_distinct_roots(self):
        first = MemoryLedger(self.db, project_id="A", identity_id="Alice")
        first.admit(admission("A", "Alice", "same"), expected_head=first.current_head)
        restarted = MemoryLedger(self.db, project_id="A", identity_id="Alice")
        self.assertEqual(restarted.read("same").text, "synthetic-same")
        second = MemoryLedger(Path(self.tmp.name) / "other.sqlite", project_id="B", identity_id="Bob")
        self.assertRaises(KeyError, second.read, "same")

    def test_unbound_existing_nonempty_ledger_not_silently_claimed(self):
        first = MemoryLedger(self.db, project_id="A", identity_id="Alice")
        first.admit(admission("A", "Alice", "legacy"), expected_head=first.current_head)
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM meta WHERE key IN ('owner_project_id','owner_identity_id')")
        with self.assertRaises(MemoryLedgerError):
            MemoryLedger(self.db, project_id="A", identity_id="Alice")

    def test_foreign_valid_record_cannot_be_read_or_superseded(self):
        alice = MemoryLedger(self.db, project_id="A", identity_id="Alice")
        bob_db = Path(self.tmp.name) / "bob.sqlite"
        bob = MemoryLedger(bob_db, project_id="B", identity_id="Bob")
        bob.admit(admission("B", "Bob", "foreign"), expected_head=bob.current_head)

        # Synthetic contamination simulates an inconsistent migration/import;
        # records are canonically valid, but belong to another owner.
        with sqlite3.connect(bob_db) as db:
            payload, digest = db.execute(
                "SELECT payload_json,record_digest FROM records WHERE record_id='foreign'"
            ).fetchone()
        with sqlite3.connect(self.db) as db:
            db.execute(
                "INSERT INTO records(record_id,payload_json,status,superseded_by,"
                "record_digest,supersedes_id) VALUES(?,?,?,?,?,?)",
                ("foreign", payload, "CURRENT", None, digest, None),
            )
        with self.assertRaises(MemoryLedgerError):
            alice.read("foreign")
        with self.assertRaises(MemoryLedgerError):
            alice.admit(admission("A", "Alice", "attempt", supersedes="foreign"),
                        expected_head=alice.current_head)
        with sqlite3.connect(self.db) as db:
            status = db.execute(
                "SELECT status FROM records WHERE record_id='foreign'"
            ).fetchone()[0]
        self.assertEqual(status, "CURRENT")

    def test_partial_owner_marker_rejected(self):
        MemoryLedger(self.db, project_id="A", identity_id="Alice")
        with sqlite3.connect(self.db) as db:
            db.execute("DELETE FROM meta WHERE key='owner_identity_id'")
        with self.assertRaises(MemoryLedgerError):
            MemoryLedger(self.db, project_id="A", identity_id="Alice")

    def test_unrelated_database_sentinel_is_not_adopted_or_modified(self):
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE unrelated_private (secret TEXT NOT NULL)")
            db.execute("INSERT INTO unrelated_private(secret) VALUES ('sentinel')")
        original = self.db.read_bytes()
        with self.assertRaisesRegex(MemoryLedgerError, "unbound existing"):
            MemoryLedger(self.db, project_id="A", identity_id="Alice")
        self.assertEqual(self.db.read_bytes(), original)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT secret FROM unrelated_private").fetchone()[0], "sentinel")
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='meta'").fetchone())

    def test_header_only_foreign_sqlite_database_is_not_adopted(self):
        with sqlite3.connect(self.db) as db:
            db.execute("PRAGMA user_version=11")
            db.execute("PRAGMA application_id=123456")
        original = self.db.read_bytes()
        with self.assertRaisesRegex(MemoryLedgerError, "unbound existing"):
            MemoryLedger(self.db, project_id="A", identity_id="Alice")
        self.assertEqual(self.db.read_bytes(), original)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 11)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='meta'").fetchone())

    def test_state_directory_cannot_rebind_identity_over_same_root(self):
        from vera_core import VeraStateDirectory

        root = Path(self.tmp.name) / "state"
        VeraStateDirectory(root, project_id="A", identity_id="Alice").open()
        with self.assertRaises(MemoryLedgerError):
            VeraStateDirectory(root, project_id="B", identity_id="Bob").open()

    def test_ephemeral_memory_and_uri_paths_cannot_claim_durable_ledger(self):
        for path in ("", " ", ":memory:", Path(":memory:"), "file::memory:?cache=shared"):
            with self.subTest(path=repr(path)):
                with self.assertRaisesRegex(MemoryLedgerError, "durable filesystem path"):
                    MemoryLedger(path, project_id="A", identity_id="Alice")


if __name__ == "__main__":
    unittest.main()
