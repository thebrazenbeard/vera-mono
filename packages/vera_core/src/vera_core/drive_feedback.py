"""Inert, source-only DRIVE feedback transaction reference.

This module provides no witness credentials or runtime installation. It must
never be taken as authentication of a model's claim about a physical effect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
from typing import Callable, Protocol


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
EFFECT_STATES = frozenset({"EFFECT", "NO_EFFECT", "FAILED"})
GOAL_STATES = frozenset({"ACTIVE", "REPLACED", "VETOED", "SATISFIED"})
MAX_AGE_MS = 60_000
FUTURE_SKEW_MS = 5_000

# These are the ONLY supported v1 database objects. They must remain identical
# across creation and re-open: a same-column table missing UNIQUE constraints
# breaks exactly-once admission even though PRAGMA table_info looks healthy.
SCHEMA_DDL = """
CREATE TABLE need_projection (
    need_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    level REAL NOT NULL CHECK(level >= 0 AND level <= 1),
    unit TEXT NOT NULL CHECK(unit = 'normalized')
);
CREATE TABLE goal_projection (
    goal_id TEXT PRIMARY KEY,
    need_id TEXT NOT NULL REFERENCES need_projection(need_id),
    choice_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    target_level REAL NOT NULL CHECK(target_level >= 0 AND target_level <= 1),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','REPLACED','VETOED','SATISFIED')),
    credited_event_id TEXT UNIQUE
);
CREATE UNIQUE INDEX idx_drive_one_active_goal_per_need
    ON goal_projection(need_id) WHERE status='ACTIVE';
