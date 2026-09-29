"""Durable budgeted dispatch admission with lease fencing.

Adapted from Project Runner's M6 execution fabric. This component only governs
dispatch admission ownership/quota. It does not execute work or grant effect
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import sqlite3


class DispatchFenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DispatchAdmission:
    lineage_id: str
    work_id: str
    holder: str
    fencing_token: int
    expires_at: float
    budget_generation: int
    remaining_active: int
    remaining_retries: int
    remaining_backend_jobs: int
    authorization_effect: str = "NONE"


class DurableDispatchGate:
    def __init__(
        self,
        path: str | Path,
        *,
        lineage_id: str,
        remaining_active: int | None = None,
        remaining_retries: int | None = None,
        remaining_backend_jobs: int | None = None,
    ) -> None:
        self.path = Path(path)
        self.lineage_id = self._text(lineage_id, "lineage_id")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM dispatch_budgets WHERE lineage_id=?",
                (self.lineage_id,),
            ).fetchone()
            if row is None:
                if None in (
                    remaining_active,
                    remaining_retries,
                    remaining_backend_jobs,
                ):
                    raise ValueError("new dispatch gate requires initial budgets")
                values = (
                    int(remaining_active),
                    int(remaining_retries),
                    int(remaining_backend_jobs),
                )
                if any(value < 0 for value in values):
                    raise ValueError("dispatch budgets must be non-negative")
                db.execute(
                    """
                    INSERT INTO dispatch_budgets(
                        lineage_id, remaining_active, remaining_retries,
                        remaining_backend_jobs, generation
                    ) VALUES(?,?,?,?,0)
                    """,
                    (self.lineage_id, *values),
                )
                db.commit()

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        lineage_id: str,
    ) -> "DurableDispatchGate":
        return cls(path, lineage_id=lineage_id)

    @staticmethod
    def _text(value: str, field: str) -> str:
        if type(value) is not str or not value:
            raise ValueError(f"{field} must be a non-empty exact string")
        return value

    @staticmethod
    def _finite(value: float, field: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        return value

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS dispatch_budgets (
                    lineage_id TEXT PRIMARY KEY,
                    remaining_active INTEGER NOT NULL CHECK(remaining_active >= 0),
                    remaining_retries INTEGER NOT NULL CHECK(remaining_retries >= 0),
                    remaining_backend_jobs INTEGER NOT NULL CHECK(remaining_backend_jobs >= 0),
                    generation INTEGER NOT NULL CHECK(generation >= 0)
                );
                CREATE TABLE IF NOT EXISTS dispatch_leases (
                    lineage_id TEXT NOT NULL,
                    work_id TEXT NOT NULL,
                    holder TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL CHECK(fencing_token > 0),
                    expires_at REAL NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0,1)),
                    PRIMARY KEY(lineage_id, work_id),
                    FOREIGN KEY(lineage_id) REFERENCES dispatch_budgets(lineage_id)
                );
                """
            )

    def claim(
        self,
        *,
        work_id: str,
        holder: str,
        now: float,
        ttl: float,
        expected_generation: int,
        retry: bool,
    ) -> DispatchAdmission:
        work_id = self._text(work_id, "work_id")
        holder = self._text(holder, "holder")
        now = self._finite(now, "now")
        ttl = self._finite(ttl, "ttl")
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        if type(retry) is not bool:
            raise TypeError("retry must be an exact bool")

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            budget = db.execute(
                """
                SELECT remaining_active, remaining_retries,
                       remaining_backend_jobs, generation
                FROM dispatch_budgets WHERE lineage_id=?
                """,
                (self.lineage_id,),
            ).fetchone()
            if budget is None:
                raise ValueError("dispatch budget not found")
            generation = int(budget["generation"])
            if generation != expected_generation:
                raise DispatchFenceError("dispatch budget generation mismatch")
            active = int(budget["remaining_active"])
            retries = int(budget["remaining_retries"])
            backend = int(budget["remaining_backend_jobs"])
            if active <= 0:
                raise DispatchFenceError("active budget exhausted")
            if backend <= 0:
                raise DispatchFenceError("backend jobs budget exhausted")
            if retry and retries <= 0:
                raise DispatchFenceError("retry budget exhausted")

            existing = db.execute(
                """
                SELECT holder, fencing_token, expires_at, completed
                FROM dispatch_leases
                WHERE lineage_id=? AND work_id=?
                """,
                (self.lineage_id, work_id),
            ).fetchone()
            if existing is None:
                token = 1
                db.execute(
                    """
                    INSERT INTO dispatch_leases(
                        lineage_id, work_id, holder, fencing_token,
                        expires_at, completed
                    ) VALUES(?,?,?,?,?,0)
                    """,
                    (self.lineage_id, work_id, holder, token, now + ttl),
                )
            else:
                if bool(existing["completed"]):
                    raise DispatchFenceError("completed work cannot be reclaimed")
                if now < float(existing["expires_at"]):
                    raise DispatchFenceError("active lease already exists")
                token = int(existing["fencing_token"]) + 1
                db.execute(
                    """
                    UPDATE dispatch_leases
                    SET holder=?, fencing_token=?, expires_at=?, completed=0
                    WHERE lineage_id=? AND work_id=?
                    """,
                    (holder, token, now + ttl, self.lineage_id, work_id),
                )

            next_generation = generation + 1
            next_active = active - 1
            next_retries = retries - int(retry)
            next_backend = backend - 1
            updated = db.execute(
                """
                UPDATE dispatch_budgets
                SET remaining_active=?, remaining_retries=?,
                    remaining_backend_jobs=?, generation=?
                WHERE lineage_id=? AND generation=?
                """,
                (
                    next_active,
                    next_retries,
                    next_backend,
                    next_generation,
                    self.lineage_id,
                    generation,
                ),
            )
            if updated.rowcount != 1:
                raise DispatchFenceError(
                    "dispatch budget generation changed during admission"
                )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

        return DispatchAdmission(
            lineage_id=self.lineage_id,
            work_id=work_id,
            holder=holder,
            fencing_token=token,
            expires_at=now + ttl,
            budget_generation=next_generation,
            remaining_active=next_active,
            remaining_retries=next_retries,
            remaining_backend_jobs=next_backend,
        )

    def complete(self, admission: DispatchAdmission, *, now: float) -> bool:
        if type(admission) is not DispatchAdmission:
            raise TypeError("admission must be exact DispatchAdmission")
        now = self._finite(now, "now")
        with self._connect() as db:
            row = db.execute(
                """
                SELECT holder, fencing_token, expires_at, completed
                FROM dispatch_leases
                WHERE lineage_id=? AND work_id=?
                """,
                (self.lineage_id, admission.work_id),
            ).fetchone()
            if row is None:
                return False
            if (
                bool(row["completed"])
                or row["holder"] != admission.holder
                or int(row["fencing_token"]) != admission.fencing_token
                or now >= float(row["expires_at"])
            ):
                return False
            updated = db.execute(
                """
                UPDATE dispatch_leases SET completed=1
                WHERE lineage_id=? AND work_id=? AND holder=?
                  AND fencing_token=? AND completed=0
                """,
                (
                    self.lineage_id,
                    admission.work_id,
                    admission.holder,
                    admission.fencing_token,
                ),
            )
            db.commit()
            return updated.rowcount == 1
