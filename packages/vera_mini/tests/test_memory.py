"""Consent, persistence, and tamper tests for Mini-Vera's local memory journal.

These tests deliberately write only synthetic, non-personal fixture text.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from mini_vera.memory import MemoryJournal


class MemoryJournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "consent-governed.jsonl"

    @staticmethod
    def _visible(records):
        return json.dumps(records, default=str, ensure_ascii=False)

    def test_initialization_and_reads_do_not_persist_user_data(self):
        journal = MemoryJournal(self.path)
        self.assertEqual(journal.read(), [])
        self.assertFalse(self.path.exists())

    def test_append_requires_explicit_consent(self):
        journal = MemoryJournal(self.path)
        for kwargs in ({}, {"consent": False}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((PermissionError, ValueError)):
                    journal.append("synthetic secret fixture", **kwargs)
                self.assertFalse(self.path.exists())

    def test_explicit_consent_persists_and_reopens(self):
        journal = MemoryJournal(self.path)
        journal.append("synthetic memory alpha", consent=True)
        journal.append("synthetic memory beta", consent=True)
        self.assertTrue(self.path.exists())
        self.assertTrue(journal.verify())
        reopened = MemoryJournal(self.path)
        self.assertTrue(reopened.verify())
        visible = self._visible(reopened.read())
        self.assertIn("synthetic memory alpha", visible)
        self.assertIn("synthetic memory beta", visible)

    def test_tampering_fails_integrity_validation(self):
        journal = MemoryJournal(self.path)
        journal.append("integrity fixture value", consent=True)
        original = self.path.read_text(encoding="utf-8")
        self.assertIn("integrity fixture value", original)
        self.path.write_text(
            original.replace("integrity fixture value", "integrity fixture OTHER"),
            encoding="utf-8",
        )
        compromised = MemoryJournal(self.path)
        try:
            result = compromised.verify()
        except (ValueError, RuntimeError, OSError):
            pass  # Either an explicit integrity error or False is fail-closed.
        else:
            self.assertFalse(result, "Tampered memory was accepted as authentic")

    def test_explicit_forget_revokes_active_record_without_erasing_audit(self):
        journal = MemoryJournal(self.path)
        first = journal.append("revocable synthetic memory", consent=True)
        journal.append("still active synthetic memory", consent=True)
        with self.assertRaises((PermissionError, ValueError)):
            journal.forget(first["seq"])
        self.assertIn("revocable synthetic memory", self._visible(journal.read()))
        journal.forget(first["seq"], consent=True)
        self.assertTrue(journal.verify())
        active = self._visible(MemoryJournal(self.path).read())
        self.assertNotIn("revocable synthetic memory", active)
        self.assertIn("still active synthetic memory", active)
        self.assertIn("revocable synthetic memory", self.path.read_text(encoding="utf-8"))

    def test_broken_json_refuses_to_be_read_or_extended(self):
        journal = MemoryJournal(self.path)
        journal.append("valid initial fixture", consent=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write('{"seq": 2, invalid json\n')
        reopened = MemoryJournal(self.path)
        with self.assertRaises(ValueError):
            reopened.read()
        with self.assertRaises(ValueError):
            reopened.append("must not overwrite corrupt state", consent=True)

    def test_journal_path_must_not_be_a_symlink(self):
        real_path = Path(self._tmp.name) / "real.jsonl"
        real_path.write_text("", encoding="utf-8")
        alias = Path(self._tmp.name) / "alias.jsonl"
        alias.symlink_to(real_path)
        with self.assertRaises(ValueError):
            MemoryJournal(alias)


if __name__ == "__main__":
    unittest.main()
