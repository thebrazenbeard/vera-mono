"""Source-level claim-ledger tests; test witnesses are NOT trusted host custody."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import shutil
import sqlite3
import threading

import pytest

from vera_core.host_authz.ledger import (
    ClaimDenied,
    ClaimLedger,
    ClaimLedgerError,
)


NOW = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


class SyntheticWitness:
    """Testing only; a dict and lock do not establish host-owned authority."""

    def __init__(self):
        self.last: dict[tuple[str, int], int] = {}
        self.spent: set[str] = set()
        self.revoked: set[str] = set()
        self.lock = threading.Lock()
        self.enabled = True

    def attest_claim(self, *, authority_id, epoch, sequence, grant_id, claim_digest):
        with self.lock:
            if (not self.enabled or len(claim_digest) != 64
                    or grant_id in self.revoked or grant_id in self.spent):
                return False
            key = authority_id, epoch
            if sequence != self.last.get(key, 0) + 1:
                return False
            self.last[key] = sequence
            self.spent.add(grant_id)
            return True

    def attest_revocation(self, *, authority_id, epoch, sequence, grant_id):
        with self.lock:
            if not self.enabled or not grant_id:
                return False
            key = authority_id, epoch
            if sequence != self.last.get(key, 0) + 1:
                return False
            self.last[key] = sequence
            self.revoked.add(grant_id)
            return True


def ledger(tmp_path: Path, witness=None):
    return ClaimLedger(tmp_path / "claims.sqlite", "synthetic-host-a", 1, witness)


class SeparateSqliteTestWitness:
    """Only a multiprocessing test oracle; DB cloning with this DB is unsafe."""

    def __init__(self, path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS highwater (id TEXT PRIMARY KEY, seq INTEGER)")

    def attest_claim(self, *, authority_id, epoch, sequence, grant_id, claim_digest):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            key = f"{authority_id}:{epoch}"
            row = db.execute("SELECT seq FROM highwater WHERE id=?", (key,)).fetchone()
            if sequence != (row[0] if row else 0) + 1:
                return False
            db.execute(
                """INSERT INTO highwater(id,seq) VALUES(?,?)
                ON CONFLICT(id) DO UPDATE SET seq=excluded.seq""",
                (key, sequence),
            )
            db.commit()
            return True

    def attest_revocation(self, *, authority_id, epoch, sequence, grant_id):
        return self.attest_claim(
            authority_id=authority_id,
            epoch=epoch,
            sequence=sequence,
            grant_id=grant_id,
            claim_digest=DIGEST,
        )


def _crossprocess_claim(paths):
    claim_path, witness_path, grant_id = paths
    store = ClaimLedger(claim_path, "synthetic-host-a", 1, SeparateSqliteTestWitness(witness_path))
    try:
        return store.claim(grant_id, DIGEST, NOW).sequence
    except ClaimDenied:
        return None


def test_absent_witness_denies_claim_without_consuming_id(tmp_path):
    store = ledger(tmp_path)
    with pytest.raises(ClaimDenied, match="witness"):
        store.claim("g1", DIGEST, NOW)
    assert store.read("g1") is None


def test_one_use_persists_across_process_like_reopen(tmp_path):
    witness = SyntheticWitness()
    first = ledger(tmp_path, witness)
    record = first.claim("g1", DIGEST, NOW)
    assert record.sequence == 1
    assert record.state == "RESERVED"
    reopened = ledger(tmp_path, witness)
    with pytest.raises(ClaimDenied, match="already"):
        reopened.claim("g1", DIGEST, NOW)
    ambiguous = reopened.mark_ambiguous("g1")
    assert ambiguous.state == "AMBIGUOUS"
    with pytest.raises(ClaimDenied):
        reopened.claim("g1", DIGEST, NOW)
    complete = reopened.complete("g1", "b" * 64)
    assert complete.state == "COMPLETED"
    assert complete.provider_receipt_digest == "b" * 64
    assert ledger(tmp_path, witness).read("g1") == complete


def test_same_claim_race_has_one_winner(tmp_path):
    store = ledger(tmp_path, SyntheticWitness())

    def attempt(_):
        try:
            return store.claim("same", DIGEST, NOW)
        except ClaimDenied:
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        claims = list(pool.map(attempt, range(64)))
    assert sum(claim is not None for claim in claims) == 1
    assert store.read("same").sequence == 1


def test_unique_claims_are_strictly_monotonic(tmp_path):
    store = ledger(tmp_path, SyntheticWitness())
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda i: store.claim(f"g{i}", DIGEST, NOW), range(20)))
    assert sorted(r.sequence for r in receipts) == list(range(1, 21))


def test_cross_process_atomic_same_grant(tmp_path):
    claim_path = str(tmp_path / "claims.sqlite")
    witness_path = str(tmp_path / "test_witness.sqlite")
    ClaimLedger(claim_path, "synthetic-host-a", 1, SeparateSqliteTestWitness(witness_path))
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=6, mp_context=context) as pool:
        results = list(pool.map(_crossprocess_claim, [(claim_path, witness_path, "g1")] * 12))
    assert sum(value is not None for value in results) == 1
    assert ClaimLedger(claim_path, "synthetic-host-a", 1, SeparateSqliteTestWitness(witness_path)).read("g1").sequence == 1


def test_revocation_before_claim_denies_then_persists(tmp_path):
    witness = SyntheticWitness()
    store = ledger(tmp_path, witness)
    store.revoke("g1")
    with pytest.raises(ClaimDenied, match="revoked"):
        store.claim("g1", DIGEST, NOW)
    assert ledger(tmp_path, witness).read("g1").revoked
    assert ledger(tmp_path, witness).read("g1").state == "REVOKED"


def test_revocation_after_reservation_never_releases_grant(tmp_path):
    store = ledger(tmp_path, SyntheticWitness())
    store.claim("g1", DIGEST, NOW)
    store.revoke("g1")
    assert store.read("g1").revoked
    assert store.read("g1").state == "RESERVED"
    with pytest.raises(ClaimDenied):
        store.claim("g1", DIGEST, NOW)
    with pytest.raises(ClaimDenied, match="revoked"):
        store.complete("g1", "b" * 64)
    assert store.read("g1").state == "RESERVED"


def test_revocation_after_ambiguous_claim_denies_completion(tmp_path):
    store = ledger(tmp_path, SyntheticWitness())
    store.claim("g1", DIGEST, NOW)
    store.mark_ambiguous("g1")
    store.revoke("g1")
    with pytest.raises(ClaimDenied, match="revoked"):
        store.complete("g1", "b" * 64)
    assert store.read("g1").state == "AMBIGUOUS"


def test_revocation_requires_trusted_witness_and_is_not_rollback_local_only(tmp_path):
    store = ledger(tmp_path)
    with pytest.raises(ClaimDenied, match="revocation witness"):
        store.revoke("g1")
    assert store.read("g1") is None


def test_claim_and_revocation_share_one_monotonic_external_event_stream(tmp_path):
    witness = SyntheticWitness()
    store = ledger(tmp_path, witness)
    assert store.claim("g1", DIGEST, NOW).sequence == 1
    assert store.revoke("g2").revoked
    assert store.claim("g3", DIGEST, NOW).sequence == 3
    assert witness.last[("synthetic-host-a", 1)] == 3


def test_external_witness_denies_local_revocation_row_tamper(tmp_path):
    witness = SyntheticWitness()
    store = ledger(tmp_path, witness)
    store.revoke("g1")
    # An attacker with DB-file write access cannot silently erase a revocation
    # if the external witness separately retains grant identity. Test-only.
    with sqlite3.connect(tmp_path / "claims.sqlite") as db:
        db.execute("DELETE FROM claims WHERE grant_id='g1'")
        db.execute("DELETE FROM revocation_events WHERE grant_id='g1'")
    with pytest.raises(ClaimDenied, match="witness"):
        store.claim("g1", DIGEST, NOW)
    assert store.read("g1") is None


def test_ambiguous_is_not_retryable_and_conflicting_receipt_rejected(tmp_path):
    store = ledger(tmp_path, SyntheticWitness())
    store.claim("g1", DIGEST, NOW)
    assert store.mark_ambiguous("g1").state == "AMBIGUOUS"
    assert store.mark_ambiguous("g1").state == "AMBIGUOUS"
    assert store.complete("g1", "b" * 64) == store.complete("g1", "b" * 64)
    with pytest.raises(ClaimLedgerError):
        store.complete("g1", "c" * 64)
    with pytest.raises(ClaimLedgerError):
        store.mark_ambiguous("g1")


def test_witness_failure_rolls_back_and_denies(tmp_path):
    witness = SyntheticWitness()
    witness.enabled = False
    store = ledger(tmp_path, witness)
    with pytest.raises(ClaimDenied, match="witness"):
        store.claim("g1", DIGEST, NOW)
    assert store.read("g1") is None
    witness.enabled = True
    assert store.claim("g1", DIGEST, NOW).sequence == 1


def test_witness_side_effect_then_exception_fails_closed(tmp_path):
    witness = SyntheticWitness()

    class BrokenWitness:
        def attest_claim(self, **kwargs):
            witness.attest_claim(**kwargs)
            raise RuntimeError("witness response interrupted after durable attestation")

    store = ledger(tmp_path, BrokenWitness())
    with pytest.raises(ClaimDenied, match="witness"):
        store.claim("g1", DIGEST, NOW)
    assert store.read("g1") is None
    # Same external witness refuses recycling the consumed sequence: safe HOLD.
    store = ledger(tmp_path, witness)
    with pytest.raises(ClaimDenied, match="witness"):
        store.claim("g1", DIGEST, NOW)


def test_keyboard_interrupt_during_witness_does_not_leave_sqlite_lock(tmp_path):
    class InterruptedWitness:
        def attest_claim(self, **kwargs):
            raise KeyboardInterrupt

    store = ledger(tmp_path, InterruptedWitness())
    with pytest.raises(KeyboardInterrupt):
        store.claim("g1", DIGEST, NOW)
    assert store.read("g1") is None
    assert ledger(tmp_path, SyntheticWitness()).claim("g1", DIGEST, NOW).sequence == 1


def test_cloned_db_cannot_replay_same_sequence_with_external_witness(tmp_path):
    witness = SyntheticWitness()
    origin = ledger(tmp_path, witness)
    clone_path = tmp_path / "clone.sqlite"
    shutil.copyfile(tmp_path / "claims.sqlite", clone_path)
    origin.claim("origin", DIGEST, NOW)
    clone = ClaimLedger(clone_path, "synthetic-host-a", 1, witness)
    with pytest.raises(ClaimDenied, match="witness"):
        clone.claim("clone", DIGEST, NOW)
    assert clone.read("clone") is None


def test_wrong_authority_and_epoch_cannot_rebind_same_db(tmp_path):
    ledger(tmp_path, SyntheticWitness())
    with pytest.raises(ClaimLedgerError, match="authority"):
        ClaimLedger(tmp_path / "claims.sqlite", "other-host", 1, SyntheticWitness())
    with pytest.raises(ClaimLedgerError, match="epoch"):
        ClaimLedger(tmp_path / "claims.sqlite", "synthetic-host-a", 2, SyntheticWitness())


@pytest.mark.parametrize("bad", ["", "A" * 64, "f" * 63, 123, None])
def test_invalid_claim_digest_denied(tmp_path, bad):
    with pytest.raises(ClaimLedgerError):
        ledger(tmp_path, SyntheticWitness()).claim("g1", bad, NOW)


def test_naive_or_caller_invalid_time_denied(tmp_path):
    with pytest.raises(ClaimLedgerError):
        ledger(tmp_path, SyntheticWitness()).claim("g1", DIGEST, datetime.now())
