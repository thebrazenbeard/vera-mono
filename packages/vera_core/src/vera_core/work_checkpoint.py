"""Durable crash-recovery checkpoints for long-running work.

Adapted from WIP. Checkpoints preserve fact/inference separation and the exact
continuation frontier. They do not self-authorize resumed actions or external
effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any


class RecoveryCheckpointError(ValueError):
    pass


class StaleCheckpointGeneration(RecoveryCheckpointError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryCheckpoint:
    objective: str
    observed: tuple[str, ...]
    inferred: tuple[str, ...]
    completed: tuple[str, ...]
    unfinished: tuple[str, ...]
    next_action: str
    do_not_repeat: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.objective) is not str or not self.objective:
            raise ValueError("objective must be a non-empty exact string")
        if type(self.next_action) is not str or not self.next_action:
            raise ValueError("next_action must be a non-empty exact string")
        for field_name in (
            "observed",
            "inferred",
            "completed",
            "unfinished",
            "do_not_repeat",
        ):
            values = tuple(getattr(self, field_name))
            if any(type(item) is not str or not item for item in values):
                raise ValueError(
                    f"{field_name} must contain non-empty exact strings"
                )
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True, slots=True)
class RecoveryCheckpointHead:
    workspace_id: str
    checkpoint_id: str
    generation: int
    checkpoint: RecoveryCheckpoint
    authorization_effect: str = "NONE"


class RecoveryCheckpointStore:
    def __init__(self, path: str | Path, *, workspace_id: str):
        self.path = Path(path)
        if type(workspace_id) is not str or not workspace_id:
            raise ValueError("workspace_id must be a non-empty exact string")
        self.workspace_id = workspace_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoint_meta (
                    workspace_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL CHECK(generation >= 0),
                    latest_checkpoint TEXT
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    workspace_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence > 0),
                    checkpoint_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, sequence),
                    UNIQUE(workspace_id, checkpoint_id),
                    FOREIGN KEY(workspace_id)
                        REFERENCES checkpoint_meta(workspace_id)
                );
                """
            )
            row = db.execute(
                "SELECT generation FROM checkpoint_meta WHERE workspace_id=?",
                (self.workspace_id,),
            ).fetchone()
            if row is None:
                db.execute(
                    """
                    INSERT INTO checkpoint_meta(
                        workspace_id, generation, latest_checkpoint
                    ) VALUES(?,0,NULL)
                    """,
                    (self.workspace_id,),
                )
            db.commit()

    @staticmethod
    def _payload(checkpoint: RecoveryCheckpoint) -> str:
        value = asdict(checkpoint)
        for key in (
            "observed",
            "inferred",
            "completed",
            "unfinished",
            "do_not_repeat",
        ):
            value[key] = list(value[key])
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _checkpoint(payload: str) -> RecoveryCheckpoint:
        try:
            value: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RecoveryCheckpointError(
                "stored checkpoint payload is invalid JSON"
            ) from exc
        return RecoveryCheckpoint(
            objective=value["objective"],
            observed=tuple(value["observed"]),
            inferred=tuple(value["inferred"]),
            completed=tuple(value["completed"]),
            unfinished=tuple(value["unfinished"]),
            next_action=value["next_action"],
            do_not_repeat=tuple(value["do_not_repeat"]),
        )

    def append(
        self,
        checkpoint: RecoveryCheckpoint,
        *,
        expected_generation: int,
    ) -> RecoveryCheckpointHead:
        if type(checkpoint) is not RecoveryCheckpoint:
            raise TypeError("checkpoint must be exact RecoveryCheckpoint")
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError(
                "expected_generation must be a non-negative integer"
            )

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT generation, latest_checkpoint
                FROM checkpoint_meta WHERE workspace_id=?
                """,
                (self.workspace_id,),
            ).fetchone()
            assert row is not None
            generation = int(row["generation"])
            if generation != expected_generation:
                raise StaleCheckpointGeneration(
                    "checkpoint generation mismatch; refresh before writing"
                )
            sequence = generation + 1
            checkpoint_id = f"cp-{sequence:06d}"
            parent = row["latest_checkpoint"]
            db.execute(
                """
                INSERT INTO checkpoints(
                    workspace_id, sequence, checkpoint_id,
                    parent_checkpoint_id, payload_json
                ) VALUES(?,?,?,?,?)
                """,
                (
                    self.workspace_id,
                    sequence,
                    checkpoint_id,
                    parent,
                    self._payload(checkpoint),
                ),
            )
            updated = db.execute(
                """
                UPDATE checkpoint_meta
                SET generation=?, latest_checkpoint=?
                WHERE workspace_id=? AND generation=?
                """,
                (
                    sequence,
                    checkpoint_id,
                    self.workspace_id,
                    expected_generation,
                ),
            )
            if updated.rowcount != 1:
                raise StaleCheckpointGeneration(
                    "checkpoint generation changed during write"
                )
            db.commit()

        return RecoveryCheckpointHead(
            workspace_id=self.workspace_id,
            checkpoint_id=checkpoint_id,
            generation=sequence,
            checkpoint=checkpoint,
        )

    def head(self) -> RecoveryCheckpointHead:
        with self._connect() as db:
            meta = db.execute(
                """
                SELECT generation, latest_checkpoint
                FROM checkpoint_meta WHERE workspace_id=?
                """,
                (self.workspace_id,),
            ).fetchone()
            assert meta is not None
            checkpoint_id = meta["latest_checkpoint"]
            if checkpoint_id is None:
                raise RecoveryCheckpointError("workspace has no checkpoint")
            row = db.execute(
                """
                SELECT payload_json FROM checkpoints
                WHERE workspace_id=? AND checkpoint_id=?
                """,
                (self.workspace_id, checkpoint_id),
            ).fetchone()
            if row is None:
                raise RecoveryCheckpointError(
                    "checkpoint head points to missing record"
                )
            return RecoveryCheckpointHead(
                workspace_id=self.workspace_id,
                checkpoint_id=str(checkpoint_id),
                generation=int(meta["generation"]),
                checkpoint=self._checkpoint(str(row["payload_json"])),
            )
