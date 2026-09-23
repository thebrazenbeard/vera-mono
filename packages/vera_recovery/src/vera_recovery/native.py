from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from r8a0.canonical import canonical_dumps, canonical_sha256, strict_loads


class NativeCheckpointError(ValueError):
    pass


class StaleCheckpointHead(NativeCheckpointError):
    pass


@dataclass(frozen=True, slots=True)
class NativeRecoveryCheckpoint:
    checkpoint_id: str
    generation: int
    predecessor_head: str
    checkpoint_digest: str
    project_id: str
    identity_id: str
    runtime_id: str
    memory_head_digest: str
    control_source_digest: str
    created_at: str
    commitments: tuple[str, ...]
    unfinished_work: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "generation": self.generation,
            "predecessor_head": self.predecessor_head,
            "project_id": self.project_id,
            "identity_id": self.identity_id,
            "runtime_id": self.runtime_id,
            "memory_head_digest": self.memory_head_digest,
            "control_source_digest": self.control_source_digest,
            "created_at": self.created_at,
            "commitments": list(self.commitments),
            "unfinished_work": list(self.unfinished_work),
        }


class NativeRecoveryCheckpointStore:
    """Portable SQLite checkpoint ledger with compare-and-swap heads."""

    _GENESIS_PAYLOAD = {
        "schema": "VERA_MONO_RECOVERY_CHECKPOINT_HEAD_V1",
        "generation": 0,
        "predecessor_head": "0" * 64,
    }

    def __init__(self, path: str | Path, *, project_id: str, identity_id: str):
        self.path = Path(path)
        if type(project_id) is not str or not project_id:
            raise NativeCheckpointError("project_id must be a non-empty exact string")
        if type(identity_id) is not str or not identity_id:
            raise NativeCheckpointError("identity_id must be a non-empty exact string")
        self.project_id = project_id
        self.identity_id = identity_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        if type(value) is not str or not value:
            raise NativeCheckpointError(f"{label} must be a non-empty exact string")
        return value

    @staticmethod
    def _require_digest(value: str, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise NativeCheckpointError(f"{label} must be an exact SHA-256 digest")
        try:
            int(value, 16)
        except ValueError as exc:
            raise NativeCheckpointError(f"{label} must be hexadecimal") from exc
        return value.lower()

    @staticmethod
    def _require_string_tuple(value: tuple[str, ...], label: str) -> tuple[str, ...]:
        if type(value) is not tuple or any(type(item) is not str or not item for item in value):
            raise NativeCheckpointError(f"{label} must be a tuple of non-empty exact strings")
        return value

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @classmethod
    def genesis_head(cls) -> str:
        return canonical_sha256(cls._GENESIS_PAYLOAD)

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL UNIQUE,
                    predecessor_head TEXT NOT NULL,
                    checkpoint_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                """
            )
            if db.execute("SELECT 1 FROM meta WHERE key='generation'").fetchone() is None:
                db.execute("INSERT INTO meta(key,value) VALUES('generation','0')")
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('head',?)",
                    (self.genesis_head(),),
                )

    def _meta(self, db: sqlite3.Connection) -> tuple[int, str]:
        generation = int(
            db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0]
        )
        head = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
        return generation, head

    @property
    def current_head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    @property
    def current_generation(self) -> int:
        with self._connect() as db:
            return self._meta(db)[0]

    def append(
        self,
        *,
        checkpoint_id: str,
        runtime_id: str,
        memory_head_digest: str,
        control_source_digest: str,
        expected_head: str,
        commitments: tuple[str, ...] = (),
        unfinished_work: tuple[str, ...] = (),
        created_at: str | None = None,
    ) -> NativeRecoveryCheckpoint:
        checkpoint_id = self._require_text(checkpoint_id, "checkpoint_id")
        runtime_id = self._require_text(runtime_id, "runtime_id")
        memory_head_digest = self._require_digest(
            memory_head_digest, "memory_head_digest"
        )
        control_source_digest = self._require_digest(
            control_source_digest, "control_source_digest"
        )
        expected_head = self._require_digest(expected_head, "expected_head")
        commitments = self._require_string_tuple(commitments, "commitments")
        unfinished_work = self._require_string_tuple(
            unfinished_work, "unfinished_work"
        )
        timestamp = (
            datetime.now(timezone.utc).isoformat()
            if created_at is None
            else self._require_text(created_at, "created_at")
        )

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload_json,checkpoint_digest FROM checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            if existing is not None:
                payload = strict_loads(existing["payload_json"])
                if (
                    payload["runtime_id"] != runtime_id
                    or payload["memory_head_digest"] != memory_head_digest
                    or payload["control_source_digest"] != control_source_digest
                    or tuple(payload["commitments"]) != commitments
                    or tuple(payload["unfinished_work"]) != unfinished_work
                ):
                    raise NativeCheckpointError(
                        "checkpoint_id replay carries different checkpoint content"
                    )
                return self._from_row(existing["checkpoint_digest"], payload)

            generation, current_head = self._meta(db)
            if current_head != expected_head:
                raise StaleCheckpointHead("stale expected recovery checkpoint head")

            next_generation = generation + 1
            payload = {
                "schema": "VERA_MONO_RECOVERY_CHECKPOINT_V1",
                "checkpoint_id": checkpoint_id,
                "generation": next_generation,
                "predecessor_head": current_head,
                "project_id": self.project_id,
                "identity_id": self.identity_id,
                "runtime_id": runtime_id,
                "memory_head_digest": memory_head_digest,
                "control_source_digest": control_source_digest,
                "created_at": timestamp,
                "commitments": list(commitments),
                "unfinished_work": list(unfinished_work),
            }
            checkpoint_digest = canonical_sha256(payload)
            db.execute(
                """
                INSERT INTO checkpoints(
                    checkpoint_id,generation,predecessor_head,checkpoint_digest,payload_json
                ) VALUES(?,?,?,?,?)
                """,
                (
                    checkpoint_id,
                    next_generation,
                    current_head,
                    checkpoint_digest,
                    canonical_dumps(payload),
                ),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='generation'",
                (str(next_generation),),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='head'",
                (checkpoint_digest,),
            )
            db.commit()
            return self._from_row(checkpoint_digest, payload)

    def read(self, checkpoint_id: str) -> NativeRecoveryCheckpoint:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json,checkpoint_digest FROM checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            raise KeyError(checkpoint_id)
        return self._from_row(
            row["checkpoint_digest"],
            strict_loads(row["payload_json"]),
        )

    def read_digest(self, checkpoint_digest: str) -> NativeRecoveryCheckpoint:
        checkpoint_digest = self._require_digest(
            checkpoint_digest,
            "checkpoint_digest",
        )
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json,checkpoint_digest
                FROM checkpoints
                WHERE checkpoint_digest=?
                """,
                (checkpoint_digest,),
            ).fetchone()
        if row is None:
            raise KeyError(checkpoint_digest)
        return self._from_row(
            row["checkpoint_digest"],
            strict_loads(row["payload_json"]),
        )

    def latest(self) -> NativeRecoveryCheckpoint | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json,checkpoint_digest
                FROM checkpoints
                ORDER BY generation DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._from_row(
            row["checkpoint_digest"],
            strict_loads(row["payload_json"]),
        )

    @staticmethod
    def _from_row(
        checkpoint_digest: str,
        payload: Mapping[str, Any],
    ) -> NativeRecoveryCheckpoint:
        if payload.get("schema") != "VERA_MONO_RECOVERY_CHECKPOINT_V1":
            raise NativeCheckpointError("unsupported recovery checkpoint schema")
        if canonical_sha256(dict(payload)) != checkpoint_digest:
            raise NativeCheckpointError("recovery checkpoint digest mismatch")
        return NativeRecoveryCheckpoint(
            checkpoint_id=str(payload["checkpoint_id"]),
            generation=int(payload["generation"]),
            predecessor_head=str(payload["predecessor_head"]),
            checkpoint_digest=str(checkpoint_digest),
            project_id=str(payload["project_id"]),
            identity_id=str(payload["identity_id"]),
            runtime_id=str(payload["runtime_id"]),
            memory_head_digest=str(payload["memory_head_digest"]),
            control_source_digest=str(payload["control_source_digest"]),
            created_at=str(payload["created_at"]),
            commitments=tuple(payload["commitments"]),
            unfinished_work=tuple(payload["unfinished_work"]),
        )
