"""Durable bounded coordination for multi-step long-horizon plans.

Adapted from Project Runner's deterministic portfolio-wave admission semantics:
priority ordering, family budgets, collision deferral, exact durable state, and
explicit non-authority. This module does not execute step effects.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import sqlite3


_PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


class StepState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    SUCCEEDED = "SUCCEEDED"
    FAILED_TERMINAL = "FAILED_TERMINAL"


@dataclass(frozen=True, slots=True)
class PlanStep:
    step_id: str
    dependencies: tuple[str, ...]
    priority: str
    family_id: str
    collision_keys: tuple[str, ...]
    max_attempts: int

    def __post_init__(self) -> None:
        for label, value in (
            ("step_id", self.step_id),
            ("family_id", self.family_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if self.priority not in _PRIORITY:
            raise ValueError("priority must be one of P0..P4")
        for label, values in (
            ("dependencies", self.dependencies),
            ("collision_keys", self.collision_keys),
        ):
            if type(values) is not tuple or any(
                type(item) is not str or not item for item in values
            ):
                raise ValueError(f"{label} must contain non-empty exact strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must not contain duplicates")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive exact integer")


@dataclass(frozen=True, slots=True)
class LongHorizonPlan:
    plan_id: str
    objective: str
    steps: tuple[PlanStep, ...]

    def __post_init__(self) -> None:
        for label, value in (
            ("plan_id", self.plan_id),
            ("objective", self.objective),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(self.steps) is not tuple or not self.steps:
            raise ValueError("steps must be a non-empty tuple")
        if any(type(step) is not PlanStep for step in self.steps):
            raise TypeError("steps must contain exact PlanStep values")
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        known = set(ids)
        for step in self.steps:
            unknown = set(step.dependencies) - known
            if unknown:
                raise ValueError(
                    f"unknown dependency for {step.step_id}: {sorted(unknown)}"
                )
            if step.step_id in step.dependencies:
                raise ValueError("step cannot depend on itself")
        self._validate_acyclic()

    def _validate_acyclic(self) -> None:
        dependencies = {
            step.step_id: set(step.dependencies) for step in self.steps
        }
        remaining = set(dependencies)
        resolved: set[str] = set()
        while remaining:
            ready = {
                step_id
                for step_id in remaining
                if dependencies[step_id] <= resolved
            }
            if not ready:
                raise ValueError("plan dependencies contain a cycle")
            resolved.update(ready)
            remaining.difference_update(ready)


@dataclass(frozen=True, slots=True)
class PlanBudget:
    max_parallel: int
    max_per_family: int

    def validate(self) -> None:
        if type(self.max_parallel) is not int or self.max_parallel < 1:
            raise ValueError("max_parallel must be a positive exact integer")
        if type(self.max_per_family) is not int or self.max_per_family < 1:
            raise ValueError("max_per_family must be a positive exact integer")
        if self.max_per_family > self.max_parallel:
            raise ValueError("max_per_family cannot exceed max_parallel")


@dataclass(frozen=True, slots=True)
class PlanAdmission:
    step_id: str
    family_id: str
    priority: str
    collision_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanDeferral:
    step_id: str
    reason: str
    collision_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanReadyFrontier:
    selected: tuple[PlanAdmission, ...]
    deferred: tuple[PlanDeferral, ...]


@dataclass(frozen=True, slots=True)
class StepClaim:
    plan_id: str
    step_id: str
    holder: str
    fencing_token: int
    attempt: int
    lease_expires_at: float
    authorization_effect: str = "NONE"


@dataclass(frozen=True, slots=True)
class StepRecord:
    step_id: str
    state: StepState
    attempts: int
    fencing_token: int
    generation: int
    authorization_effect: str = "NONE"


@dataclass(frozen=True, slots=True)
class LongHorizonSnapshot:
    plan_id: str
    plan_digest: str
    objective: str
    completed_steps: tuple[str, ...]
    failed_terminal_steps: tuple[str, ...]
    total_attempts: int
    correction_count: int
    authorization_effect: str = "NONE"


def _canonical_plan(plan: LongHorizonPlan) -> str:
    payload = {
        "plan_id": plan.plan_id,
        "objective": plan.objective,
        "steps": [
            {
                **asdict(step),
                "dependencies": list(step.dependencies),
                "collision_keys": list(step.collision_keys),
            }
            for step in plan.steps
        ],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def plan_digest(plan: LongHorizonPlan) -> str:
    return hashlib.sha256(_canonical_plan(plan).encode("utf-8")).hexdigest()


class DurableLongHorizonCoordinator:
    def __init__(self, path: str | Path, *, plan: LongHorizonPlan) -> None:
        if type(plan) is not LongHorizonPlan:
            raise TypeError("plan must be exact LongHorizonPlan")
        self.path = Path(path)
        self.plan = plan
        self._steps = {step.step_id: step for step in plan.steps}
        self._order = {step.step_id: index for index, step in enumerate(plan.steps)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def _init_db(self) -> None:
        digest = plan_digest(self.plan)
        canonical = _canonical_plan(self.plan)
        with closing(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS long_horizon_plan (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    plan_id TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    canonical_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS long_horizon_steps (
                    step_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK(fencing_token >= 0),
                    generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
                    holder TEXT,
                    lease_expires_at REAL,
                    last_failure_attempt INTEGER
                );
                CREATE TABLE IF NOT EXISTS long_horizon_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS long_horizon_corrections (
                    step_id TEXT NOT NULL,
                    failed_attempt INTEGER NOT NULL,
                    correction_ref TEXT NOT NULL,
                    PRIMARY KEY(step_id, failed_attempt)
                );
                """
            )
            row = db.execute(
                "SELECT plan_id,plan_digest,objective,canonical_json "
                "FROM long_horizon_plan WHERE singleton=1"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO long_horizon_plan VALUES(1,?,?,?,?)",
                    (self.plan.plan_id, digest, self.plan.objective, canonical),
                )
                db.executemany(
                    """
                    INSERT INTO long_horizon_steps(
                        step_id,state,attempts,fencing_token,generation
                    ) VALUES(?, ?, 0, 0, 0)
                    """,
                    [
                        (step.step_id, StepState.PENDING.value)
                        for step in self.plan.steps
                    ],
                )
                db.commit()
            elif (
                str(row["plan_id"]) != self.plan.plan_id
                or str(row["plan_digest"]) != digest
                or str(row["canonical_json"]) != canonical
            ):
                raise ValueError("plan digest does not match durable plan identity")

    def _rows(self, db: sqlite3.Connection) -> dict[str, sqlite3.Row]:
        rows = db.execute(
            "SELECT * FROM long_horizon_steps"
        ).fetchall()
        if {str(row["step_id"]) for row in rows} != set(self._steps):
            raise ValueError("durable plan step membership is corrupt")
        return {str(row["step_id"]): row for row in rows}

    def _has_correction(
        self,
        db: sqlite3.Connection,
        *,
        step_id: str,
        failed_attempt: int,
    ) -> bool:
        return db.execute(
            """
            SELECT 1 FROM long_horizon_corrections
            WHERE step_id=? AND failed_attempt=?
            """,
            (step_id, failed_attempt),
        ).fetchone() is not None

    def _ready_reason(
        self,
        db: sqlite3.Connection,
        rows: dict[str, sqlite3.Row],
        step: PlanStep,
    ) -> str | None:
        row = rows[step.step_id]
        state = StepState(str(row["state"]))
        if state is StepState.SUCCEEDED:
            return "SUCCEEDED"
        if state is StepState.FAILED_TERMINAL:
            return "FAILED_TERMINAL"
        if state is StepState.RUNNING:
            return "RUNNING"
        dependency_states = {
            dependency: StepState(str(rows[dependency]["state"]))
            for dependency in step.dependencies
        }
        if any(
            value is StepState.FAILED_TERMINAL
            for value in dependency_states.values()
        ):
            return "DEPENDENCY_FAILED"
        if any(
            value is not StepState.SUCCEEDED
            for value in dependency_states.values()
        ):
            return "DEPENDENCIES"
        if state is StepState.FAILED_RETRYABLE:
            failed_attempt = row["last_failure_attempt"]
            if failed_attempt is None or not self._has_correction(
                db,
                step_id=step.step_id,
                failed_attempt=int(failed_attempt),
            ):
                return "CORRECTION_REQUIRED"
        return None

    def _plan_ready_with_db(
        self,
        db: sqlite3.Connection,
        rows: dict[str, sqlite3.Row],
        *,
        budget: PlanBudget,
        occupied_collision_keys: tuple[str, ...],
    ) -> PlanReadyFrontier:
        reserved = set(occupied_collision_keys)
        selected: list[PlanAdmission] = []
        deferred: list[PlanDeferral] = []
        family_load: dict[str, int] = {}
        for step in sorted(
            self.plan.steps,
            key=lambda item: (
                _PRIORITY[item.priority],
                self._order[item.step_id],
                item.step_id,
            ),
        ):
            reason = self._ready_reason(db, rows, step)
            if reason is not None:
                deferred.append(
                    PlanDeferral(step.step_id, reason, step.collision_keys)
                )
                continue
            if reserved.intersection(step.collision_keys):
                deferred.append(
                    PlanDeferral(step.step_id, "COLLISION", step.collision_keys)
                )
                continue
            if len(selected) >= budget.max_parallel:
                deferred.append(
                    PlanDeferral(
                        step.step_id,
                        "GLOBAL_BUDGET",
                        step.collision_keys,
                    )
                )
                continue
            if family_load.get(step.family_id, 0) >= budget.max_per_family:
                deferred.append(
                    PlanDeferral(
                        step.step_id,
                        "FAMILY_BUDGET",
                        step.collision_keys,
                    )
                )
                continue
            selected.append(
                PlanAdmission(
                    step_id=step.step_id,
                    family_id=step.family_id,
                    priority=step.priority,
                    collision_keys=step.collision_keys,
                )
            )
            family_load[step.family_id] = (
                family_load.get(step.family_id, 0) + 1
            )
            reserved.update(step.collision_keys)
        return PlanReadyFrontier(tuple(selected), tuple(deferred))

    @staticmethod
    def _validate_occupied(
        occupied_collision_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        if type(occupied_collision_keys) is not tuple or any(
            type(value) is not str or not value
            for value in occupied_collision_keys
        ):
            raise ValueError(
                "occupied_collision_keys must contain non-empty exact strings"
            )
        return occupied_collision_keys

    def plan_ready(
        self,
        *,
        budget: PlanBudget,
        occupied_collision_keys: tuple[str, ...] = (),
    ) -> PlanReadyFrontier:
        if type(budget) is not PlanBudget:
            raise TypeError("budget must be exact PlanBudget")
        budget.validate()
        occupied_collision_keys = self._validate_occupied(
            occupied_collision_keys
        )
        with closing(self._connect()) as db:
            rows = self._rows(db)
            return self._plan_ready_with_db(
                db,
                rows,
                budget=budget,
                occupied_collision_keys=occupied_collision_keys,
            )

    @staticmethod
    def _finite(value: float, field: str) -> float:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        return value

    def claim(
        self,
        step_id: str,
        *,
        holder: str,
        now: float,
        ttl: float,
        budget: PlanBudget | None = None,
        occupied_collision_keys: tuple[str, ...] = (),
    ) -> StepClaim:
        if step_id not in self._steps:
            raise KeyError(step_id)
        if type(holder) is not str or not holder:
            raise ValueError("holder must be a non-empty exact string")
        now = self._finite(now, "now")
        ttl = self._finite(ttl, "ttl")
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        effective_budget = (
            PlanBudget(max_parallel=1, max_per_family=1)
            if budget is None
            else budget
        )
        if type(effective_budget) is not PlanBudget:
            raise TypeError("budget must be exact PlanBudget")
        effective_budget.validate()
        occupied_collision_keys = self._validate_occupied(
            occupied_collision_keys
        )

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            rows = self._rows(db)
            step = self._steps[step_id]
            reason = self._ready_reason(db, rows, step)
            if reason is not None:
                if reason == "DEPENDENCIES":
                    raise ValueError("step dependencies are not satisfied")
                raise ValueError(f"step is not ready: {reason}")
            frontier = self._plan_ready_with_db(
                db,
                rows,
                budget=effective_budget,
                occupied_collision_keys=occupied_collision_keys,
            )
            if step_id not in {item.step_id for item in frontier.selected}:
                raise ValueError("step is outside current budget selection")
            row = rows[step_id]
            attempts = int(row["attempts"])
            if attempts >= step.max_attempts:
                raise ValueError("step attempt budget exhausted")
            token = int(row["fencing_token"]) + 1
            attempt = attempts + 1
            generation = int(row["generation"]) + 1
            expires = now + ttl
            db.execute(
                """
                UPDATE long_horizon_steps
                SET state=?, attempts=?, fencing_token=?, generation=?,
                    holder=?, lease_expires_at=?
                WHERE step_id=?
                """,
                (
                    StepState.RUNNING.value,
                    attempt,
                    token,
                    generation,
                    holder,
                    expires,
                    step_id,
                ),
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        return StepClaim(
            plan_id=self.plan.plan_id,
            step_id=step_id,
            holder=holder,
            fencing_token=token,
            attempt=attempt,
            lease_expires_at=expires,
        )

    def complete(
        self,
        claim: StepClaim,
        *,
        success: bool,
        evidence_ref: str,
        now: float,
    ) -> StepRecord:
        if type(claim) is not StepClaim:
            raise TypeError("claim must be exact StepClaim")
        if claim.plan_id != self.plan.plan_id:
            raise ValueError("claim plan identity mismatch")
        if type(success) is not bool:
            raise TypeError("success must be exact bool")
        if type(evidence_ref) is not str or not evidence_ref:
            raise ValueError("evidence_ref must be a non-empty exact string")
        now = self._finite(now, "now")
        step = self._steps.get(claim.step_id)
        if step is None:
            raise KeyError(claim.step_id)

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM long_horizon_steps WHERE step_id=?",
                (claim.step_id,),
            ).fetchone()
            assert row is not None
            if StepState(str(row["state"])) is not StepState.RUNNING:
                raise ValueError("step claim is stale or no longer running")
            if (
                str(row["holder"]) != claim.holder
                or int(row["fencing_token"]) != claim.fencing_token
                or int(row["attempts"]) != claim.attempt
            ):
                raise ValueError("step claim fencing token is stale")
            expires = row["lease_expires_at"]
            if expires is None or now >= float(expires):
                raise ValueError("step claim lease expired")
            if success:
                state = StepState.SUCCEEDED
                last_failure_attempt = None
                outcome = "SUCCEEDED"
            elif claim.attempt < step.max_attempts:
                state = StepState.FAILED_RETRYABLE
                last_failure_attempt = claim.attempt
                outcome = "FAILED_RETRYABLE"
            else:
                state = StepState.FAILED_TERMINAL
                last_failure_attempt = claim.attempt
                outcome = "FAILED_TERMINAL"
            generation = int(row["generation"]) + 1
            db.execute(
                """
                UPDATE long_horizon_steps
                SET state=?, generation=?, holder=NULL, lease_expires_at=NULL,
                    last_failure_attempt=?
                WHERE step_id=?
                """,
                (
                    state.value,
                    generation,
                    last_failure_attempt,
                    claim.step_id,
                ),
            )
            db.execute(
                """
                INSERT INTO long_horizon_events(
                    step_id, attempt, outcome, evidence_ref
                ) VALUES(?,?,?,?)
                """,
                (claim.step_id, claim.attempt, outcome, evidence_ref),
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        return StepRecord(
            step_id=claim.step_id,
            state=state,
            attempts=claim.attempt,
            fencing_token=claim.fencing_token,
            generation=generation,
        )

    def apply_correction(self, step_id: str, *, correction_ref: str) -> None:
        if step_id not in self._steps:
            raise KeyError(step_id)
        if type(correction_ref) is not str or not correction_ref:
            raise ValueError("correction_ref must be a non-empty exact string")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,last_failure_attempt FROM long_horizon_steps "
                "WHERE step_id=?",
                (step_id,),
            ).fetchone()
            assert row is not None
            if StepState(str(row["state"])) is not StepState.FAILED_RETRYABLE:
                raise ValueError("correction requires FAILED_RETRYABLE step")
            failed_attempt = row["last_failure_attempt"]
            if failed_attempt is None:
                raise ValueError("retryable failure lacks failed attempt identity")
            try:
                db.execute(
                    """
                    INSERT INTO long_horizon_corrections(
                        step_id, failed_attempt, correction_ref
                    ) VALUES(?,?,?)
                    """,
                    (step_id, int(failed_attempt), correction_ref),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "correction already recorded for failed attempt"
                ) from exc
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def snapshot(self) -> LongHorizonSnapshot:
        with closing(self._connect()) as db:
            rows = self._rows(db)
            corrections = int(
                db.execute(
                    "SELECT COUNT(*) FROM long_horizon_corrections"
                ).fetchone()[0]
            )
        completed = tuple(
            step.step_id
            for step in self.plan.steps
            if StepState(str(rows[step.step_id]["state"])) is StepState.SUCCEEDED
        )
        failed = tuple(
            step.step_id
            for step in self.plan.steps
            if StepState(str(rows[step.step_id]["state"]))
            is StepState.FAILED_TERMINAL
        )
        return LongHorizonSnapshot(
            plan_id=self.plan.plan_id,
            plan_digest=plan_digest(self.plan),
            objective=self.plan.objective,
            completed_steps=completed,
            failed_terminal_steps=failed,
            total_attempts=sum(int(row["attempts"]) for row in rows.values()),
            correction_count=corrections,
        )
