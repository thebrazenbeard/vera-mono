"""Host-local pre-dispatch attempt fence for isolated Goal 1 research.

A disposable transport adapter, NOT installed QVR or an independent witness.
Only hashes and conservative outcome statuses survive. Never sign a receipt,
assert loaded weight bytes, or declare a model execution independently attested.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import time

_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_ARMS = frozenset(("FROZEN", "LEARNED", "PLACEBO", "SHUFFLED"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _id(value: object, field: str) -> str:
    if type(value) is not str or _IDENT.fullmatch(value) is None:
        raise ValueError("invalid " + field)
    return value


def _sha(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError("invalid " + field)
    return value


class LocalAttemptStore:
    """SQLite CAS fence. Lock/uniqueness survives concurrent OS processes.

    RESERVED surviving a process crash remains unresolved and undispatchable.
    It is intentionally not auto-removed or converted on open: another process
    could still be legitimately dispatching. No retry of that identity.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._db()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS attempts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    invocation_id TEXT NOT NULL UNIQUE,
                    reservation_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL, arm TEXT NOT NULL,
                    challenge_id TEXT NOT NULL,
                    challenge_view_digest TEXT NOT NULL,
                    route_ref TEXT NOT NULL, model TEXT NOT NULL,
                    reported_model_digest TEXT NOT NULL,
                    prompt_sha256 TEXT NOT NULL, max_tokens INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                       ('RESERVED', 'COMPLETED', 'OUTCOME_UNKNOWN')),
                    reserved_utc TEXT NOT NULL, finished_utc TEXT,
                    response_sha256 TEXT, elapsed_ms INTEGER,
                    model_identity_level TEXT NOT NULL,
                    independent_attestation INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(run_id, arm, challenge_id)
                )
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level="DEFERRED")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def reserve(self, *, invocation_id: str, reservation_id: str, run_id: str, arm: str,
                challenge_id: str, challenge_view_digest: str, route_ref: str,
                model: str, reported_model_digest: str,
                prompt_sha256: str, max_tokens: int) -> dict:
        for name, value in (
            ("invocation_id", invocation_id), ("reservation_id", reservation_id), ("run_id", run_id),
            ("challenge_id", challenge_id), ("route_ref", route_ref),
            ("model", model),
        ):
            _id(value, name)
        if arm not in _ALLOWED_ARMS or type(arm) is not str:
            raise ValueError("invalid arm")
        _sha(challenge_view_digest, "challenge_view_digest")
        _sha(reported_model_digest, "reported_model_digest")
        _sha(prompt_sha256, "prompt_sha256")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 128:
            raise ValueError("invalid bounded max_tokens")
        try:
            with closing(self._db()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""
                    INSERT INTO attempts
                    (invocation_id,reservation_id,run_id,arm,challenge_id,challenge_view_digest,
                     route_ref,model,reported_model_digest,prompt_sha256,
                     max_tokens,status,reserved_utc,model_identity_level)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'RESERVED',?,
                            'REGISTRY_SELF_REPORTED')
                """, (invocation_id,reservation_id,run_id,arm,challenge_id,challenge_view_digest,
                      route_ref,model,reported_model_digest,prompt_sha256,
                      max_tokens,_now()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("invocation or arm/case already reserved; retry forbidden") from exc
        return self._one(invocation_id)

    def _one(self, invocation_id: str) -> dict:
        _id(invocation_id, "invocation_id")
        with closing(self._db()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM attempts WHERE invocation_id=?",
                             (invocation_id,)).fetchone()
        if row is None:
            raise KeyError(invocation_id)
        record = dict(row)
        record["independent_attestation"] = bool(record["independent_attestation"])
        return record

    def history(self) -> list[dict]:
        with closing(self._db()) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM attempts ORDER BY sequence").fetchall()
        result = []
        for row in rows:
            record = dict(row)
            record["independent_attestation"] = bool(record["independent_attestation"])
            result.append(record)
        return result

    def _finish(self, invocation_id: str, *, status: str,
                response_sha256: str | None = None, elapsed_ms: int | None = None):
        if status not in ("COMPLETED", "OUTCOME_UNKNOWN"):
            raise ValueError("invalid terminal status")
        if status == "COMPLETED":
            _sha(response_sha256, "response_sha256")
            if type(elapsed_ms) is not int or elapsed_ms < 0:
                raise ValueError("invalid elapsed_ms")
        else:
            response_sha256 = None
            elapsed_ms = None
        with closing(self._db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("""
                UPDATE attempts SET status=?, finished_utc=?,
                    response_sha256=?, elapsed_ms=?
                WHERE invocation_id=? AND status='RESERVED'
            """, (status, _now(), response_sha256, elapsed_ms, invocation_id))
            if result.rowcount != 1:
                raise ValueError("attempt not in RESERVED; terminal replay denied")
        return self._one(invocation_id)

    def execute(self, *, invocation_id: str, reservation_id: str, run_id: str, arm: str,
                challenge_id: str, challenge_view_digest: str,
                route_ref: str, model: str, reported_model_digest: str,
                prompt_sha256: str, max_tokens: int, prompt: str,
                transport: object, permit: object):
        """Reserve before ANY transport call; return (durable_record, volatile_text).

        Returns no independent dispatch evidence. Caught transport failures
        are marked UNKNOWN even when dispatch might not have occurred.
        """
        if (type(prompt) is not str or not prompt
                or len(prompt.encode("utf-8")) > 4096
                or _digest(prompt) != prompt_sha256):
            raise ValueError("prompt digest mismatch before reservation")
        if not callable(getattr(transport, "generate", None)):
            raise ValueError("invalid transport")
        self.reserve(
            invocation_id=invocation_id, reservation_id=reservation_id, run_id=run_id, arm=arm,
            challenge_id=challenge_id, challenge_view_digest=challenge_view_digest,
            route_ref=route_ref, model=model,
            reported_model_digest=reported_model_digest,
            prompt_sha256=prompt_sha256, max_tokens=max_tokens,
        )
        start = time.monotonic_ns()
        try:
            reply = transport.generate(prompt, permit=permit, max_tokens=max_tokens)
            text = reply.text
            if (type(text) is not str or not text
                    or len(text.encode("utf-8")) > 4096
                    or reply.model != model
                    or reply.reported_model_digest != reported_model_digest
                    or reply.prompt_sha256 != prompt_sha256
                    or reply.response_sha256 != _digest(text)):
                raise ValueError("untrusted model reply does not match reserved identity")
            elapsed_ms = max(0, (time.monotonic_ns() - start) // 1_000_000)
            record = self._finish(
                invocation_id, status="COMPLETED",
                response_sha256=_digest(text), elapsed_ms=elapsed_ms,
            )
            return record, text
        except Exception:
            # A terminal write failure leaves RESERVED in the DB, which also
            # blocks automatic replay. Never re-dispatch on error.
            try:
                self._finish(invocation_id, status="OUTCOME_UNKNOWN")
            except Exception:
                pass
            raise
