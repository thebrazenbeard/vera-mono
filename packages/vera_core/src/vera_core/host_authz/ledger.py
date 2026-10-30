"""Durable, fail-closed one-use claim ledger for the dedicated host authority.

The ledger is deliberately *not* its own authority. The trusted host must
inject an external, independently persistent witness which verifies exclusive
authority and monotonically fences each claim. A synthetic witness or SQLite
database restored alongside its witness cannot establish antirollback safety.

Model/adapters must never be given the ClaimLedger object, database file,
filesystem permissions to mutate it, or the witness. Only a dedicated host
authorization-service process may call this module.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Iterator, Protocol


class ClaimLedgerError(ValueError):
    """Invalid metadata, impossible transition, or local ledger corruption."""


class ClaimDenied(ClaimLedgerError):
    """No authority to make the claim; grant must not be dispatched."""


class ClaimWitness(Protocol):
    def attest_claim(
        self, *, authority_id: str, epoch: int, sequence: int,
        grant_id: str, claim_digest: str
    ) -> bool:
        """Host-controlled exclusive authority/monotonic claim attestation.

        Requires a deployment-qualified external trust domain, not an object
        or local DB merely implementing this protocol.
        """

    def attest_revocation(
        self, *, authority_id: str, epoch: int, sequence: int, grant_id: str
    ) -> bool:
        """Persist a revocation in the same exclusive monotonic event stream."""


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    grant_id: str
    claim_digest: str | None
    sequence: int | None
    claimed_at_us: int | None
    state: str
    provider_receipt_digest: str | None
    revoked: bool


_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


def _id(value: str, name: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise ClaimLedgerError(f"{name} must be an exact nonempty bounded string")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ClaimLedgerError(f"{name} must not contain control characters")
    return value


def _digest(value: str, name: str) -> str:
    if type(value) is not str or _HEX_SHA256.fullmatch(value) is None:
        raise ClaimLedgerError(f"{name} must be a lowercase sha256 hex digest")
    return value


def _time(value: datetime) -> int:
    if type(value) is not datetime or value.tzinfo is None:
        raise ClaimLedgerError("now must be a trusted aware datetime")
    offset = value.utcoffset()
    if offset is None:
        raise ClaimLedgerError("now must have an unambiguous UTC offset")
    # Store microseconds, not provider-controlled free text.
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)


class ClaimLedger:
    """SQLite claim state plus mandatory out-of-band antirollback witness.

    `attest_claim` is called under BEGIN IMMEDIATE. If it attests and the DB
    subsequently fails, safe recovery may require an external operator/witness
    reconciliation. This is intentional fail-closed behavior, not a claim of
    cross-resource atomic commit.
    """

    def __init__(
        self,
        path: str | Path,
        authority_id: str,
        epoch: int,
        witness: ClaimWitness | None,
    ) -> None:
        self.path = Path(path)
        self.authority_id = _id(authority_id, "authority_id")
        if type(epoch) is not int or epoch <= 0:
            raise ClaimLedgerError("epoch must be a positive exact integer")
        self.epoch = epoch
        self._witness = witness
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """CREATE TABLE IF NOT EXISTS claim_authority (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    authority_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL,
                    last_sequence INTEGER NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS claims (
                    grant_id TEXT PRIMARY KEY,
                    claim_digest TEXT,
                    sequence INTEGER UNIQUE,
                    claimed_at_us INTEGER,
                    state TEXT NOT NULL CHECK (
                        state IN ('RESERVED', 'AMBIGUOUS', 'COMPLETED', 'REVOKED')
                    ),
                    provider_receipt_digest TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS revocation_events (
                    sequence INTEGER PRIMARY KEY,
                    grant_id TEXT NOT NULL UNIQUE
                )"""
            )
            existing = db.execute(
                "SELECT authority_id, epoch, last_sequence FROM claim_authority WHERE singleton=1"
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO claim_authority VALUES(1,?,?,0)",
                    (self.authority_id, self.epoch),
                )
            elif existing["authority_id"] != self.authority_id:
                raise ClaimLedgerError("authority binding mismatch on existing ledger")
            elif existing["epoch"] != self.epoch:
                raise ClaimLedgerError("epoch binding mismatch on existing ledger")
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """Close every connection, including BaseException or witness faults."""
        db = self._connect()
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> ClaimRecord:
        return ClaimRecord(
            grant_id=str(row["grant_id"]),
            claim_digest=row["claim_digest"],
            sequence=row["sequence"],
            claimed_at_us=row["claimed_at_us"],
            state=str(row["state"]),
            provider_receipt_digest=row["provider_receipt_digest"],
            revoked=bool(row["revoked"]),
        )

    def claim(self, grant_id: str, claim_digest: str, now: datetime) -> ClaimRecord:
        grant_id = _id(grant_id, "grant_id")
        claim_digest = _digest(claim_digest, "claim_digest")
        now_us = _time(now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM claims WHERE grant_id=?", (grant_id,)
            ).fetchone()
            if row is not None:
                if row["revoked"]:
                    raise ClaimDenied("grant revoked")
                raise ClaimDenied("grant already claimed; no automatic retry")
            state = db.execute(
                "SELECT last_sequence FROM claim_authority WHERE singleton=1"
            ).fetchone()
            if state is None:
                raise ClaimDenied("authority metadata absent")
            sequence = int(state["last_sequence"]) + 1
            attestor = getattr(self._witness, "attest_claim", None)
            if not callable(attestor):
                raise ClaimDenied("trusted external witness unavailable")
            try:
                attested = attestor(
                    authority_id=self.authority_id,
                    epoch=self.epoch,
                    sequence=sequence,
                    grant_id=grant_id,
                    claim_digest=claim_digest,
                )
            except Exception as exc:
                raise ClaimDenied("trusted external witness failed") from exc
            if attested is not True:
                raise ClaimDenied("trusted external witness denied claim")
            db.execute(
                """INSERT INTO claims (
                    grant_id, claim_digest, sequence, claimed_at_us, state, revoked
                ) VALUES(?,?,?,?,'RESERVED',0)""",
                (grant_id, claim_digest, sequence, now_us),
            )
            db.execute(
                "UPDATE claim_authority SET last_sequence=? WHERE singleton=1",
                (sequence,),
            )
            db.commit()
        return ClaimRecord(grant_id, claim_digest, sequence, now_us, "RESERVED", None, False)

    def read(self, grant_id: str) -> ClaimRecord | None:
        grant_id = _id(grant_id, "grant_id")
        with self._db() as db:
            row = db.execute("SELECT * FROM claims WHERE grant_id=?", (grant_id,)).fetchone()
        return self._record(row) if row is not None else None

    def revoke(self, grant_id: str) -> ClaimRecord:
        grant_id = _id(grant_id, "grant_id")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM claims WHERE grant_id=?", (grant_id,)
            ).fetchone()
            if existing is not None and bool(existing["revoked"]):
                db.commit()
                return self._record(existing)
            meta = db.execute(
                "SELECT last_sequence FROM claim_authority WHERE singleton=1"
            ).fetchone()
            if meta is None:
                raise ClaimDenied("authority metadata absent")
            sequence = int(meta["last_sequence"]) + 1
            attestor = getattr(self._witness, "attest_revocation", None)
            if not callable(attestor):
                raise ClaimDenied("trusted external revocation witness unavailable")
            try:
                attested = attestor(
                    authority_id=self.authority_id,
                    epoch=self.epoch,
                    sequence=sequence,
                    grant_id=grant_id,
                )
            except Exception as exc:
                raise ClaimDenied("trusted external revocation witness failed") from exc
            if attested is not True:
                raise ClaimDenied("trusted external revocation witness denied revocation")
            db.execute(
                """INSERT INTO claims(grant_id, state, revoked)
                VALUES(?,'REVOKED',1)
                ON CONFLICT(grant_id) DO UPDATE SET revoked=1""",
                (grant_id,),
            )
            db.execute(
                "INSERT INTO revocation_events(sequence, grant_id) VALUES(?,?)",
                (sequence, grant_id),
            )
            db.execute(
                "UPDATE claim_authority SET last_sequence=? WHERE singleton=1",
                (sequence,),
            )
            row = db.execute("SELECT * FROM claims WHERE grant_id=?", (grant_id,)).fetchone()
            db.commit()
        return self._record(row)

    def mark_ambiguous(self, grant_id: str) -> ClaimRecord:
        grant_id = _id(grant_id, "grant_id")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM claims WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None or row["state"] not in {"RESERVED", "AMBIGUOUS"}:
                raise ClaimLedgerError("only reserved/ambiguous claims can be marked ambiguous")
            db.execute(
                "UPDATE claims SET state='AMBIGUOUS' WHERE grant_id=?",
                (grant_id,),
            )
            updated = db.execute("SELECT * FROM claims WHERE grant_id=?", (grant_id,)).fetchone()
            db.commit()
        return self._record(updated)

    def complete(self, grant_id: str, provider_receipt_digest: str) -> ClaimRecord:
        grant_id = _id(grant_id, "grant_id")
        provider_receipt_digest = _digest(provider_receipt_digest, "provider_receipt_digest")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM claims WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None or row["state"] == "REVOKED":
                raise ClaimLedgerError("cannot complete an unclaimed grant")
            if bool(row["revoked"]):
                raise ClaimDenied("revoked grant cannot complete")
            if row["state"] == "COMPLETED":
                if row["provider_receipt_digest"] != provider_receipt_digest:
                    raise ClaimLedgerError("conflicting provider receipt for completed grant")
                db.commit()
                return self._record(row)
            if row["state"] not in {"RESERVED", "AMBIGUOUS"}:
                raise ClaimLedgerError("invalid completion transition")
            db.execute(
                """UPDATE claims SET state='COMPLETED', provider_receipt_digest=?
                WHERE grant_id=?""",
                (provider_receipt_digest, grant_id),
            )
            updated = db.execute("SELECT * FROM claims WHERE grant_id=?", (grant_id,)).fetchone()
            db.commit()
        return self._record(updated)