CREATE TABLE outcome_receipt (
    event_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    physical_effect_id TEXT NOT NULL UNIQUE,
    evidence_digest TEXT NOT NULL UNIQUE,
    observer_id TEXT NOT NULL,
    source_sequence INTEGER NOT NULL,
    observed_at_ms INTEGER NOT NULL,
    claim_sha256 TEXT NOT NULL,
    witness_id TEXT NOT NULL UNIQUE,
    need_id TEXT NOT NULL,
    need_revision INTEGER NOT NULL,
    goal_credit INTEGER NOT NULL CHECK(goal_credit IN (0,1)),
    goal_credit_reason TEXT NOT NULL,
    UNIQUE(observer_id, source_sequence)
);
CREATE TABLE drive_outbox (
    event_id TEXT PRIMARY KEY REFERENCES outcome_receipt(event_id),
    claim_sha256 TEXT NOT NULL,
    need_id TEXT NOT NULL,
    need_revision INTEGER NOT NULL,
    goal_credit INTEGER NOT NULL CHECK(goal_credit IN (0,1)),
    goal_credit_reason TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0 CHECK(delivered IN (0,1))
);
"""


class DriveFeedbackError(ValueError):
    """Malformed, conflicting, or stale reference feedback input."""


def _id(value: object, label: str) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise DriveFeedbackError(f"{label} must be a bounded opaque identifier")
    return value


def _revision(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value < 2**63 - 1:
        raise DriveFeedbackError(f"{label} must be a bounded nonnegative integer")
    return value


def _level(value: object, label: str) -> float:
    # Reject huge ints by comparison before float conversion. Python's
    # math.isfinite(10**5000) otherwise raises an uncontrolled OverflowError.
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise DriveFeedbackError(f"{label} must be finite normalized level [0,1]")
    if type(value) is float and not math.isfinite(value):
        raise DriveFeedbackError(f"{label} must be finite normalized level [0,1]")
    return float(value)


def _digest(value: object, label: str) -> str:
    if type(value) is not str or DIGEST.fullmatch(value) is None:
        raise DriveFeedbackError(f"{label} must be lowercase SHA-256 hex")
    return value


def _timestamp(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise DriveFeedbackError(f"{label} must be bounded positive milliseconds")
    return value


def _claim_sha256(observation: DriveObservation) -> str:
    return sha256(
        json.dumps(
            asdict(observation),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class DriveObservation:
    event_id: str
    attempt_id: str
    physical_effect_id: str
    observer_id: str
    source_sequence: int
    observed_at_ms: int
    need_id: str
    expected_need_revision: int
    absolute_post_level: float
    unit: str
    goal_id: str | None
    choice_id: str | None
    expected_goal_revision: int | None
    effect_status: str
    request_goal_credit: bool
    evidence_digest: str


class DriveWitnessVerifier(Protocol):
    """Externally custodied verifier supplied by a qualified host.

    Implementations must authenticate the physical source themselves. A model,
    this module, the asserted observer_id, or a digest cannot do so.
    """

    def verify(
        self, observation: DriveObservation, claim_sha256: str
    ) -> DriveWitness | None: ...


@dataclass(frozen=True, slots=True)
class DriveWitness:
    claim_sha256: str
    observer_id: str
    attestation_id: str
    verified_at_ms: int


@dataclass(frozen=True, slots=True)
class DriveAdmission:
    event_id: str
    status: str
    claim_sha256: str
    need_revision: int | None
    goal_credit: bool
    goal_credit_reason: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class NeedProjection:
    need_id: str
    revision: int
    level: float
    unit: str


@dataclass(frozen=True, slots=True)
class GoalProjection:
    goal_id: str
    need_id: str
    choice_id: str
    revision: int
    target_level: float
    status: str
    credited_event_id: str | None


@dataclass(frozen=True, slots=True)
class DriveOutboxItem:
    event_id: str
    claim_sha256: str
    need_id: str
    need_revision: int
    goal_credit: bool
    goal_credit_reason: str


class DriveFeedbackStore:
    """Inert, single-SQLite-transaction reference for witnessed feedback.

    This is NOT attached to QualifiedVeraRuntime, MESO, Volition, any device,
    or an independent witness. An absent/failing host verifier yields HOLD,
    even if caller supplies plausible observer names or evidence digests.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | Path,
        *,
        verifier: DriveWitnessVerifier | None = None,
        clock_ms: Callable[[], int] | None = None,
        max_age_ms: int = MAX_AGE_MS,
        future_skew_ms: int = FUTURE_SKEW_MS,
    ):
        self.path = Path(path).expanduser().absolute()
        self._prepare_private_path()
        if type(max_age_ms) is not int or not 0 < max_age_ms <= 24 * 3600 * 1000:
            raise DriveFeedbackError("max_age_ms out of bounds")
        if type(future_skew_ms) is not int or not 0 <= future_skew_ms <= 60_000:
            raise DriveFeedbackError("future_skew_ms out of bounds")
        self.verifier = verifier
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.max_age_ms = max_age_ms
        self.future_skew_ms = future_skew_ms
        self._reentrancy = threading.local()
        db = self._connect()
        try:
            # Serialize first-open bootstrap and existing-schema inspection.
            # executescript() would implicitly COMMIT this transaction, so
            # individual, module-controlled DDL statements are required.
            db.execute("BEGIN IMMEDIATE")
            current = int(db.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, self.SCHEMA_VERSION):
                raise DriveFeedbackError("unknown DRIVE feedback store schema")
            if current == 0:
                foreign = db.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
                    "AND type IN ('table','index','view','trigger') LIMIT 1"
                ).fetchone()
                if foreign is not None:
                    raise DriveFeedbackError("cannot adopt an unversioned nonempty database")
                # This canonical DDL contains no semicolons inside literals.
                for index, statement in enumerate(SCHEMA_DDL.split(";"), start=1):
                    if statement.strip():
                        db.execute(statement)
                        self._bootstrap_fault_point(index)
                db.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
                self._bootstrap_fault_point("after_version")
            self._verify_schema(db)
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @classmethod
    def _verify_schema(cls, db: sqlite3.Connection) -> None:
        # Compare CREATE SQL to a newly built reference schema. This validates
        # PK/UNIQUE/CHECK/FK and the partial UNIQUE active-goal index, and rejects
        # unexpected triggers/views that might change these transaction effects.
        query = (
            "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL "
            "AND type IN ('table','index','view','trigger') ORDER BY type,name"
        )
        reference = sqlite3.connect(":memory:")
        try:
            reference.executescript(SCHEMA_DDL)
            expected = reference.execute(query).fetchall()
        finally:
            reference.close()
        actual = db.execute(query).fetchall()
        if [tuple(row) for row in actual] != [tuple(row) for row in expected]:
            raise DriveFeedbackError("DRIVE feedback schema does not match v1 invariants")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 3000")
        # WAL sidecars require a separate host review; keep transient rollback
        # journals within the private DB directory for this source reference.
        journal = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal != "delete":
            db.close()
            raise DriveFeedbackError("unsupported durable journal mode")
        return db

    def _prepare_private_path(self) -> None:
        """Reject shared or symlinked POSIX state; never chmod existing data.

        The qualified host must provide trusted storage/ACLs. POSIX mode
        checks are not a portable substitute for Windows ACL enforcement.
        """
        for part in (*reversed(self.path.parents), self.path):
            if part.is_symlink():
                raise DriveFeedbackError("symlinked DRIVE feedback state path")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "posix":
            return

        directory = os.stat(self.path.parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.getuid()
            or stat.S_IMODE(directory.st_mode) & 0o077
        ):
            raise DriveFeedbackError("DRIVE feedback directory must be private and owned")

        def check_existing() -> None:
            current = os.stat(self.path, follow_symlinks=False)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_uid != os.getuid()
                or stat.S_IMODE(current.st_mode) & 0o077
            ):
                raise DriveFeedbackError("DRIVE feedback database must be private and owned")

        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError:
            check_existing()
        else:
            try:
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)

    @staticmethod
    def _fault_point(_: str) -> None:
        """Test seam for transaction aborts; never authorizes an effect."""

    @staticmethod
    def _bootstrap_fault_point(_: int | str) -> None:
        """Test seam for first-open crash recovery; never changes authority."""

    def register_need(
        self, need_id: str, *, level: float, unit: str = "normalized"
    ) -> NeedProjection:
        _id(need_id, "need_id")
        normalized = _level(level, "level")
        if unit != "normalized":
            raise DriveFeedbackError("only normalized absolute need levels supported")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT revision, level, unit FROM need_projection WHERE need_id=?",
                (need_id,),
            ).fetchone()
            if old is None:
                db.execute(
                    "INSERT INTO need_projection VALUES (?, 0, ?, ?)",
                    (need_id, normalized, unit),
                )
            elif old["revision"] != 0 or old["level"] != normalized or old["unit"] != unit:
                raise DriveFeedbackError("need initialization conflicts with durable state")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.read_need(need_id)

    def register_goal(
        self,
        goal_id: str,
        *,
        need_id: str,
        choice_id: str,
        target_level: float,
    ) -> GoalProjection:
        _id(goal_id, "goal_id")
        _id(need_id, "need_id")
        _id(choice_id, "choice_id")
        target = _level(target_level, "target_level")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO goal_projection VALUES (?, ?, ?, 0, ?, 'ACTIVE', NULL)",
                (goal_id, need_id, choice_id, target),
            )
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise DriveFeedbackError("duplicate active goal or unknown need") from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.read_goal(goal_id)

    def replace_goal(
        self,
        old_goal_id: str,
        *,
        new_goal_id: str,
        new_choice_id: str,
        target_level: float,
    ) -> GoalProjection:
        _id(old_goal_id, "old_goal_id")
        _id(new_goal_id, "new_goal_id")
        _id(new_choice_id, "new_choice_id")
        target = _level(target_level, "target_level")
        if old_goal_id == new_goal_id:
            raise DriveFeedbackError("goal replacement requires a new exact identity")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM goal_projection WHERE goal_id=?", (old_goal_id,)
            ).fetchone()
            if old is None or old["status"] != "ACTIVE":
                raise DriveFeedbackError("only an active current goal can be replaced")
            db.execute(
                "UPDATE goal_projection SET status='REPLACED', revision=revision+1 "
                "WHERE goal_id=? AND revision=? AND status='ACTIVE'",
                (old_goal_id, old["revision"]),
            )
            db.execute(
                "INSERT INTO goal_projection VALUES (?, ?, ?, 0, ?, 'ACTIVE', NULL)",
                (new_goal_id, old["need_id"], new_choice_id, target),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.read_goal(new_goal_id)

    def veto_goal(self, goal_id: str) -> GoalProjection:
        _id(goal_id, "goal_id")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "UPDATE goal_projection SET status='VETOED', revision=revision+1 "
                "WHERE goal_id=? AND status='ACTIVE'", (goal_id,)
            )
            if row.rowcount != 1:
                raise DriveFeedbackError("goal missing or no longer active")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.read_goal(goal_id)

    def read_need(self, need_id: str) -> NeedProjection:
        _id(need_id, "need_id")
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM need_projection WHERE need_id=?", (need_id,)
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError(need_id)
        return NeedProjection(str(row["need_id"]), int(row["revision"]), float(row["level"]), str(row["unit"]))

    def read_goal(self, goal_id: str) -> GoalProjection:
        _id(goal_id, "goal_id")
        db = self._connect()
        try:
            row = db.execute(
                "SELECT * FROM goal_projection WHERE goal_id=?", (goal_id,)
            ).fetchone()
        finally:
            db.close()
        if row is None:
            raise KeyError(goal_id)
        return GoalProjection(
            str(row["goal_id"]), str(row["need_id"]), str(row["choice_id"]),
            int(row["revision"]), float(row["target_level"]), str(row["status"]),
            row["credited_event_id"],
        )

    @staticmethod
    def _validate(observation: DriveObservation) -> str:
        if type(observation) is not DriveObservation:
            raise DriveFeedbackError("requires exact DriveObservation")
        for field in (
            "event_id", "attempt_id", "physical_effect_id", "observer_id", "need_id"
        ):
            _id(getattr(observation, field), field)
        for field in ("goal_id", "choice_id"):
            value = getattr(observation, field)
            if value is not None:
                _id(value, field)
        if (observation.goal_id is None) != (observation.choice_id is None):
            raise DriveFeedbackError("goal and choice must be bound together")
        _revision(observation.expected_need_revision, "expected_need_revision")
        if observation.goal_id is None:
            if observation.expected_goal_revision is not None:
                raise DriveFeedbackError("goal revision requires exact goal identity")
        else:
            _revision(observation.expected_goal_revision, "expected_goal_revision")
        _revision(observation.source_sequence, "source_sequence")
        if observation.source_sequence == 0:
            raise DriveFeedbackError("source_sequence must be positive")
        _timestamp(observation.observed_at_ms, "observed_at_ms")
        _level(observation.absolute_post_level, "absolute_post_level")
        if observation.unit != "normalized":
            raise DriveFeedbackError("only normalized absolute need levels supported")
        if type(observation.effect_status) is not str or observation.effect_status not in EFFECT_STATES:
            raise DriveFeedbackError("unsupported effect_status")
        if type(observation.request_goal_credit) is not bool:
            raise DriveFeedbackError("request_goal_credit must be boolean")
        _digest(observation.evidence_digest, "evidence_digest")
        return _claim_sha256(observation)

    def admit(self, observation: DriveObservation) -> DriveAdmission:
        digest = self._validate(observation)
        event_id = observation.event_id
        held = lambda reason: DriveAdmission(
            event_id, "HOLD", digest, None, False, reason
        )
        if self.verifier is None:
            return held("VERIFIER_UNAVAILABLE")
        if getattr(self._reentrancy, "inside", False):
            return held("VERIFIER_REENTRANCY")
        try:
            now_ms = _timestamp(self.clock_ms(), "now_ms")
        except Exception:
            return held("CLOCK_UNAVAILABLE")
        if not (
            now_ms - self.max_age_ms <= observation.observed_at_ms
            <= now_ms + self.future_skew_ms
        ):
            return held("OBSERVATION_NOT_FRESH")
        try:
            self._reentrancy.inside = True
            witness = self.verifier.verify(observation, digest)
        except Exception:
            return held("VERIFIER_ERROR")
        finally:
            self._reentrancy.inside = False
        if type(witness) is not DriveWitness:
            return held("WITNESS_UNAVAILABLE")
        try:
            _id(witness.observer_id, "witness.observer_id")
            _id(witness.attestation_id, "witness.attestation_id")
            _digest(witness.claim_sha256, "witness.claim_sha256")
            _timestamp(witness.verified_at_ms, "witness.verified_at_ms")
        except DriveFeedbackError:
            return held("INVALID_WITNESS")
        if (
            witness.claim_sha256 != digest
            or witness.observer_id != observation.observer_id
            or witness.verified_at_ms < observation.observed_at_ms
            or witness.verified_at_ms > now_ms + self.future_skew_ms
        ):
            return held("WITNESS_BINDING_MISMATCH")

        def admission_time_failure() -> str | None:
            # Recheck AFTER arbitrary verifier latency, lock contention and
            # immediately BEFORE commit. Validation before verification alone
            # permits a stale measurement to receive durable goal credit.
            try:
                current_time = _timestamp(self.clock_ms(), "now_ms")
            except Exception:
                return "CLOCK_UNAVAILABLE"
            if not (
                current_time - self.max_age_ms <= observation.observed_at_ms
                <= current_time + self.future_skew_ms
            ):
                return "OBSERVATION_NOT_FRESH"
            if witness.verified_at_ms > current_time + self.future_skew_ms:
                return "WITNESS_BINDING_MISMATCH"
            return None

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            timing_error = admission_time_failure()
            if timing_error is not None:
                db.rollback()
                return held(timing_error)
            old = db.execute(
                "SELECT * FROM outcome_receipt WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if old is not None:
                if old["claim_sha256"] != digest:
                    raise DriveFeedbackError("same event ID with different observation")
                db.commit()
                return DriveAdmission(
                    event_id, "REPLAY_NOOP", digest, int(old["need_revision"]),
                    False, "REPLAY_NO_NEW_GOAL_CREDIT", True,
                )
            need = db.execute(
                "SELECT * FROM need_projection WHERE need_id=?",
                (observation.need_id,),
            ).fetchone()
            if need is None:
                raise DriveFeedbackError("unknown need projection")
            if need["revision"] != observation.expected_need_revision:
                raise DriveFeedbackError("stale need revision")
            if need["unit"] != observation.unit:
                raise DriveFeedbackError("need measurement unit mismatch")
            previous_level = float(need["level"])
            new_level = float(observation.absolute_post_level)
            if observation.effect_status != "EFFECT" and new_level > previous_level:
                raise DriveFeedbackError("failed/no-op effect cannot claim need improvement")
            last_source = db.execute(
                "SELECT source_sequence, observed_at_ms FROM outcome_receipt "
                "WHERE observer_id=? ORDER BY source_sequence DESC LIMIT 1",
                (observation.observer_id,),
            ).fetchone()
            if last_source is not None and (
                observation.source_sequence <= int(last_source["source_sequence"])
                or observation.observed_at_ms < int(last_source["observed_at_ms"])
            ):
                raise DriveFeedbackError("replayed or out-of-order observer clock")
            goal_credit = False
            goal_reason = "NOT_REQUESTED"
            if observation.request_goal_credit:
                goal_reason = "GOAL_NOT_BOUND"
                if observation.goal_id is not None:
                    goal = db.execute(
                        "SELECT * FROM goal_projection WHERE goal_id=?",
                        (observation.goal_id,),
                    ).fetchone()
                    if goal is None:
                        goal_reason = "GOAL_NOT_CURRENT"
                    elif goal["need_id"] != observation.need_id:
                        raise DriveFeedbackError("goal and need identity mismatch")
                    elif goal["status"] != "ACTIVE":
                        goal_reason = "GOAL_NOT_ACTIVE"
                    elif (
                        goal["choice_id"] != observation.choice_id
                        or goal["revision"] != observation.expected_goal_revision
                    ):
                        goal_reason = "STALE_GOAL_BINDING"
                    elif observation.effect_status != "EFFECT":
                        goal_reason = "NO_VERIFIED_EFFECT"
                    elif new_level <= previous_level:
                        goal_reason = "NO_NEED_IMPROVEMENT"
                    elif new_level < float(goal["target_level"]):
                        goal_reason = "TARGET_UNMET"
                    else:
                        goal_credit = True
                        goal_reason = "EXACT_GOAL_SATISFIED"
            next_need_revision = int(need["revision"]) + 1
            db.execute(
                """
                INSERT INTO outcome_receipt(
                    event_id, attempt_id, physical_effect_id, evidence_digest,
                    observer_id, source_sequence, observed_at_ms, claim_sha256,
                    witness_id, need_id, need_revision, goal_credit, goal_credit_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id, observation.attempt_id, observation.physical_effect_id,
                    observation.evidence_digest, observation.observer_id,
                    observation.source_sequence, observation.observed_at_ms,
                    digest, witness.attestation_id, observation.need_id,
                    next_need_revision, int(goal_credit), goal_reason,
                ),
            )
            self._fault_point("after_receipt")
            count = db.execute(
                "UPDATE need_projection SET revision=revision+1, level=? "
                "WHERE need_id=? AND revision=?",
                (new_level, observation.need_id, observation.expected_need_revision),
            ).rowcount
            if count != 1:
                raise DriveFeedbackError("need projection CAS failed")
            self._fault_point("after_need")
            if goal_credit:
                count = db.execute(
                    "UPDATE goal_projection SET status='SATISFIED', "
                    "revision=revision+1, credited_event_id=? "
                    "WHERE goal_id=? AND choice_id=? AND revision=? AND status='ACTIVE'",
                    (
                        event_id, observation.goal_id, observation.choice_id,
                        observation.expected_goal_revision,
                    ),
                ).rowcount
                if count != 1:
                    raise DriveFeedbackError("goal projection CAS failed")
            self._fault_point("after_goal")
            db.execute(
                "INSERT INTO drive_outbox(event_id,claim_sha256,need_id,need_revision,"
                "goal_credit,goal_credit_reason) VALUES(?,?,?,?,?,?)",
                (
                    event_id, digest, observation.need_id,
                    next_need_revision, int(goal_credit), goal_reason,
                ),
            )
            self._fault_point("after_outbox")
            timing_error = admission_time_failure()
            if timing_error is not None:
                db.rollback()
                return held(timing_error)
            db.commit()
            return DriveAdmission(
                event_id, "ADMITTED", digest, next_need_revision,
                goal_credit, goal_reason,
            )
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise DriveFeedbackError("duplicate effect/attempt/evidence/observer identity") from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def pending_outbox(self, *, limit: int = 1000) -> tuple[DriveOutboxItem, ...]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise DriveFeedbackError("outbox batch limit must be 1..1000")
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT * FROM drive_outbox WHERE delivered=0 ORDER BY rowid LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            db.close()
        return tuple(
            DriveOutboxItem(
                str(row["event_id"]), str(row["claim_sha256"]),
                str(row["need_id"]), int(row["need_revision"]),
                bool(row["goal_credit"]), str(row["goal_credit_reason"]),
            )
            for row in rows
        )

    def ack_outbox(self, event_id: str) -> bool:
        """Record host claim of delivery, not proof consumer accepted it."""
        _id(event_id, "event_id")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "UPDATE drive_outbox SET delivered=1 "
                "WHERE event_id=? AND delivered=0", (event_id,)
            )
            if row.rowcount == 0 and db.execute(
                "SELECT 1 FROM drive_outbox WHERE event_id=?", (event_id,)
            ).fetchone() is None:
                raise KeyError(event_id)
            db.commit()
            return row.rowcount == 1
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
