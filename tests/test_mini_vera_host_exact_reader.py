"""Source-only public record lookup against a real synthetic SQLite ledger."""

from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for package in ("vera_memory", "portfolio_runtime"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from tests.test_mini_vera_source_bindings import KEY, ledger_fixture
from tools.mini_vera import compose
from tools.mini_vera.host_memory_broker import PublicMemoryGrant, bind_host_public_memory
from tools.mini_vera.host_exact_reader import read_public_record, HostSourceRefused


class HostExactReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger, head = ledger_fixture(Path(self.temp.name))
        self.grant = PublicMemoryGrant(
            project_id="vera-mono", identity_id="vera", ledger_head=head,
            revision=13, record_ids=("work-1",),
            record_digests=(("work-1", self.ledger.read("work-1").record_digest),),
            approval_epoch=1, authority_revision=10, expires_at_unix=1_000_600)
        self.authority_revision = 10
        self.floor = -1

    def provider(self):
        def advance_floor(value):
            self.floor = max(self.floor, value)
            return self.floor
        return bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.grant,
            current_authority_revision=lambda: self.authority_revision,
            atomic_host_revision_floor=advance_floor,
            approve_record=lambda record, grant: (
                record.record_id in grant.record_ids
                and record.authority_ref == "synthetic-approved"
                and record.privacy_ref == "PUBLIC"),
            now_seconds=lambda: 1_000_000)

    def test_exact_id_returns_source_text_and_explicit_not_neural_provenance(self):
        answer = read_public_record(self.provider(), record_id="work-1")
        self.assertEqual("MINI_VERA_HOST_PUBLIC_EXACT_READ_V1", answer["schema"])
        self.assertEqual("SOURCE_READ", answer["status"])
        self.assertEqual("Synthetic public project milestone; not present-day truth.",
                         answer["answer"])
        self.assertEqual("work-1", answer["source"]["record_id"])
        self.assertEqual(
            compose.sha256(answer["answer"].encode("utf-8")),
            answer["source"]["text_sha256"])
        self.assertEqual(13, answer["source"]["revision"])
        self.assertEqual("HOST_SUPPLIED_APPROVED_PUBLIC_SOURCE_NOT_NEURAL",
                         answer["origin"])
        self.assertEqual("HOST_CALLBACK_TRUST_NOT_INDEPENDENTLY_ATTESTED",
                         answer["authority"])
        self.assertFalse(answer["host_issuer_qualified"])
        self.assertEqual(0, answer["model_http_calls"])
        self.assertEqual(0, answer["writes"])

    def test_source_identifier_cannot_change_after_verified_snapshot(self):
        """A host-owned mutable state may change during final equality checks."""
        import hmac
        from unittest import mock
        from tools.mini_vera import host_exact_reader

        state, key, revision = self.provider()()
        validated_source_id = state["source_id"]
        forged_id = "forged-public-source-attribution"
        untouched_compare = hmac.compare_digest
        changed = [False]

        def change_during_final_compare(left, right):
            if (not changed[0] and type(left) is bytes and type(right) is bytes
                    and len(left) == len(right) == 32):
                changed[0] = True
                state["source_id"] = forged_id
            return untouched_compare(left, right)

        with mock.patch.object(
                host_exact_reader.hmac, "compare_digest",
                side_effect=change_during_final_compare):
            result = read_public_record(
                lambda: (state, key, revision), record_id="work-1")

        self.assertTrue(changed[0], "the mutation must occur in the final check")
        self.assertEqual("SOURCE_READ", result["status"])
        self.assertEqual(validated_source_id, result["source"]["source_id"])
        self.assertNotEqual(forged_id, result["source"]["source_id"])
    def test_refuses_state_mutation_between_verification_and_snapshot_copy(self):
        """Both reads can share a forged snapshot while their verified SHA is old."""
        from unittest import mock
        state, key, revision = self.provider()()
        original_source_id = state["source_id"]
        canonical_original = compose.canonical
        calls = {"source": 0, "provider": 0}

        def reset_before_verification():
            calls["provider"] += 1
            calls["source"] = 0
            state["source_id"] = original_source_id
            return state, key, revision

        def mutate_during_freeze(value):
            if value is state:
                calls["source"] += 1
                if calls["source"] == 2:
                    state["source_id"] = "forged-source-at-freeze"
            return canonical_original(value)

        with mock.patch.object(compose, "canonical",
                               side_effect=mutate_during_freeze):
            with self.assertRaises(HostSourceRefused):
                read_public_record(
                    reset_before_verification, record_id="work-1")
        self.assertEqual(1, calls["provider"])

    def test_unknown_id_returns_unknown_without_enumerating_approved_sources(self):
        answer = read_public_record(self.provider(), record_id="not-approved")
        self.assertEqual("UNKNOWN", answer["answer"])
        self.assertEqual("UNKNOWN", answer["status"])
        self.assertIsNone(answer["source"])
        self.assertNotIn("work-1", str(answer))
        self.assertNotIn("Synthetic public", str(answer))

    def test_revoked_grant_refuses_without_source_or_private_host_error(self):
        self.grant = None
        with self.assertRaises(HostSourceRefused) as err:
            read_public_record(self.provider(), record_id="work-1")
        self.assertNotIn("Synthetic public", str(err.exception))

    def test_approval_revoked_between_reads_prevents_text_release(self):
        provider = self.provider()
        calls = [0]
        def change_between_reads():
            result = provider()
            calls[0] += 1
            if calls[0] == 1:
                self.authority_revision += 1
                self.grant = None
            return result
        with self.assertRaises(HostSourceRefused):
            read_public_record(change_between_reads, record_id="work-1")
        self.assertEqual(1, calls[0])

    def test_changed_approval_epoch_refuses_even_when_record_text_is_same(self):
        provider = self.provider()
        calls = [0]
        def rotate_epoch():
            result = provider()
            calls[0] += 1
            if calls[0] == 1:
                self.grant = replace(self.grant, approval_epoch=2)
            return result
        with self.assertRaises(HostSourceRefused):
            read_public_record(rotate_epoch, record_id="work-1")
        self.assertEqual(2, calls[0])

    def test_host_callback_private_exception_does_not_reach_reader_message(self):
        def leaked():
            raise RuntimeError("SECRET HOST POLICY MESSAGE: never echo me")
        with self.assertRaises(HostSourceRefused) as err:
            read_public_record(leaked, record_id="work-1")
        self.assertNotIn("SECRET HOST POLICY", str(err.exception))
        self.assertIsNone(err.exception.__cause__)

    def test_in_place_state_rewrite_between_reads_is_withheld(self):
        import hmac
        state, key, revision = self.provider()()
        calls = [0]

        def mutable_shared_state():
            calls[0] += 1
            if calls[0] == 2:
                state["records"][0]["text"] = "Rewritten public statement"
                state["records"][0]["source_sha256"] = compose.sha256(
                    state["records"][0]["text"].encode())
                unsigned = {name: value for name, value in state.items()
                            if name != "hmac_sha256"}
                state["hmac_sha256"] = hmac.new(
                    key, compose.canonical(unsigned), "sha256").hexdigest()
            return state, key, revision

        with self.assertRaises(HostSourceRefused):
            read_public_record(mutable_shared_state, record_id="work-1")
        self.assertEqual(2, calls[0])

    def test_tampered_record_or_invalid_id_refused_before_release(self):
        provider = self.provider()
        def corrupted():
            state, key, revision = provider()
            state["records"][0]["text"] = "UNAPPROVED SOURCE"
            return state, key, revision
        with self.assertRaises(HostSourceRefused):
            read_public_record(corrupted, record_id="work-1")
        for invalid in ("", "work/1", None, True, "a" * 81):
            with self.subTest(invalid=invalid):
                with self.assertRaises(HostSourceRefused):
                    read_public_record(provider, record_id=invalid)