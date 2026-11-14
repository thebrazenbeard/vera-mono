"""Synthetic-only SQLite fence for signed correction *candidate* replay.

A local database is not an authority source. The caller must provide an
independently retained head on every reopen. This cannot prove who owns the
signer or supply an independent host checkpoint or durable consumed effect.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3

from .social_revision_ledger import CorrectionEntry, CorrectionLedger
from .social_user_correction_witness import (
    SignedUserCorrectionV1,
    TrustedCorrectionVerifier,
)

SCHEMA = "VERA_SYNTHETIC_SOCIAL_REPLAY_FENCE_V1"
MAX_CANDIDATES = 256


class FenceBlocked(ValueError):
    """Rejected synthetic candidate; never implies protected effect status."""


@dataclass(frozen=True, slots=True)
class LocalCandidateReceipt:
    status: str
    fence_head: str
    recorded_count: int
    external_effect_authorized: bool = False
    canonical_memory_admitted: bool = False


def _digest(previous: str, sequence: int, witness_digest: str,
            previous_ledger_head: str, resulting_ledger_head: str) -> str:
    payload = json.dumps({
        "schema": SCHEMA,
        "sequence": sequence,
        "witness_digest": witness_digest,
        "previous_ledger_head": previous_ledger_head,
        "resulting_ledger_head": resulting_ledger_head,
    }, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(
        b"VERA_SYNTHETIC_CORRECTION_FENCE_EVENT_V1\0"
        + previous.encode("ascii") + b"\0" + payload
    ).hexdigest()


def _sha(value: str, field: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise FenceBlocked(f"invalid {field}")


class CorrectionReplayFence:
    """Synthetic SQLite CAS, not production host or privacy authorization."""

    def __init__(
        self,
        path: str | Path,
        *,
        installation_id: str,
        verifier: TrustedCorrectionVerifier,
        trusted_checkpoint_head: str | None = None,
        synthetic_fixture_mode: bool = False,
    ) -> None:
        if synthetic_fixture_mode is not True:
            raise FenceBlocked("live correction consumption disabled")
        if type(verifier) is not TrustedCorrectionVerifier:
            raise FenceBlocked("typed external verifier required")
        if (type(installation_id) is not str or not installation_id.strip()
                or len(installation_id) > 128):
            raise FenceBlocked("bounded installation ID required")
        if not isinstance(path, (str, Path)):
            raise FenceBlocked("path must be literal string or Path")
        self.path = Path(path).absolute()
        self.installation_id = installation_id
        self.verifier = verifier
        self._key_digest = hashlib.sha256(verifier.public_key_bytes).hexdigest()
        self._check_path()
        existed = self.path.exists()
        if existed and trusted_checkpoint_head is None:
            raise FenceBlocked("existing database requires external checkpoint")
        if not existed and trusted_checkpoint_head is not None:
            raise FenceBlocked("missing database cannot match external checkpoint")
        if trusted_checkpoint_head is not None:
            _sha(trusted_checkpoint_head, "external checkpoint")
        if existed and self.path.stat().st_size == 0:
            raise FenceBlocked("preexisting empty database refused")
        try:
            if not existed:
                with closing(self._connect(create_new=True)) as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("""
                        CREATE TABLE fence_meta (
                            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                            schema TEXT NOT NULL,
                            installation_id TEXT NOT NULL,
                            issuer_id TEXT NOT NULL,
                            key_id TEXT NOT NULL,
                            signer_key_sha256 TEXT NOT NULL,
                            random_journal_id TEXT NOT NULL,
                            fence_head TEXT NOT NULL,
                            event_count INTEGER NOT NULL
                        )
                    """)
                    db.execute("""
                        CREATE TABLE fence_events (
                            sequence INTEGER PRIMARY KEY,
                            witness_digest TEXT NOT NULL UNIQUE,
                            previous_ledger_head TEXT NOT NULL UNIQUE,
                            resulting_ledger_head TEXT NOT NULL,
                            prior_fence_head TEXT NOT NULL,
                            event_head TEXT NOT NULL UNIQUE
                        )
                    """)
                    nonce = secrets.token_hex(16)
                    genesis = hashlib.sha256(
                        b"VERA_SYNTHETIC_CORRECTION_FENCE_ROOT_V1\0"
                        + json.dumps({
                            "installation_id": installation_id,
                            "issuer_id": verifier.issuer_id,
                            "key_id": verifier.key_id,
                            "public_key_sha256": self._key_digest,
                            "random_journal_id": nonce,
                        }, sort_keys=True, separators=(",", ":")).encode("ascii")
                    ).hexdigest()
                    db.execute(
                        "INSERT INTO fence_meta VALUES (1,?,?,?,?,?,?,?,0)",
                        (SCHEMA, installation_id, verifier.issuer_id,
                         verifier.key_id, self._key_digest, nonce, genesis),
                    )
                    db.commit()
            with closing(self._connect()) as db:
                head, _ = self._scan(db)
                if trusted_checkpoint_head is not None and head != trusted_checkpoint_head:
                    raise FenceBlocked("external checkpoint mismatch")
        except sqlite3.DatabaseError as exc:
            raise FenceBlocked("synthetic journal database invalid") from exc

    def _check_path(self) -> None:
        if not self.path.parent.is_dir():
            raise FenceBlocked("parent directory must exist")
        for component in (self.path, *self.path.parents):
            if component.is_symlink() or (
                hasattr(os.path, "isjunction") and os.path.isjunction(component)
            ):
                raise FenceBlocked("symlink/junction path forbidden")
        if self.path.exists() and (
            not self.path.is_file() or self.path.stat().st_nlink > 1
        ):
            raise FenceBlocked("non-file or hardlink path forbidden")

    def _connect(self, *, create_new: bool = False) -> sqlite3.Connection:
        # Recheck on every access; mode=rw prevents SQLite from silently
        # creating a replacement database after path deletion.
        # Still not a protected-handle/ACL guarantee.
        self._check_path()
        if create_new:
            db = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        else:
            if not self.path.is_file():
                raise FenceBlocked("existing fence database disappeared")
            db = sqlite3.connect(
                self.path.as_uri() + "?mode=rw",
                uri=True, timeout=10.0, isolation_level=None,
            )
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _scan(self, db: sqlite3.Connection) -> tuple[str, int]:
        try:
            meta = db.execute("SELECT * FROM fence_meta").fetchall()
            if len(meta) != 1:
                raise FenceBlocked("missing or ambiguous fence metadata")
            (_, schema, installation, issuer, key_id, key_hash,
             nonce, stored_head, stored_count) = meta[0]
            if (
                schema != SCHEMA or installation != self.installation_id
                or issuer != self.verifier.issuer_id
                or key_id != self.verifier.key_id
                or key_hash != self._key_digest
                or type(nonce) is not str
                or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
            ):
                raise FenceBlocked("fence owner/schema/key mismatch")
            head = hashlib.sha256(
                b"VERA_SYNTHETIC_CORRECTION_FENCE_ROOT_V1\0"
                + json.dumps({
                    "installation_id": installation,
                    "issuer_id": issuer,
                    "key_id": key_id,
                    "public_key_sha256": key_hash,
                    "random_journal_id": nonce,
                }, sort_keys=True, separators=(",", ":")).encode("ascii")
            ).hexdigest()
            rows = db.execute(
                "SELECT sequence,witness_digest,previous_ledger_head,"
                "resulting_ledger_head,prior_fence_head,event_head "
                "FROM fence_events ORDER BY sequence"
            ).fetchall()
            if len(rows) > MAX_CANDIDATES or type(stored_count) is not int:
                raise FenceBlocked("invalid candidate count")
            ledger_last: str | None = None
            for count, row in enumerate(rows, start=1):
                seq, digest, previous, resulting, prior_head, event_head = row
                for field, value in (
                    ("witness digest", digest), ("previous ledger", previous),
                    ("resulting ledger", resulting), ("prior fence", prior_head),
                    ("event head", event_head),
                ):
                    _sha(value, field)
                if (
                    seq != count or prior_head != head
                    or (ledger_last is not None and previous != ledger_last)
                ):
                    raise FenceBlocked("broken candidate sequence or lineage")
                head = _digest(head, count, digest, previous, resulting)
                if head != event_head:
                    raise FenceBlocked("candidate content tampered")
                ledger_last = resulting
            if stored_count != len(rows) or stored_head != head:
                raise FenceBlocked("stored candidate head/count inconsistent")
            return head, len(rows)
        except sqlite3.DatabaseError as exc:
            raise FenceBlocked("journal read/integrity failure") from exc

    @property
    def head(self) -> str:
        with closing(self._connect()) as db:
            return self._scan(db)[0]

    @property
    def recorded_count(self) -> int:
        with closing(self._connect()) as db:
            return self._scan(db)[1]

    def claim(
        self,
        witness: SignedUserCorrectionV1,
        *,
        entry: CorrectionEntry,
        ledger: CorrectionLedger,
        expected_session_id: str,
        expected_turn_id: str,
        expected_previous_head: str,
        expected_fence_head: str,
    ) -> LocalCandidateReceipt:
        """Atomic local candidate insertion; never grants a runtime action."""
        _sha(expected_fence_head, "expected fence head")
        if not self.verifier.verify(
            witness, entry=entry, ledger=ledger,
            expected_session_id=expected_session_id,
            expected_turn_id=expected_turn_id,
            expected_previous_head=expected_previous_head,
        ):
            raise FenceBlocked("signed correction source unverified")
        # Signed witness fingerprint (not source text) is never emitted publicly.
        signature = witness.signature_b64.encode("ascii")
        digest = hashlib.sha256(
            b"VERA_SYNTHETIC_CORRECTION_WITNESS_ID_V1\0"
            + witness.signed_bytes() + b"\0" + signature
        ).hexdigest()
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                head, count = self._scan(db)
                if head != expected_fence_head:
                    raise FenceBlocked("stale external expected fence head")
                if count >= MAX_CANDIDATES:
                    raise FenceBlocked("bounded synthetic replay fence full")
                if count:
                    last = db.execute(
                        "SELECT resulting_ledger_head FROM fence_events "
                        "ORDER BY sequence DESC LIMIT 1"
                    ).fetchone()[0]
                    if last != witness.expected_previous_head:
                        raise FenceBlocked("previous accepted correction not current")
                new_head = _digest(
                    head, count + 1, digest,
                    witness.expected_previous_head, witness.resulting_head,
                )
                db.execute(
                    "INSERT INTO fence_events VALUES (?,?,?,?,?,?)",
                    (count + 1, digest, witness.expected_previous_head,
                     witness.resulting_head, head, new_head),
                )
                changed = db.execute(
                    "UPDATE fence_meta SET fence_head=?, event_count=? "
                    "WHERE singleton=1 AND fence_head=? AND event_count=?",
                    (new_head, count + 1, head, count),
                ).rowcount
                if changed != 1:
                    raise FenceBlocked("concurrent candidate head drift")
                db.commit()
            # Read-back detects local persistence, NOT out-of-band pinning.
            with closing(self._connect()) as verify_db:
                after_head, after_count = self._scan(verify_db)
            if after_head != new_head or after_count != count + 1:
                raise FenceBlocked("local write unconfirmed; do not retry blindly")
            return LocalCandidateReceipt(
                status="LOCAL_CANDIDATE_UNCONFIRMED",
                fence_head=new_head, recorded_count=count + 1,
            )
        except sqlite3.IntegrityError as exc:
            raise FenceBlocked("duplicate correction or replay") from exc
        except sqlite3.DatabaseError as exc:
            raise FenceBlocked("journal write outcome uncertain; no blind retry") from exc
