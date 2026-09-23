from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex


class LifecycleJournalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    sequence: int
    transition_id: str
    event_type: str
    predecessor_event_digest: str
    event_digest: str
    payload: Mapping[str, Any]


class LifecycleJournal:
    """Append-only, digest-chained lifecycle event journal."""

    GENESIS_HEAD = sha256_hex(b"vera-mono-lifecycle-journal-genesis-v1")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY,
                    transition_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    predecessor_event_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    UNIQUE(transition_id,event_type)
                );
                """
            )
            if db.execute("SELECT 1 FROM meta WHERE key='sequence'").fetchone() is None:
                db.execute("INSERT INTO meta(key,value) VALUES('sequence','0')")
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('head',?)",
                    (self.GENESIS_HEAD,),
                )

    def _meta(self, db: sqlite3.Connection) -> tuple[int, str]:
        sequence = int(
            db.execute("SELECT value FROM meta WHERE key='sequence'").fetchone()[0]
        )
        head = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
        return sequence, head

    @property
    def head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    @property
    def sequence(self) -> int:
        with self._connect() as db:
            return self._meta(db)[0]

    def append(
        self,
        *,
        transition_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> LifecycleEvent:
        if type(transition_id) is not str or not transition_id:
            raise LifecycleJournalError("transition_id must be a non-empty exact string")
        if type(event_type) is not str or not event_type:
            raise LifecycleJournalError("event_type must be a non-empty exact string")
        if not isinstance(payload, Mapping):
            raise LifecycleJournalError("payload must be a mapping")

        normalized_payload = dict(payload)
        payload_json = canonical_json(normalized_payload)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                """
                SELECT * FROM events
                WHERE transition_id=? AND event_type=?
                """,
                (transition_id, event_type),
            ).fetchone()
            if replay is not None:
                existing = self._row(replay)
                if canonical_json(dict(existing.payload)) != payload_json:
                    raise LifecycleJournalError(
                        "journal event replay carries different payload"
                    )
                return existing

            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            body = {
                "schema": "VERA_MONO_LIFECYCLE_EVENT_V1",
                "sequence": next_sequence,
                "transition_id": transition_id,
                "event_type": event_type,
                "predecessor_event_digest": predecessor,
                "payload": normalized_payload,
            }
            digest = sha256_hex(canonical_json_bytes(body))
            db.execute(
                """
                INSERT INTO events(
                    sequence,transition_id,event_type,predecessor_event_digest,
                    event_digest,payload_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    transition_id,
                    event_type,
                    predecessor,
                    digest,
                    payload_json,
                ),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='sequence'",
                (str(next_sequence),),
            )
            db.execute("UPDATE meta SET value=? WHERE key='head'", (digest,))
            db.commit()
            return LifecycleEvent(
                next_sequence,
                transition_id,
                event_type,
                predecessor,
                digest,
                normalized_payload,
            )

    def verify_chain(self) -> str:
        """Verify sequence continuity, predecessor links, digests, and meta head."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM events ORDER BY sequence"
            ).fetchall()
            meta_sequence, meta_head = self._meta(db)

        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        for row in rows:
            event = self._row(row)
            if event.sequence != expected_sequence:
                raise LifecycleJournalError("lifecycle journal sequence gap")
            if event.predecessor_event_digest != predecessor:
                raise LifecycleJournalError(
                    "lifecycle journal predecessor digest mismatch"
                )
            body = {
                "schema": "VERA_MONO_LIFECYCLE_EVENT_V1",
                "sequence": event.sequence,
                "transition_id": event.transition_id,
                "event_type": event.event_type,
                "predecessor_event_digest": event.predecessor_event_digest,
                "payload": dict(event.payload),
            }
            observed = sha256_hex(canonical_json_bytes(body))
            if observed != event.event_digest:
                raise LifecycleJournalError(
                    "lifecycle journal event digest mismatch"
                )
            predecessor = event.event_digest
            expected_sequence += 1

        observed_sequence = expected_sequence - 1
        if meta_sequence != observed_sequence:
            raise LifecycleJournalError(
                "lifecycle journal meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if meta_head != expected_head:
            raise LifecycleJournalError("lifecycle journal meta head mismatch")
        return expected_head

    def events(self, transition_id: str | None = None) -> tuple[LifecycleEvent, ...]:
        with self._connect() as db:
            if transition_id is None:
                rows = db.execute(
                    "SELECT * FROM events ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM events
                    WHERE transition_id=?
                    ORDER BY sequence
                    """,
                    (transition_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def latest(self, transition_id: str | None = None) -> LifecycleEvent | None:
        with self._connect() as db:
            if transition_id is None:
                row = db.execute(
                    "SELECT * FROM events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
            else:
                row = db.execute(
                    """
                    SELECT * FROM events
                    WHERE transition_id=?
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (transition_id,),
                ).fetchone()
        return None if row is None else self._row(row)

    def has_event(self, transition_id: str, event_type: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT 1 FROM events
                WHERE transition_id=? AND event_type=?
                """,
                (transition_id, event_type),
            ).fetchone()
        return row is not None

    @staticmethod
    def _row(row: sqlite3.Row) -> LifecycleEvent:
        import json

        return LifecycleEvent(
            sequence=int(row["sequence"]),
            transition_id=str(row["transition_id"]),
            event_type=str(row["event_type"]),
            predecessor_event_digest=str(row["predecessor_event_digest"]),
            event_digest=str(row["event_digest"]),
            payload=json.loads(row["payload_json"]),
        )
