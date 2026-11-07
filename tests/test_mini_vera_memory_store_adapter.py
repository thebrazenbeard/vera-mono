"""MemoryStore structural adapter tests; synthetic DB, no Lappy memory reads."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for package in ("vera_memory", "portfolio_runtime"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from tests.test_mini_vera_loopback import FakeLocal, response  # noqa: E402
from tools.mini_vera import compose, local_session  # noqa: E402
from tools.mini_vera.host_memory_broker import (  # noqa: E402
    PublicMemoryGrant, bind_host_public_memory,
)
from tools.mini_vera.memory_store_adapter import ReadOnlyMemoryStoreAsLedger  # noqa: E402


KEY = b"synthetic-memory-store-integrity-key"[:32]
HEAD = "a" * 64
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def public_row(record_id: str = "mem-public-1") -> dict:
    statement = "Synthetic public project status, not verified current truth."
    return {
        "memory_id": record_id, "source_id": "src-public-1",
        "source_locator": "synthetic:test-memory-store:source-1",
        "content_hash": hashlib.sha256(statement.encode()).hexdigest(),
        "statement": statement, "author": "fixture", "memory_class": "current_state",
        "scope": "project", "branch_id": "chatgpt-project-current",
        "subject_id": "vera-chatgpt-current",
        "privacy_scope": "PUBLIC", "consent": "granted",
        "endorsement": "endorsed_current", "lifecycle": "active",
        "instruction_status": "data_only", "risk_flags": [], "revision": 1,
        "valid_from": None, "valid_until": None,
    }


class FakeReadOnlyMemoryStore:
    """Replicates only the real MemoryStore read_only/conn/get_memory API."""

    def __init__(self, conn: sqlite3.Connection, records: dict[str, dict]):
        self.conn = conn
        self.records = records
        self.read_only = True
        self.get_calls: list[str] = []

    def get_memory(self, record_id: str) -> dict:
        self.get_calls.append(record_id)
        return deepcopy(self.records[record_id])


class MemoryStoreAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic-memory.sqlite"
        writer = sqlite3.connect(self.path)
        writer.execute("CREATE TABLE events(event_seq INTEGER PRIMARY KEY, event_hash TEXT NOT NULL)")
        writer.execute("INSERT INTO events VALUES(1,?)", (HEAD,))
        writer.commit()
        writer.close()
        self.rows = {"mem-public-1": public_row()}
        self.preapproved = True
        self.approved_records = True
        self.authority_revision = 25
        self.current_grant = PublicMemoryGrant(
            project_id="vera-mono", identity_id="vera", ledger_head=HEAD,
            revision=7, record_ids=("mem-public-1",), approval_epoch=3,
            expires_at_unix=2_000_000_000)
        self.id_approval_calls = []
        self.record_approval_calls = []
        self.open_store()

    def open_store(self):
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        store = FakeReadOnlyMemoryStore(conn, self.rows)
        self.addCleanup(conn.close)
        self.store = store

    def adapter(self):
        def id_approval(record_id, head):
            self.id_approval_calls.append((record_id, head))
            return self.preapproved is True

        return ReadOnlyMemoryStoreAsLedger(
            self.store, project_id="vera-mono", identity_id="vera",
            branch_id="chatgpt-project-current", subject_id="vera-chatgpt-current",
            allow_public_id=id_approval,
            now_utc=lambda: NOW)

    def provider(self):
        def record_approval(record, grant):
            self.record_approval_calls.append((record.record_id, grant.approval_epoch))
            return self.approved_records is True

        return bind_host_public_memory(
            self.adapter(), integrity_key=KEY,
            current_grant=lambda: self.current_grant,
            current_authority_revision=lambda: self.authority_revision,
            approve_record=record_approval,
            now_seconds=lambda: 1_999_999_700)

    def test_public_explicit_selected_memory_passes_existing_composer_state(self):
        provider = self.provider()
        state, key, revision = provider()
        self.assertEqual(7, revision)
        self.assertNotEqual(KEY, key)  # grant-scoped HMAC
        self.assertEqual("ledger:" + HEAD, state["source_id"])
        self.assertEqual(["mem-public-1"], [x["record_id"] for x in state["records"]])
        self.assertEqual("DATA_NOT_INSTRUCTION", state["records"][0]["instruction_trust"])
        self.assertEqual(1, len(compose.verify_state(state, key=key, expected_revision=revision)[0]))
        self.assertEqual(["mem-public-1"], self.store.get_calls)
        self.assertEqual([("mem-public-1", 3)], self.record_approval_calls)

    def test_unapproved_id_refused_before_any_memory_content_read(self):
        self.preapproved = False
        with self.assertRaisesRegex(compose.CompositionRejected, "not preapproved"):
            self.provider()()
        self.assertEqual([], self.store.get_calls)
        self.assertEqual([], self.record_approval_calls)

    def test_collaborator_shared_is_not_auto_promoted_to_public(self):
        self.rows["mem-public-1"]["privacy_scope"] = "collaborator_shared"
        with self.assertRaisesRegex(compose.CompositionRejected, "not qualified"):
            self.provider()()
        self.assertEqual([], self.record_approval_calls)

    def test_consent_privacy_risks_and_source_digest_guard_projection(self):
        for field, value, message in (
            ("consent", "refused", "not qualified"),
            ("endorsement", "candidate", "not qualified"),
            ("lifecycle", "tombstoned", "not qualified"),
            ("risk_flags", ["instruction_override"], "not qualified"),
            ("scope", "global", "not qualified"),
            ("subject_id", "other-subject", "not qualified"),
            ("content_hash", "0" * 64, "hash mismatch"),
            ("valid_until", "2026-10-01T00:00:00+00:00", "validity window"),
        ):
            with self.subTest(field=field):
                source = self.rows["mem-public-1"]
                original = source.get(field)
                source[field] = value
                try:
                    with self.assertRaisesRegex(compose.CompositionRejected, message):
                        self.provider()()
                finally:
                    source[field] = original

    def test_foreign_or_empty_project_id_if_exported_never_gets_relabelled(self):
        # MemoryStore 0.4.0 has no project_id column; a later host/schema
        # extension can supply one, but its contradictory value must not be
        # silently discarded while the adapter stamps configured project_id.
        source = self.rows["mem-public-1"]
        for foreign in ("definitely-another-project", "", None):
            with self.subTest(foreign=foreign):
                source["project_id"] = foreign
                with self.assertRaisesRegex(compose.CompositionRejected, "project scope mismatch"):
                    self.provider()()
        del source["project_id"]
        state, _key, _revision = self.provider()()
        self.assertEqual(1, len(state["records"]))

    def test_missing_source_subject_id_is_rejected(self):
        source = self.rows["mem-public-1"]
        del source["subject_id"]
        with self.assertRaisesRegex(compose.CompositionRejected, "lacks provenance fields"):
            self.provider()()

    def test_read_only_property_and_sqlite_query_only_mandatory(self):
        self.store.read_only = False
        with self.assertRaisesRegex(compose.CompositionRejected, "opened read-only"):
            self.adapter()
        self.store.read_only = True
        self.store.conn.execute("PRAGMA query_only=OFF")
        with self.assertRaisesRegex(compose.CompositionRejected, "query_only is not active"):
            self.adapter()

    def test_current_host_grant_must_match_independent_event_head(self):
        self.current_grant = PublicMemoryGrant(
            project_id="vera-mono", identity_id="vera", ledger_head="b" * 64,
            revision=7, record_ids=("mem-public-1",), approval_epoch=3,
            expires_at_unix=2_000_000_000)
        with self.assertRaisesRegex(compose.CompositionRejected, "head drift"):
            self.provider()()
        self.assertEqual([], self.store.get_calls)

    def test_cold_sqlite_reopen_and_epoch_revocation(self):
        first = self.provider()()[0]
        self.store.conn.close()
        self.open_store()
        second = self.provider()()[0]
        self.assertEqual(first, second)
        self.current_grant = None
        with self.assertRaisesRegex(compose.CompositionRejected, "revoked"):
            self.provider()()

    def test_postread_host_content_policy_denial(self):
        self.approved_records = False
        with self.assertRaisesRegex(compose.CompositionRejected, "host rejected"):
            self.provider()()
        self.assertEqual(["mem-public-1"], self.store.get_calls)

    def test_local_inference_withholds_output_when_host_epoch_advances(self):
        provider = self.provider()
        with FakeLocal(answer=response(model="vera:local", text="Synthetic reply to withhold.")) as server:
            original_execute = local_session.loopback.execute

            def change_epoch_after_local_reply(request, **kwargs):
                result = original_execute(request, **kwargs)
                self.current_grant = replace(self.current_grant, approval_epoch=4)
                return result

            output, errors = io.StringIO(), io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--prompt", "Synthetic project question",
                    "--execute", "--host-idle-confirmed"]
            with patch.object(local_session.loopback, "execute", side_effect=change_epoch_after_local_reply), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(2, local_session.main(args, live_public_provider=provider))
            self.assertEqual(1, len(server.requests))
            self.assertNotIn("Synthetic reply", output.getvalue())
            self.assertIn("post-inference", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
