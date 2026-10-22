"""Windows-sensitive SQLite handle-release regressions; no GC dependency."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from vera_core.behavior_attestation import BehaviorAttestationStore


class AttestationCloseTest(unittest.TestCase):
    def test_constructor_normal_exception_repeated_and_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attestation.sqlite"
            owner = BehaviorAttestationStore(path)
            for i in range(3):
                with owner._connect() as db:
                    self.assertEqual(db.execute("SELECT 1").fetchone()[0], 1)
                self.assertRaises(sqlite3.ProgrammingError, db.execute, "SELECT 1")
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    with owner._connect() as db:
                        raise RuntimeError("injected")
                self.assertRaises(sqlite3.ProgrammingError, db.execute, "SELECT 1")
            renamed = path.with_name("attestation-moved.sqlite")
            os.replace(path, renamed)
            os.replace(renamed, path)
            other_owner = BehaviorAttestationStore(path)
            with other_owner._connect() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM attestations").fetchone()[0], 0)
            self.assertRaises(sqlite3.ProgrammingError, db.execute, "SELECT 1")
