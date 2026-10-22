"""Durable, metadata-only record of *observed* local model invocations.

No prompt or model output is persisted. Hash chain detects accidental/tampered
database changes but is NOT an external witness or tamper-proof ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ZERO = "0" * 64
FIELDS = (
    "invocation_id", "route_ref", "runtime_pid", "model", "reported_model_digest",
    "prompt_sha256", "response_sha256", "observed_utc",
    "model_byte_identity_verified", "independent_attestation",
)


class LocalCognitionJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS invocations (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                invocation_id TEXT NOT NULL UNIQUE,
                route_ref TEXT NOT NULL,
                runtime_pid INTEGER NOT NULL,
                model TEXT NOT NULL,
                reported_model_digest TEXT NOT NULL,
                prompt_sha256 TEXT NOT NULL,
                response_sha256 TEXT NOT NULL,
                observed_utc TEXT NOT NULL,
                model_byte_identity_verified INTEGER NOT NULL DEFAULT 0,
                independent_attestation INTEGER NOT NULL DEFAULT 0,
                previous_digest TEXT NOT NULL,
                entry_digest TEXT NOT NULL
            )""")
        self.history()  # Reject corrupt history before any new evidence is accepted.

    def _connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _digest(entry: dict, previous: str) -> str:
        data = json.dumps(
            {"previous_digest": previous, "record": entry},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def history(self) -> list[dict]:
        with self._lock, self._connection() as db:
            rows = db.execute("SELECT * FROM invocations ORDER BY sequence").fetchall()
            prior = ZERO
            output = []
            for expected_sequence, row in enumerate(rows, start=1):
                if row["sequence"] != expected_sequence:
                    raise ValueError("local cognition invocation sequence broken")
                entry = {key: row[key] for key in FIELDS}
                entry["model_byte_identity_verified"] = bool(
                    entry["model_byte_identity_verified"]
                )
                entry["independent_attestation"] = bool(
                    entry["independent_attestation"]
                )
                if (row["previous_digest"] != prior or
                    row["entry_digest"] != self._digest(entry, prior)):
                    raise ValueError("local cognition invocation chain corrupted")
                entry["sequence"] = expected_sequence
                entry["entry_digest"] = row["entry_digest"]
                output.append(entry)
                prior = row["entry_digest"]
            return output

    def require_unused(self, invocation_id: str) -> None:
        if type(invocation_id) is not str or not ID.fullmatch(invocation_id):
            raise ValueError("invalid invocation id")
        with self._lock, self._connection() as db:
            if db.execute(
                "SELECT 1 FROM invocations WHERE invocation_id=?", (invocation_id,)
            ).fetchone() is not None:
                raise ValueError("invocation id already recorded")

    def append(self, *, invocation_id: str, route_ref: str, model: str,
               reported_model_digest: str, prompt_sha256: str,
               response_sha256: str) -> dict:
        self.require_unused(invocation_id)
        if type(route_ref) is not str or not ID.fullmatch(route_ref):
            raise ValueError("invalid cognition route identifier")
        if not all(
            type(value) is str and DIGEST.fullmatch(value)
            for value in (reported_model_digest, prompt_sha256, response_sha256)
        ):
            raise ValueError("invalid observed digest")
        if type(model) is not str or not model or len(model) > 128:
            raise ValueError("invalid observed model")
        entry = {
            "invocation_id": invocation_id,
            "route_ref": route_ref,
            "runtime_pid": os.getpid(),
            "model": model,
            "reported_model_digest": reported_model_digest,
            "prompt_sha256": prompt_sha256,
            "response_sha256": response_sha256,
            "observed_utc": datetime.now(timezone.utc).isoformat(),
            "model_byte_identity_verified": False,
            "independent_attestation": False,
        }
        with self._lock, self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute(
                "SELECT entry_digest FROM invocations ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            prior = ZERO if last is None else last["entry_digest"]
            stamp = self._digest(entry, prior)
            db.execute(
                """INSERT INTO invocations (
                    invocation_id, route_ref, runtime_pid, model,
                    reported_model_digest, prompt_sha256, response_sha256,
                    observed_utc, model_byte_identity_verified,
                    independent_attestation, previous_digest, entry_digest)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(int(entry[k]) if k in (
                    "model_byte_identity_verified", "independent_attestation"
                ) else entry[k] for k in FIELDS) + (prior, stamp),
            )
        final = self.history()
        return final[-1]
