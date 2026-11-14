"""Synthetic correction replay fence behavior tests, no live user state."""
from __future__ import annotations

from dataclasses import replace
import base64
import hashlib
import tempfile
from pathlib import Path
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vera_core.social_revision_ledger import (
    CorrectionEntry, CorrectionLedger, PropositionType, SourceKind, ROOT_HEAD
)
from vera_core.social_user_correction_witness import (
    SignedUserCorrectionV1, TrustedCorrectionVerifier
)
from vera_core.social_correction_replay_fence import (
    CorrectionReplayFence, FenceBlocked,
)


class TestCorrectionReplayFence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-social-replay-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "witness-fence.sqlite"
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.verifier = TrustedCorrectionVerifier(
            issuer_id="synthetic-issuer", key_id="ephemeral-key",
            public_key_bytes=public,
        )
        self.one = CorrectionEntry(
            event_id="event1", session_id="fictional-session", turn_id="turn1",
            subject_ref="fictional/life/nonbiological",
            proposition_type=PropositionType.DEFINITION,
            source_kind=SourceKind.CURRENT_USER,
            statement="Life need not be biological.", supersedes=None,
        )
        self.base = CorrectionLedger()
        self.fence = CorrectionReplayFence(
            self.path, installation_id="synthetic-install",
            verifier=self.verifier, synthetic_fixture_mode=True,
        )

    def witness(self, entry: CorrectionEntry, ledger: CorrectionLedger):
        preview = ledger.append(entry, expected_head=ledger.head)
        w = SignedUserCorrectionV1(
            issuer_id=self.verifier.issuer_id, key_id=self.verifier.key_id,
            actor_id="authenticated_user", session_id=entry.session_id,
            turn_id=entry.turn_id, subject_ref=entry.subject_ref,
            proposition_type=entry.proposition_type, source_kind=entry.source_kind,
            event_id=entry.event_id, supersedes=entry.supersedes,
            statement_sha256=hashlib.sha256(entry.statement.encode("utf8")).hexdigest(),
            expected_previous_head=ledger.head, resulting_head=preview.head,
            signature_b64="",
        )
        return replace(w, signature_b64=base64.b64encode(
            self.private.sign(w.signed_bytes())
        ).decode("ascii"))

    def claim(self, w, entry=None, ledger=None, expected_fence_head=None):
        entry = self.one if entry is None else entry
        ledger = self.base if ledger is None else ledger
        expected_fence_head = (
            self.fence.head if expected_fence_head is None else expected_fence_head
        )
        return self.fence.claim(
            w, entry=entry, ledger=ledger,
            expected_session_id=entry.session_id,
            expected_turn_id=entry.turn_id,
            expected_previous_head=ledger.head,
            expected_fence_head=expected_fence_head,
        )

    def test_signed_correction_claim_once_and_old_context_replay_denied(self):
        w = self.witness(self.one, self.base)
        pinned_before = self.fence.head
        first = self.claim(w, expected_fence_head=pinned_before)
        self.assertEqual(first.status, "LOCAL_CANDIDATE_UNCONFIRMED")
        self.assertNotEqual(first.fence_head, pinned_before)
        self.assertEqual(first.recorded_count, 1)
        self.assertFalse(first.external_effect_authorized)
        self.assertFalse(first.canonical_memory_admitted)
        with self.assertRaises(FenceBlocked):
            self.claim(w, expected_fence_head=first.fence_head)
        self.assertEqual(self.fence.head, first.fence_head)
        self.assertEqual(self.fence.recorded_count, 1)


    def test_successive_distinct_signed_corrections_follow_ledger_head(self):
        first = self.claim(self.witness(self.one, self.base))
        after_one = self.base.append(self.one, expected_head=ROOT_HEAD)
        correction = replace(
            self.one, event_id="event2", turn_id="turn2",
            statement="More precisely, I mean a nonbiological process.",
            supersedes=self.one.event_id,
        )
        signed_next = self.witness(correction, after_one)
        second = self.claim(
            signed_next, entry=correction, ledger=after_one,
            expected_fence_head=first.fence_head,
        )
        self.assertEqual(second.recorded_count, 2)
        self.assertNotEqual(first.fence_head, second.fence_head)
        with self.assertRaises(FenceBlocked):
            self.claim(signed_next, entry=correction, ledger=after_one,
                       expected_fence_head=first.fence_head)

    def test_reopen_requires_independent_checkpoint_and_matches_key(self):
        first = self.claim(self.witness(self.one, self.base))
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                self.path, installation_id="synthetic-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
            )
        reopened = CorrectionReplayFence(
            self.path, installation_id="synthetic-install",
            verifier=self.verifier, synthetic_fixture_mode=True,
            trusted_checkpoint_head=first.fence_head,
        )
        self.assertEqual(reopened.recorded_count, 1)
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                self.path, installation_id="synthetic-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
                trusted_checkpoint_head=ROOT_HEAD,
            )
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                self.path, installation_id="different-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
                trusted_checkpoint_head=first.fence_head,
            )
        other = Ed25519PrivateKey.generate()
        public = other.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                self.path, installation_id="synthetic-install",
                verifier=TrustedCorrectionVerifier(
                    issuer_id="synthetic-issuer", key_id="ephemeral-key",
                    public_key_bytes=public,
                ),
                synthetic_fixture_mode=True, trusted_checkpoint_head=first.fence_head,
            )

    def test_bad_signature_rejected_without_storage_or_private_content(self):
        w = self.witness(self.one, self.base)
        tampered = replace(
            w, signature_b64=base64.b64encode(b"0" * 64).decode("ascii")
        )
        original_head = self.fence.head
        with self.assertRaises(FenceBlocked):
            self.claim(tampered)
        self.assertEqual(self.fence.recorded_count, 0)
        self.assertEqual(self.fence.head, original_head)
        self.claim(w)
        raw_db = self.path.read_bytes()
        self.assertNotIn(self.one.statement.encode("utf8"), raw_db)
        self.assertNotIn(self.one.subject_ref.encode("utf8"), raw_db)

    def test_production_mode_disabled_and_missing_path_not_created(self):
        fresh = Path(self.temp.name) / "disabled.sqlite"
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                fresh, installation_id="synthetic-install", verifier=self.verifier
            )
        self.assertFalse(fresh.exists())
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                fresh, installation_id="synthetic-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
                trusted_checkpoint_head=self.fence.head,
            )
        self.assertFalse(fresh.exists())

    def test_tampered_database_refuses_even_matching_external_head(self):
        import sqlite3
        from contextlib import closing
        first = self.claim(self.witness(self.one, self.base))
        with closing(sqlite3.connect(str(self.path))) as db:
            db.execute("UPDATE fence_events SET witness_digest=? WHERE sequence=1",
                       ("0"*64,))
            db.commit()
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                self.path, installation_id="synthetic-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
                trusted_checkpoint_head=first.fence_head,
            )

    def test_rollback_database_refused_with_real_previous_checkpoint(self):
        import shutil
        backup = Path(self.temp.name) / "empty-before-claim.backup"
        shutil.copyfile(self.path, backup)
        first = self.claim(self.witness(self.one, self.base))
        shutil.copyfile(backup, self.path)
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                self.path, installation_id="synthetic-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
                trusted_checkpoint_head=first.fence_head,
            )

    def test_symlink_to_synthetic_database_rejected(self):
        import os
        link = Path(self.temp.name) / "alias.sqlite"
        try:
            os.symlink(self.path, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink privilege unavailable")
        with self.assertRaises(FenceBlocked):
            CorrectionReplayFence(
                link, installation_id="synthetic-install",
                verifier=self.verifier, synthetic_fixture_mode=True,
                trusted_checkpoint_head=self.fence.head,
            )

    def test_missing_existing_database_never_recreated(self):
        self.path.unlink()
        with self.assertRaises(FenceBlocked):
            self.fence.head
        self.assertFalse(self.path.exists())

    def test_post_initialization_hardlink_path_swap_is_rejected(self):
        import os
        target = Path(self.temp.name) / "trusted-original.sqlite"
        self.path.rename(target)
        try:
            os.link(target, self.path)
        except (OSError, NotImplementedError):
            target.rename(self.path)
            self.skipTest("hard links unavailable")
        with self.assertRaises(FenceBlocked):
            self.fence.head
        with self.assertRaises(FenceBlocked):
            self.claim(self.witness(self.one, self.base))

    def test_actual_concurrent_fresh_processes_only_one_local_claim(self):
        from dataclasses import asdict
        import json
        import subprocess
        import sys
        w = self.witness(self.one, self.base)
        original = self.fence.head
        fixture = Path(self.temp.name) / "synthetic-claim-fixture.json"
        fixture.write_text(json.dumps({
            "entry": asdict(self.one), "witness": asdict(w),
            "key": base64.b64encode(self.verifier.public_key_bytes).decode("ascii"),
            "initial_head": original,
        }, sort_keys=True), encoding="utf8")
        child = """
import base64,json,sys
from pathlib import Path
from vera_core.social_revision_ledger import CorrectionEntry,CorrectionLedger,PropositionType,SourceKind,ROOT_HEAD
from vera_core.social_user_correction_witness import SignedUserCorrectionV1,TrustedCorrectionVerifier
from vera_core.social_correction_replay_fence import CorrectionReplayFence,FenceBlocked
f=json.loads(Path(sys.argv[2]).read_text(encoding='utf8'))
def decode(klass,record):
 return klass(**{**record,'proposition_type':PropositionType(record['proposition_type']),'source_kind':SourceKind(record['source_kind'])})
entry=decode(CorrectionEntry,f['entry'])
witness=decode(SignedUserCorrectionV1,f['witness'])
verifier=TrustedCorrectionVerifier(issuer_id='synthetic-issuer',key_id='ephemeral-key',public_key_bytes=base64.b64decode(f['key']))
try:
 fence=CorrectionReplayFence(Path(sys.argv[1]),installation_id='synthetic-install',verifier=verifier,synthetic_fixture_mode=True,trusted_checkpoint_head=f['initial_head'])
 receipt=fence.claim(witness,entry=entry,ledger=CorrectionLedger(),expected_session_id=entry.session_id,expected_turn_id=entry.turn_id,expected_previous_head=ROOT_HEAD,expected_fence_head=f['initial_head'])
 print('ACCEPT',receipt.recorded_count)
except FenceBlocked as exc:
 print('BLOCK',str(exc))
"""
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", child, str(self.path), str(fixture)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ) for _ in range(4)
        ]
        results = []
        try:
            for proc in processes:
                output, errors = proc.communicate(timeout=25)
                self.assertEqual(proc.returncode, 0, errors)
                results.append(output.strip().split(" ")[0])
        finally:
            for proc in processes:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
        self.assertEqual(results.count("ACCEPT"), 1, results)
        self.assertEqual(results.count("BLOCK"), 3, results)
        self.assertEqual(self.fence.recorded_count, 1)

if __name__ == "__main__":
    unittest.main()
