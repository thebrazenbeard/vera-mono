"""Portable persistent coordination repository for the Vera monorepo."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from .contracts import (
    CoordinationEvent,
    CoordinationEventDraft,
    RepositoryConflict,
    canonical_hash,
    canonicalize,
)


class CoordinationRepositoryCorrupt(RepositoryConflict):
    """Persistent coordination history or its projection failed integrity checks."""


class SQLiteCoordinationRepository:
    """Append-only, digest-chained SQLite coordination event repository."""

    SCHEMA = "VERA_MONO_COORDINATION_SQLITE_V1"
    GENESIS_HEAD = canonical_hash(
        {"schema": "VERA_MONO_COORDINATION_SQLITE_GENESIS_V1"}
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS coordination_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    schema_version TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL,
                    head_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coordination_events (
                    event_sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    thread_key TEXT NOT NULL,
                    source_branch TEXT NOT NULL,
                    target_branch TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    active_issue TEXT,
                    requested_perspective TEXT,
                    supersedes_event_id TEXT,
                    acknowledges_event_id TEXT,
                    payload_json TEXT NOT NULL,
                    reference_data_json TEXT NOT NULL,
                    record_time TEXT NOT NULL,
                    predecessor_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS coordination_thread_sequence_idx
                    ON coordination_events(thread_key,event_sequence);
                CREATE INDEX IF NOT EXISTS coordination_target_sequence_idx
                    ON coordination_events(target_branch,event_sequence);
                CREATE INDEX IF NOT EXISTS coordination_ack_idx
                    ON coordination_events(acknowledges_event_id);
                CREATE UNIQUE INDEX IF NOT EXISTS coordination_one_successor_idx
                    ON coordination_events(supersedes_event_id)
                    WHERE supersedes_event_id IS NOT NULL;
                """
            )
            row = db.execute(
                "SELECT * FROM coordination_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                db.execute(
                    """
                    INSERT INTO coordination_meta(
                        singleton,schema_version,event_sequence,head_digest
                    ) VALUES(1,?,?,?)
                    """,
                    (self.SCHEMA, 0, self.GENESIS_HEAD),
                )
            elif row["schema_version"] != self.SCHEMA:
                raise CoordinationRepositoryCorrupt(
                    "coordination repository schema identity mismatch"
                )
        self.verify_integrity()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        return json.dumps(
            canonicalize(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _decode_object(value: str, label: str) -> dict[str, Any]:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise CoordinationRepositoryCorrupt(
                f"{label} is not valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise CoordinationRepositoryCorrupt(
                f"{label} must decode to an object"
            )
        return decoded

    @classmethod
    def _event_from_row(cls, row: sqlite3.Row) -> CoordinationEvent:
        return CoordinationEvent.from_row(
            {
                "event_id": row["event_id"],
                "event_sequence": row["event_sequence"],
                "thread_key": row["thread_key"],
                "source_branch": row["source_branch"],
                "target_branch": row["target_branch"],
                "event_type": row["event_type"],
                "status": row["status"],
                "objective": row["objective"],
                "summary": row["summary"],
                "active_issue": row["active_issue"],
                "requested_perspective": row["requested_perspective"],
                "supersedes_event_id": row["supersedes_event_id"],
                "acknowledges_event_id": row["acknowledges_event_id"],
                "payload": cls._decode_object(
                    row["payload_json"],
                    "coordination payload",
                ),
                "reference_data": cls._decode_object(
                    row["reference_data_json"],
                    "coordination reference_data",
                ),
                "record_time": row["record_time"],
            }
        )

    @staticmethod
    def _event_digest(
        event: CoordinationEvent,
        predecessor_digest: str,
    ) -> str:
        return canonical_hash(
            {
                "schema": "VERA_MONO_COORDINATION_SQLITE_EVENT_V1",
                "predecessor_digest": predecessor_digest,
                "event": event.as_dict(),
            }
        )

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, str]:
        row = db.execute(
            "SELECT event_sequence,head_digest FROM coordination_meta "
            "WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise CoordinationRepositoryCorrupt(
                "coordination repository meta row is missing"
            )
        return int(row["event_sequence"]), str(row["head_digest"])

    @property
    def head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    @property
    def event_sequence(self) -> int:
        with self._connect() as db:
            return self._meta(db)[0]

    def append(self, draft: CoordinationEventDraft) -> CoordinationEvent:
        draft.validate()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence, predecessor = self._meta(db)

            if draft.acknowledges_event_id is not None:
                original = db.execute(
                    "SELECT thread_key FROM coordination_events WHERE event_id=?",
                    (draft.acknowledges_event_id,),
                ).fetchone()
                if original is None:
                    raise RepositoryConflict(
                        "acknowledged coordination event does not exist"
                    )
                if original["thread_key"] != draft.thread_key:
                    raise RepositoryConflict(
                        "acknowledgement must stay in same thread"
                    )
            if draft.supersedes_event_id is not None:
                if draft.supersedes_event_id == draft.acknowledges_event_id:
                    raise RepositoryConflict(
                        "one reference cannot acknowledge and supersede"
                    )
                prior = db.execute(
                    "SELECT thread_key FROM coordination_events WHERE event_id=?",
                    (draft.supersedes_event_id,),
                ).fetchone()
                if prior is None:
                    raise RepositoryConflict(
                        "superseded coordination event does not exist"
                    )
                if prior["thread_key"] != draft.thread_key:
                    raise RepositoryConflict(
                        "supersession must stay in same thread"
                    )

            next_sequence = sequence + 1
            event_id = canonical_hash(
                {
                    "schema": "VERA_COORDINATION_EVENT_ID_V1",
                    "sequence": next_sequence,
                    **draft.canonical_dict(),
                }
            )[:32]
            event = CoordinationEvent(
                event_id=event_id,
                event_sequence=next_sequence,
                thread_key=draft.thread_key,
                source_branch=draft.source_branch,
                target_branch=draft.target_branch,
                event_type=draft.event_type,
                status=draft.status,
                objective=draft.objective,
                summary=draft.summary,
                active_issue=draft.active_issue,
                requested_perspective=draft.requested_perspective,
                supersedes_event_id=draft.supersedes_event_id,
                acknowledges_event_id=draft.acknowledges_event_id,
                payload=canonicalize(draft.payload),
                reference_data=canonicalize(draft.reference_data),
                record_time=datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                ),
            )
            digest = self._event_digest(event, predecessor)
            try:
                db.execute(
                    """
                    INSERT INTO coordination_events(
                        event_sequence,event_id,thread_key,source_branch,
                        target_branch,event_type,status,objective,summary,
                        active_issue,requested_perspective,supersedes_event_id,
                        acknowledges_event_id,payload_json,reference_data_json,
                        record_time,predecessor_digest,event_digest
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.event_sequence,
                        event.event_id,
                        event.thread_key,
                        event.source_branch,
                        event.target_branch,
                        event.event_type,
                        event.status,
                        event.objective,
                        event.summary,
                        event.active_issue,
                        event.requested_perspective,
                        event.supersedes_event_id,
                        event.acknowledges_event_id,
                        self._json(event.payload),
                        self._json(event.reference_data),
                        event.record_time,
                        predecessor,
                        digest,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RepositoryConflict(
                    "coordination append uniqueness conflict"
                ) from exc
            db.execute(
                """
                UPDATE coordination_meta
                SET event_sequence=?,head_digest=?
                WHERE singleton=1
                """,
                (next_sequence, digest),
            )
            db.commit()
            return event

    def get(self, event_id: str) -> CoordinationEvent | None:
        self.verify_integrity()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM coordination_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
        return None if row is None else self._event_from_row(row)

    def list_thread(self, thread_key: str) -> tuple[CoordinationEvent, ...]:
        self.verify_integrity()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM coordination_events
                WHERE thread_key=?
                ORDER BY event_sequence
                """,
                (thread_key,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def read_inbox(
        self,
        target_branch: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        include_acknowledged: bool = False,
    ) -> tuple[CoordinationEvent, ...]:
        self.verify_integrity()
        with self._connect() as db:
            if include_acknowledged:
                rows = db.execute(
                    """
                    SELECT * FROM coordination_events
                    WHERE target_branch=? AND event_sequence>?
                    ORDER BY event_sequence
                    LIMIT ?
                    """,
                    (target_branch, after_sequence, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT event.* FROM coordination_events AS event
                    WHERE event.target_branch=?
                      AND event.event_sequence>?
                      AND NOT EXISTS(
                        SELECT 1 FROM coordination_events AS response
                        WHERE response.acknowledges_event_id=event.event_id
                          AND response.source_branch=?
                      )
                    ORDER BY event.event_sequence
                    LIMIT ?
                    """,
                    (
                        target_branch,
                        after_sequence,
                        target_branch,
                        limit,
                    ),
                ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def verify_integrity(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM coordination_events ORDER BY event_sequence"
            ).fetchall()
            sequence, head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        seen_event_ids: set[str] = set()
        seen_successors: set[str] = set()
        events_by_id: dict[str, CoordinationEvent] = {}
        for row in rows:
            if int(row["event_sequence"]) != expected_sequence:
                raise CoordinationRepositoryCorrupt(
                    "coordination event sequence gap"
                )
            if row["predecessor_digest"] != predecessor:
                raise CoordinationRepositoryCorrupt(
                    "coordination predecessor digest mismatch"
                )
            event = self._event_from_row(row)
            if event.event_id in seen_event_ids:
                raise CoordinationRepositoryCorrupt(
                    "duplicate coordination event identity"
                )
            expected_id = canonical_hash(
                {
                    "schema": "VERA_COORDINATION_EVENT_ID_V1",
                    "sequence": event.event_sequence,
                    "thread_key": event.thread_key,
                    "source_branch": event.source_branch,
                    "target_branch": event.target_branch,
                    "event_type": event.event_type,
                    "status": event.status,
                    "objective": event.objective,
                    "summary": event.summary,
                    "active_issue": event.active_issue,
                    "requested_perspective": event.requested_perspective,
                    "supersedes_event_id": event.supersedes_event_id,
                    "acknowledges_event_id": event.acknowledges_event_id,
                    "payload": canonicalize(event.payload),
                    "reference_data": canonicalize(event.reference_data),
                }
            )[:32]
            if expected_id != event.event_id:
                raise CoordinationRepositoryCorrupt(
                    "coordination event identity mismatch"
                )
            if event.acknowledges_event_id is not None:
                original = events_by_id.get(event.acknowledges_event_id)
                if original is None or original.thread_key != event.thread_key:
                    raise CoordinationRepositoryCorrupt(
                        "coordination acknowledgement lineage is invalid"
                    )
            if event.supersedes_event_id is not None:
                prior = events_by_id.get(event.supersedes_event_id)
                if prior is None or prior.thread_key != event.thread_key:
                    raise CoordinationRepositoryCorrupt(
                        "coordination supersession lineage is invalid"
                    )
                if event.supersedes_event_id in seen_successors:
                    raise CoordinationRepositoryCorrupt(
                        "coordination event has multiple successors"
                    )
                seen_successors.add(event.supersedes_event_id)
            observed = self._event_digest(event, predecessor)
            if observed != row["event_digest"]:
                raise CoordinationRepositoryCorrupt(
                    "coordination event digest mismatch"
                )
            predecessor = observed
            seen_event_ids.add(event.event_id)
            events_by_id[event.event_id] = event
            expected_sequence += 1

        if sequence != expected_sequence - 1:
            raise CoordinationRepositoryCorrupt(
                "coordination meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise CoordinationRepositoryCorrupt(
                "coordination meta head mismatch"
            )
        return head

    def context(self) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_COORDINATION_SQLITE_CONTEXT_V1",
            "event_sequence": self.event_sequence,
            "head_digest": self.verify_integrity(),
            "path": str(self.path),
        }
