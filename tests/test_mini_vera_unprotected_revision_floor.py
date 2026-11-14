"""Unprotected cross-process authority revision floor: source-level proof, NOT OS security."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from tools.mini_vera.unprotected_revision_floor import (
    RevisionFloorRefused, UnprotectedRevisionFloor,
)

ROOT = Path(__file__).resolve().parents[1]


class UnprotectedRevisionFloorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(prefix="mini-vera-revfloor-")
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "authority-floor.sqlite"

    def test_first_write_and_restart_preserve_monotonic_revision(self):
        first = UnprotectedRevisionFloor(self.path)
        self.assertEqual(10, first.advance(10))
        self.assertEqual(12, first.advance(12))
        second = UnprotectedRevisionFloor(self.path)
        self.assertEqual(12, second.advance(10))
        self.assertEqual(12, second.advance(12))
        self.assertEqual(13, second.advance(13))
        self.assertEqual(13, UnprotectedRevisionFloor(self.path).advance(0))

    def test_full_uint64_range_never_loses_precision(self):
        high = 2**64-2
        floor = UnprotectedRevisionFloor(self.path)
        self.assertEqual(high, floor.advance(high))
        self.assertEqual(2**64-1, floor.advance(2**64-1))
        self.assertEqual(2**64-1,
                         UnprotectedRevisionFloor(self.path).advance(9))

    def test_invalid_values_and_path_refused_before_creating_file(self):
        floor = UnprotectedRevisionFloor(self.path)
        for value in (True, -1, 1.2, "2", None, 2**64):
            with self.subTest(value=value):
                with self.assertRaises(RevisionFloorRefused):
                    floor.advance(value)
                self.assertFalse(self.path.exists())
        with self.assertRaises(RevisionFloorRefused):
            UnprotectedRevisionFloor(Path("relative.sqlite"))
        with self.assertRaises(RevisionFloorRefused):
            UnprotectedRevisionFloor(ROOT / "inside-source.sqlite")
        with self.assertRaises(RevisionFloorRefused):
            UnprotectedRevisionFloor(Path(self.dir.name) / "wrong.db")

    def test_database_corruption_and_wrong_schema_fail_closed(self):
        self.path.write_bytes(b"not a SQLite database!")
        with self.assertRaises(RevisionFloorRefused):
            UnprotectedRevisionFloor(self.path).advance(4)
        self.path.unlink()
        con = sqlite3.connect(self.path)
        try:
            con.execute("CREATE TABLE revision_floor (id TEXT, revision_hex TEXT)")
            con.commit()
        finally:
            con.close()
        with self.assertRaises(RevisionFloorRefused):
            UnprotectedRevisionFloor(self.path).advance(4)

    def test_reparse_or_symlink_ledger_refused(self):
        real = Path(self.dir.name) / "legitimate.sqlite"
        UnprotectedRevisionFloor(real).advance(4)
        try:
            self.path.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("this Windows account cannot create symlinks")
        with self.assertRaises(RevisionFloorRefused):
            UnprotectedRevisionFloor(self.path).advance(5)

    def test_distinct_python_processes_atomically_advance_one_file(self):
        python = sys.executable
        script = (
            "import sys;"
            "from pathlib import Path;"
            "from tools.mini_vera.unprotected_revision_floor import UnprotectedRevisionFloor as F;"
            "print(F(Path(sys.argv[1])).advance(int(sys.argv[2])))"
        )
        values = [20, 24, 21, 23, 22, 24]
        workers = [
            subprocess.Popen(
                [python, "-B", "-c", script, str(self.path), str(value)],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ) for value in values
        ]
        observed = []
        results = []
        try:
            for proc in workers:
                stdout, stderr = proc.communicate(timeout=20)
                results.append((proc.returncode, stdout, stderr))
        finally:
            # A failed first worker must not orphan the other test processes.
            for proc in workers:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate(timeout=10)
        for returncode, stdout, stderr in results:
            self.assertEqual(0, returncode, stderr.decode(errors="replace"))
            observed.append(int(stdout.decode().strip()))
        self.assertEqual(24, UnprotectedRevisionFloor(self.path).advance(0))
        self.assertTrue(all(20 <= n <= 24 for n in observed))

    def test_same_user_byte_rollback_remains_possible_unqualified(self):
        """Replays an old database to prove this is NOT a protected host floor."""
        floor = UnprotectedRevisionFloor(self.path)
        self.assertEqual(5, floor.advance(5))
        backup = Path(self.dir.name) / "rollback-copy"
        shutil.copyfile(self.path, backup)
        self.assertEqual(8, floor.advance(8))
        shutil.copyfile(backup, self.path)
        # No remote/privileged attestation: the replaced file's 5 is accepted.
        self.assertEqual(5, UnprotectedRevisionFloor(self.path).advance(5))


if __name__ == "__main__":
    unittest.main()
