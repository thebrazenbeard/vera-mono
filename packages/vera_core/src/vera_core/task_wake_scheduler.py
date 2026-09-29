"""Durable task wake scheduling without execution authority.

Adapted from Pro-Run's interval scheduler semantics. Wakes are durable,
idempotent host inputs. They do not open tasks, execute tools, or authorize
effects by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class TaskWake:
    wake_id: str
    schedule_id: str
    task_id: str
    due_at: float
    authorization_effect: str = "NONE"


class TaskWakeScheduler:
    """SQLite-backed interval wake ledger with restart continuity."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    every_seconds REAL NOT NULL CHECK (every_seconds > 0),
                    next_at REAL NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS wakes (
                    wake_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    due_at REAL NOT NULL,
                    UNIQUE(schedule_id, due_at)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _text(value: str, field: str) -> str:
        if type(value) is not str or not value:
            raise ValueError(f"{field} must be a non-empty exact string")
        return value

    @staticmethod
    def _time(value: float, field: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        return value

    def add_interval(
        self,
        *,
        schedule_id: str,
        task_id: str,
        every_seconds: float,
        first_at: float,
    ) -> None:
        schedule_id = self._text(schedule_id, "schedule_id")
        task_id = self._text(task_id, "task_id")
        every_seconds = self._time(every_seconds, "every_seconds")
        first_at = self._time(first_at, "first_at")
        if every_seconds <= 0:
            raise ValueError("every_seconds must be > 0")

        with self._connect() as db:
            try:
                db.execute(
                    """
                    INSERT INTO schedules(
                        schedule_id, task_id, every_seconds, next_at, enabled
                    ) VALUES(?,?,?,?,1)
                    """,
                    (schedule_id, task_id, every_seconds, first_at),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"schedule_id is already bound: {schedule_id}") from exc
            db.commit()

    @staticmethod
    def _wake_id(schedule_id: str, task_id: str, due_at: float) -> str:
        body = f"vera-task-wake-v1\0{schedule_id}\0{task_id}\0{due_at:.6f}"
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def tick(
        self,
        *,
        now: float,
        max_occurrences: int = 100,
    ) -> tuple[TaskWake, ...]:
        now = self._time(now, "now")
        if type(max_occurrences) is not int or max_occurrences < 1:
            raise ValueError("max_occurrences must be a positive integer")

        emitted: list[TaskWake] = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """
                SELECT schedule_id, task_id, every_seconds, next_at
                FROM schedules
                WHERE enabled=1 AND next_at <= ?
                ORDER BY next_at ASC, schedule_id ASC
                """,
                (now,),
            ).fetchall()

            for row in rows:
                schedule_id = str(row["schedule_id"])
                task_id = str(row["task_id"])
                interval = float(row["every_seconds"])
                next_at = float(row["next_at"])

                while next_at <= now and len(emitted) < max_occurrences:
                    wake_id = self._wake_id(schedule_id, task_id, next_at)
                    cursor = db.execute(
                        """
                        INSERT OR IGNORE INTO wakes(
                            wake_id, schedule_id, task_id, due_at
                        ) VALUES(?,?,?,?)
                        """,
                        (wake_id, schedule_id, task_id, next_at),
                    )
                    if cursor.rowcount == 1:
                        emitted.append(
                            TaskWake(
                                wake_id=wake_id,
                                schedule_id=schedule_id,
                                task_id=task_id,
                                due_at=next_at,
                            )
                        )
                    next_at += interval

                db.execute(
                    "UPDATE schedules SET next_at=? WHERE schedule_id=?",
                    (next_at, schedule_id),
                )
                if len(emitted) >= max_occurrences:
                    break

            db.commit()

        return tuple(emitted)
