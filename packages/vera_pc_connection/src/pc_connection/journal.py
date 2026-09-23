from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import sqlite3
from typing import Any

from pc_connection import PHASE_ONE_OPERATIONS
from pc_connection.canonical import sha256_domain_text_tuple
from pc_connection.validation import (
    sha256_hex,
    uint,
    utc_microseconds,
    uuid_v7,
)

JOURNAL_SCHEMA = "VERA_PCCC_LOCAL_JOURNAL_V1"
JOURNAL_EVENT_DOMAIN = "VERA-PCCC-LOCAL-JOURNAL-EVENT-V1"
ZERO_SHA256 = "0" * 64
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
FIXED_RELATIVE_PATH = Path("journal") / "pccc_journal.sqlite3"
MAX_RECEIPT_BYTES = 256 * 1024


class JournalError(RuntimeError):
    """Base class for local PCCC journal failures."""


class JournalConflict(JournalError):
    """Immutable attempt identity or result evidence diverged."""


class JournalStateError(JournalError):
    """A local transition was not legal."""


class JournalCorrupt(JournalError):
    """Append-only evidence or projection integrity failed."""


class AlreadyStartedRequiresReconciliation(JournalStateError):
    """The handler must not run again until authoritative reconciliation."""


class JournalState(str, Enum):
    CLAIMED = "CLAIMED"
    PREPARING = "PREPARING"
    EFFECT_STARTED = "EFFECT_STARTED"
    RESULT_OBSERVED = "RESULT_OBSERVED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    COMPLETING = "COMPLETING"
    TERMINAL_CONFIRMED = "TERMINAL_CONFIRMED"
    ABANDONED = "ABANDONED"


class JournalEvent(str, Enum):
    CLAIM_RECORDED = "CLAIM_RECORDED"
    PREPARATION_STARTED = "PREPARATION_STARTED"
    EFFECT_START_COMMITTED = "EFFECT_START_COMMITTED"
    RESULT_RECORDED = "RESULT_RECORDED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    COMPLETION_SUBMITTED = "COMPLETION_SUBMITTED"
    TERMINAL_READBACK_CONFIRMED = "TERMINAL_READBACK_CONFIRMED"
    ATTEMPT_ABANDONED = "ATTEMPT_ABANDONED"
    CORRUPTION_DETECTED = "CORRUPTION_DETECTED"


TERMINAL_STATES = frozenset(
    {JournalState.TERMINAL_CONFIRMED, JournalState.ABANDONED}
)


_PATH_TOKEN = object()


@dataclass(frozen=True)
class VerifiedJournalPath:
    path: Path
    root_alias: str
    verification_receipt_digest: str
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _PATH_TOKEN:
            raise JournalError(
                "journal path requires Windows path-authority verification"
            )
        sha256_hex(
            self.verification_receipt_digest,
            "verification_receipt_digest",
        )
        if self.path.name != FIXED_RELATIVE_PATH.name:
            raise JournalError("journal filename is not fixed")

    @classmethod
    def _from_windows_verifier(
        cls,
        path: Path,
        *,
        root_alias: str,
        verification_receipt_digest: str,
    ) -> "VerifiedJournalPath":
        return cls(
            path=path,
            root_alias=root_alias,
            verification_receipt_digest=verification_receipt_digest,
            _token=_PATH_TOKEN,
        )

    @classmethod
    def for_test(cls, root: Path) -> "VerifiedJournalPath":
        return cls(
            path=root / FIXED_RELATIVE_PATH,
            root_alias="TEST_ONLY",
            verification_receipt_digest="f" * 64,
            _token=_PATH_TOKEN,
        )


@dataclass(frozen=True)
class AttemptIdentity:
    job_id: str
    attempt_id: str
    host_id: str
    claim_generation: int
    lease_id: str
    lease_fence: int
    job_digest: str
    authorization_id: str
    authorization_revision: int
    issuer_revocation_epoch: int
    host_revocation_epoch: int
    operation_id: str
    operation_version: int
    retry_class: str
    side_effect_class: str

    def validate(self) -> None:
        for field in (
            "job_id",
            "attempt_id",
            "host_id",
            "lease_id",
            "authorization_id",
        ):
            uuid_v7(getattr(self, field), field)
        uint(
            self.claim_generation,
            "claim_generation",
            minimum=1,
            maximum=9_223_372_036_854_775_807,
        )
        uint(
            self.lease_fence,
            "lease_fence",
            minimum=1,
            maximum=9_223_372_036_854_775_807,
        )
        sha256_hex(self.job_digest, "job_digest")
        uint(
            self.authorization_revision,
            "authorization_revision",
            minimum=1,
            maximum=9_223_372_036_854_775_807,
        )
        uint(
            self.issuer_revocation_epoch,
            "issuer_revocation_epoch",
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        uint(
            self.host_revocation_epoch,
            "host_revocation_epoch",
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        if self.operation_id not in PHASE_ONE_OPERATIONS:
            raise JournalError("operation is not enabled in phase one")
        uint(
            self.operation_version,
            "operation_version",
            minimum=1,
            maximum=4_294_967_295,
        )
        if self.retry_class not in {
            "PURE_READ",
            "CONTENT_ADDRESSED_WRITE",
            "AT_MOST_ONCE",
        }:
            raise JournalError("unsupported retry_class")
        if self.side_effect_class != "NONE":
            raise JournalError(
                "enabled phase-one operations require side_effect_class NONE"
            )

    def as_tuple(self) -> tuple[Any, ...]:
        self.validate()
        return (
            self.job_id,
            self.attempt_id,
            self.host_id,
            self.claim_generation,
            self.lease_id,
            self.lease_fence,
            self.job_digest,
            self.authorization_id,
            self.authorization_revision,
            self.issuer_revocation_epoch,
            self.host_revocation_epoch,
            self.operation_id,
            self.operation_version,
            self.retry_class,
            self.side_effect_class,
        )


@dataclass(frozen=True)
class AttemptProjection:
    identity: AttemptIdentity
    local_state: JournalState
    state_version: int
    last_event_id: str
    last_event_digest: str
    result_digest: str
    terminal_receipt_id: str
    terminal_receipt_digest: str
    server_request_id: str
    server_readback_receipt_id: str
    server_readback_digest: str
    server_time_anchor: str
    local_monotonic_ns: int
    created_at: str
    updated_at: str


class JobJournal:
    """Attempt-fenced local replay gate and tamper-evident event journal.

    The journal never authorizes work and never treats local completion as an
    authoritative server outcome.
    """

    def __init__(self, verified_path: VerifiedJournalPath):
        if not isinstance(verified_path, VerifiedJournalPath):
            raise JournalError("VerifiedJournalPath is required")
        self.verified_path = verified_path
        self.path = verified_path.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._verify_integrity()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS pccc_local_meta (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    schema_version TEXT NOT NULL,
                    root_alias TEXT NOT NULL,
                    verification_receipt_digest TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pccc_local_attempts (
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    host_id TEXT NOT NULL,
                    claim_generation INTEGER NOT NULL CHECK (
                        claim_generation >= 1
                    ),
                    lease_id TEXT NOT NULL,
                    lease_fence INTEGER NOT NULL CHECK (lease_fence >= 1),
                    job_digest TEXT NOT NULL,
                    authorization_id TEXT NOT NULL,
                    authorization_revision INTEGER NOT NULL CHECK (
                        authorization_revision >= 1
                    ),
                    issuer_revocation_epoch INTEGER NOT NULL CHECK (
                        issuer_revocation_epoch >= 0
                    ),
                    host_revocation_epoch INTEGER NOT NULL CHECK (
                        host_revocation_epoch >= 0
                    ),
                    operation_id TEXT NOT NULL,
                    operation_version INTEGER NOT NULL CHECK (
                        operation_version >= 1
                    ),
                    retry_class TEXT NOT NULL,
                    side_effect_class TEXT NOT NULL,
                    local_state TEXT NOT NULL,
                    state_version INTEGER NOT NULL CHECK (state_version >= 1),
                    last_event_id TEXT NOT NULL,
                    last_event_digest TEXT NOT NULL,
                    result_digest TEXT NOT NULL,
                    terminal_receipt_id TEXT NOT NULL,
                    terminal_receipt_digest TEXT NOT NULL,
                    server_request_id TEXT NOT NULL,
                    server_readback_receipt_id TEXT NOT NULL,
                    server_readback_digest TEXT NOT NULL,
                    server_time_anchor TEXT NOT NULL,
                    local_monotonic_ns INTEGER NOT NULL CHECK (
                        local_monotonic_ns >= 0
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (job_id, attempt_id)
                );

                CREATE TABLE IF NOT EXISTS pccc_local_events (
                    local_event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL CHECK (
                        event_sequence >= 1
                    ),
                    predecessor_event_digest TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    prior_state TEXT NOT NULL,
                    committed_state TEXT NOT NULL,
                    state_version INTEGER NOT NULL CHECK (state_version >= 1),
                    claim_generation INTEGER NOT NULL CHECK (
                        claim_generation >= 1
                    ),
                    lease_id TEXT NOT NULL,
                    lease_fence INTEGER NOT NULL CHECK (lease_fence >= 1),
                    payload_digest TEXT NOT NULL,
                    server_time_anchor TEXT NOT NULL,
                    local_monotonic_ns INTEGER NOT NULL CHECK (
                        local_monotonic_ns >= 0
                    ),
                    record_time TEXT NOT NULL,
                    event_digest TEXT NOT NULL,
                    UNIQUE (job_id, attempt_id, event_sequence),
                    FOREIGN KEY (job_id, attempt_id)
                        REFERENCES pccc_local_attempts(job_id, attempt_id)
                        ON DELETE RESTRICT
                );
                """
            )
            row = connection.execute(
                "SELECT * FROM pccc_local_meta WHERE singleton = 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO pccc_local_meta("
                    "singleton, schema_version, root_alias, "
                    "verification_receipt_digest"
                    ") VALUES (1, ?, ?, ?)",
                    (
                        JOURNAL_SCHEMA,
                        self.verified_path.root_alias,
                        self.verified_path.verification_receipt_digest,
                    ),
                )
            elif (
                row["schema_version"] != JOURNAL_SCHEMA
                or row["root_alias"] != self.verified_path.root_alias
                or row["verification_receipt_digest"]
                != self.verified_path.verification_receipt_digest
            ):
                raise JournalError("local journal identity mismatch")

    @staticmethod
    def _event_digest(
        *,
        local_event_id: str,
        job_id: str,
        attempt_id: str,
        event_sequence: int,
        predecessor_event_digest: str,
        event_type: str,
        prior_state: str,
        committed_state: str,
        state_version: int,
        claim_generation: int,
        lease_id: str,
        lease_fence: int,
        payload_digest: str,
        server_time_anchor: str,
        local_monotonic_ns: int,
        record_time: str,
    ) -> str:
        fields = (
            local_event_id,
            job_id,
            attempt_id,
            str(event_sequence),
            predecessor_event_digest,
            event_type,
            prior_state,
            committed_state,
            str(state_version),
            str(claim_generation),
            lease_id,
            str(lease_fence),
            payload_digest,
            server_time_anchor,
            str(local_monotonic_ns),
            record_time,
        )
        return sha256_domain_text_tuple(JOURNAL_EVENT_DOMAIN, fields)

    @staticmethod
    def _validate_event_inputs(
        *,
        local_event_id: str,
        payload_digest: str,
        server_time_anchor: str,
        local_monotonic_ns: int,
        record_time: str,
    ) -> None:
        uuid_v7(local_event_id, "local_event_id")
        sha256_hex(payload_digest, "payload_digest")
        if server_time_anchor:
            utc_microseconds(server_time_anchor, "server_time_anchor")
        uint(
            local_monotonic_ns,
            "local_monotonic_ns",
            minimum=0,
            maximum=9_223_372_036_854_775_807,
        )
        utc_microseconds(record_time, "record_time")

    @staticmethod
    def _identity_from_row(row: sqlite3.Row) -> AttemptIdentity:
        return AttemptIdentity(
            job_id=row["job_id"],
            attempt_id=row["attempt_id"],
            host_id=row["host_id"],
            claim_generation=row["claim_generation"],
            lease_id=row["lease_id"],
            lease_fence=row["lease_fence"],
            job_digest=row["job_digest"],
            authorization_id=row["authorization_id"],
            authorization_revision=row["authorization_revision"],
            issuer_revocation_epoch=row["issuer_revocation_epoch"],
            host_revocation_epoch=row["host_revocation_epoch"],
            operation_id=row["operation_id"],
            operation_version=row["operation_version"],
            retry_class=row["retry_class"],
            side_effect_class=row["side_effect_class"],
        )

    @classmethod
    def _projection_from_row(cls, row: sqlite3.Row) -> AttemptProjection:
        return AttemptProjection(
            identity=cls._identity_from_row(row),
            local_state=JournalState(row["local_state"]),
            state_version=row["state_version"],
            last_event_id=row["last_event_id"],
            last_event_digest=row["last_event_digest"],
            result_digest=row["result_digest"],
            terminal_receipt_id=row["terminal_receipt_id"],
            terminal_receipt_digest=row["terminal_receipt_digest"],
            server_request_id=row["server_request_id"],
            server_readback_receipt_id=row[
                "server_readback_receipt_id"
            ],
            server_readback_digest=row["server_readback_digest"],
            server_time_anchor=row["server_time_anchor"],
            local_monotonic_ns=row["local_monotonic_ns"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _same_identity(row: sqlite3.Row, identity: AttemptIdentity) -> bool:
        return tuple(
            row[key]
            for key in (
                "job_id",
                "attempt_id",
                "host_id",
                "claim_generation",
                "lease_id",
                "lease_fence",
                "job_digest",
                "authorization_id",
                "authorization_revision",
                "issuer_revocation_epoch",
                "host_revocation_epoch",
                "operation_id",
                "operation_version",
                "retry_class",
                "side_effect_class",
            )
        ) == identity.as_tuple()

    def record_claim(
        self,
        identity: AttemptIdentity,
        *,
        local_event_id: str,
        payload_digest: str,
        server_time_anchor: str,
        local_monotonic_ns: int,
        record_time: str,
    ) -> AttemptProjection:
        identity.validate()
        self._validate_event_inputs(
            local_event_id=local_event_id,
            payload_digest=payload_digest,
            server_time_anchor=server_time_anchor,
            local_monotonic_ns=local_monotonic_ns,
            record_time=record_time,
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pccc_local_attempts "
                "WHERE job_id = ? AND attempt_id = ?",
                (identity.job_id, identity.attempt_id),
            ).fetchone()
            if row is not None:
                if not self._same_identity(row, identity):
                    connection.execute("ROLLBACK")
                    raise JournalConflict(
                        "LOCAL_JOURNAL_IDENTITY_CONFLICT"
                    )
                connection.execute("COMMIT")
                return self._projection_from_row(row)

            event_digest = self._event_digest(
                local_event_id=local_event_id,
                job_id=identity.job_id,
                attempt_id=identity.attempt_id,
                event_sequence=1,
                predecessor_event_digest=ZERO_SHA256,
                event_type=JournalEvent.CLAIM_RECORDED.value,
                prior_state="NONE",
                committed_state=JournalState.CLAIMED.value,
                state_version=1,
                claim_generation=identity.claim_generation,
                lease_id=identity.lease_id,
                lease_fence=identity.lease_fence,
                payload_digest=payload_digest,
                server_time_anchor=server_time_anchor,
                local_monotonic_ns=local_monotonic_ns,
                record_time=record_time,
            )
            connection.execute(
                "INSERT INTO pccc_local_attempts VALUES ("
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?"
                ")",
                (
                    *identity.as_tuple(),
                    JournalState.CLAIMED.value,
                    1,
                    local_event_id,
                    event_digest,
                    ZERO_SHA256,
                    ZERO_UUID,
                    ZERO_SHA256,
                    ZERO_UUID,
                    ZERO_UUID,
                    ZERO_SHA256,
                    server_time_anchor,
                    local_monotonic_ns,
                    record_time,
                    record_time,
                ),
            )
            connection.execute(
                "INSERT INTO pccc_local_events VALUES ("
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?"
                ")",
                (
                    local_event_id,
                    identity.job_id,
                    identity.attempt_id,
                    1,
                    ZERO_SHA256,
                    JournalEvent.CLAIM_RECORDED.value,
                    "NONE",
                    JournalState.CLAIMED.value,
                    1,
                    identity.claim_generation,
                    identity.lease_id,
                    identity.lease_fence,
                    payload_digest,
                    server_time_anchor,
                    local_monotonic_ns,
                    record_time,
                    event_digest,
                ),
            )
            row = connection.execute(
                "SELECT * FROM pccc_local_attempts "
                "WHERE job_id = ? AND attempt_id = ?",
                (identity.job_id, identity.attempt_id),
            ).fetchone()
            connection.execute("COMMIT")
            assert row is not None
            return self._projection_from_row(row)

    def _transition(
        self,
        identity: AttemptIdentity,
        *,
        allowed_states: set[JournalState],
        event_type: JournalEvent,
        committed_state: JournalState,
        local_event_id: str,
        payload_digest: str,
        server_time_anchor: str,
        local_monotonic_ns: int,
        record_time: str,
        result_digest: str | None = None,
        terminal_receipt_id: str | None = None,
        terminal_receipt_digest: str | None = None,
        server_request_id: str | None = None,
        server_readback_receipt_id: str | None = None,
        server_readback_digest: str | None = None,
    ) -> AttemptProjection:
        identity.validate()
        self._validate_event_inputs(
            local_event_id=local_event_id,
            payload_digest=payload_digest,
            server_time_anchor=server_time_anchor,
            local_monotonic_ns=local_monotonic_ns,
            record_time=record_time,
        )
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pccc_local_attempts "
                "WHERE job_id = ? AND attempt_id = ?",
                (identity.job_id, identity.attempt_id),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise JournalStateError("attempt is not journaled")
            if not self._same_identity(row, identity):
                connection.execute("ROLLBACK")
                raise JournalConflict("LOCAL_JOURNAL_STALE_ATTEMPT")
            current = JournalState(row["local_state"])
            if current not in allowed_states:
                connection.execute("ROLLBACK")
                raise JournalStateError(
                    f"illegal journal transition from {current.value}"
                )
            sequence = row["state_version"] + 1
            event_digest = self._event_digest(
                local_event_id=local_event_id,
                job_id=identity.job_id,
                attempt_id=identity.attempt_id,
                event_sequence=sequence,
                predecessor_event_digest=row["last_event_digest"],
                event_type=event_type.value,
                prior_state=current.value,
                committed_state=committed_state.value,
                state_version=sequence,
                claim_generation=identity.claim_generation,
                lease_id=identity.lease_id,
                lease_fence=identity.lease_fence,
                payload_digest=payload_digest,
                server_time_anchor=server_time_anchor,
                local_monotonic_ns=local_monotonic_ns,
                record_time=record_time,
            )
            updates = {
                "result_digest": result_digest or row["result_digest"],
                "terminal_receipt_id": (
                    terminal_receipt_id or row["terminal_receipt_id"]
                ),
                "terminal_receipt_digest": (
                    terminal_receipt_digest
                    or row["terminal_receipt_digest"]
                ),
                "server_request_id": (
                    server_request_id or row["server_request_id"]
                ),
                "server_readback_receipt_id": (
                    server_readback_receipt_id
                    or row["server_readback_receipt_id"]
                ),
                "server_readback_digest": (
                    server_readback_digest
                    or row["server_readback_digest"]
                ),
            }
            connection.execute(
                "UPDATE pccc_local_attempts SET "
                "local_state=?, state_version=?, last_event_id=?, "
                "last_event_digest=?, result_digest=?, "
                "terminal_receipt_id=?, terminal_receipt_digest=?, "
                "server_request_id=?, server_readback_receipt_id=?, "
                "server_readback_digest=?, server_time_anchor=?, "
                "local_monotonic_ns=?, updated_at=? "
                "WHERE job_id=? AND attempt_id=?",
                (
                    committed_state.value,
                    sequence,
                    local_event_id,
                    event_digest,
                    updates["result_digest"],
                    updates["terminal_receipt_id"],
                    updates["terminal_receipt_digest"],
                    updates["server_request_id"],
                    updates["server_readback_receipt_id"],
                    updates["server_readback_digest"],
                    server_time_anchor,
                    local_monotonic_ns,
                    record_time,
                    identity.job_id,
                    identity.attempt_id,
                ),
            )
            connection.execute(
                "INSERT INTO pccc_local_events VALUES ("
                "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?"
                ")",
                (
                    local_event_id,
                    identity.job_id,
                    identity.attempt_id,
                    sequence,
                    row["last_event_digest"],
                    event_type.value,
                    current.value,
                    committed_state.value,
                    sequence,
                    identity.claim_generation,
                    identity.lease_id,
                    identity.lease_fence,
                    payload_digest,
                    server_time_anchor,
                    local_monotonic_ns,
                    record_time,
                    event_digest,
                ),
            )
            row = connection.execute(
                "SELECT * FROM pccc_local_attempts "
                "WHERE job_id = ? AND attempt_id = ?",
                (identity.job_id, identity.attempt_id),
            ).fetchone()
            connection.execute("COMMIT")
            assert row is not None
            return self._projection_from_row(row)

    def start_preparation(
        self,
        identity: AttemptIdentity,
        **event: Any,
    ) -> AttemptProjection:
        return self._transition(
            identity,
            allowed_states={JournalState.CLAIMED},
            event_type=JournalEvent.PREPARATION_STARTED,
            committed_state=JournalState.PREPARING,
            **event,
        )

    def commit_effect_start(
        self,
        identity: AttemptIdentity,
        **event: Any,
    ) -> AttemptProjection:
        current = self.get(identity.job_id, identity.attempt_id)
        if current is not None and current.local_state in {
            JournalState.EFFECT_STARTED,
            JournalState.RESULT_OBSERVED,
            JournalState.RECOVERY_REQUIRED,
            JournalState.COMPLETING,
            JournalState.TERMINAL_CONFIRMED,
        }:
            raise AlreadyStartedRequiresReconciliation(
                "ALREADY_STARTED_REQUIRES_RECONCILIATION"
            )
        if identity.side_effect_class == "NONE":
            raise JournalStateError(
                "side-effect-free operation may not commit EFFECT_STARTED"
            )
        return self._transition(
            identity,
            allowed_states={JournalState.PREPARING},
            event_type=JournalEvent.EFFECT_START_COMMITTED,
            committed_state=JournalState.EFFECT_STARTED,
            **event,
        )

    def record_result(
        self,
        identity: AttemptIdentity,
        *,
        result_digest: str,
        **event: Any,
    ) -> AttemptProjection:
        sha256_hex(result_digest, "result_digest")
        allowed = (
            {JournalState.PREPARING}
            if identity.side_effect_class == "NONE"
            else {
                JournalState.EFFECT_STARTED,
                JournalState.RECOVERY_REQUIRED,
            }
        )
        return self._transition(
            identity,
            allowed_states=allowed,
            event_type=JournalEvent.RESULT_RECORDED,
            committed_state=JournalState.RESULT_OBSERVED,
            result_digest=result_digest,
            **event,
        )

    def require_recovery(
        self,
        identity: AttemptIdentity,
        **event: Any,
    ) -> AttemptProjection:
        return self._transition(
            identity,
            allowed_states={
                JournalState.CLAIMED,
                JournalState.PREPARING,
                JournalState.EFFECT_STARTED,
                JournalState.RESULT_OBSERVED,
                JournalState.COMPLETING,
            },
            event_type=JournalEvent.RECOVERY_REQUIRED,
            committed_state=JournalState.RECOVERY_REQUIRED,
            **event,
        )

    def submit_completion(
        self,
        identity: AttemptIdentity,
        *,
        receipt_id: str,
        receipt_digest: str,
        server_request_id: str,
        **event: Any,
    ) -> AttemptProjection:
        uuid_v7(receipt_id, "receipt_id")
        sha256_hex(receipt_digest, "receipt_digest")
        uuid_v7(server_request_id, "server_request_id")
        return self._transition(
            identity,
            allowed_states={JournalState.RESULT_OBSERVED},
            event_type=JournalEvent.COMPLETION_SUBMITTED,
            committed_state=JournalState.COMPLETING,
            terminal_receipt_id=receipt_id,
            terminal_receipt_digest=receipt_digest,
            server_request_id=server_request_id,
            **event,
        )

    def confirm_terminal_readback(
        self,
        identity: AttemptIdentity,
        *,
        server_readback_receipt_id: str,
        server_readback_digest: str,
        expected_result_digest: str,
        expected_receipt_digest: str,
        **event: Any,
    ) -> AttemptProjection:
        uuid_v7(
            server_readback_receipt_id,
            "server_readback_receipt_id",
        )
        sha256_hex(server_readback_digest, "server_readback_digest")
        sha256_hex(expected_result_digest, "expected_result_digest")
        sha256_hex(expected_receipt_digest, "expected_receipt_digest")
        current = self.get(identity.job_id, identity.attempt_id)
        if current is None or current.local_state != JournalState.COMPLETING:
            raise JournalStateError("completion was not submitted")
        if (
            current.result_digest != expected_result_digest
            or current.terminal_receipt_digest != expected_receipt_digest
        ):
            raise JournalConflict("LOCAL_JOURNAL_SERVER_DIVERGENCE")
        return self._transition(
            identity,
            allowed_states={JournalState.COMPLETING},
            event_type=JournalEvent.TERMINAL_READBACK_CONFIRMED,
            committed_state=JournalState.TERMINAL_CONFIRMED,
            server_readback_receipt_id=server_readback_receipt_id,
            server_readback_digest=server_readback_digest,
            **event,
        )

    def abandon(
        self,
        identity: AttemptIdentity,
        **event: Any,
    ) -> AttemptProjection:
        return self._transition(
            identity,
            allowed_states=set(JournalState) - TERMINAL_STATES,
            event_type=JournalEvent.ATTEMPT_ABANDONED,
            committed_state=JournalState.ABANDONED,
            **event,
        )

    def get(
        self,
        job_id: str,
        attempt_id: str,
    ) -> AttemptProjection | None:
        uuid_v7(job_id, "job_id")
        uuid_v7(attempt_id, "attempt_id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM pccc_local_attempts "
                "WHERE job_id=? AND attempt_id=?",
                (job_id, attempt_id),
            ).fetchone()
            return None if row is None else self._projection_from_row(row)

    def recover_incomplete(self) -> tuple[AttemptProjection, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM pccc_local_attempts "
                "WHERE local_state NOT IN "
                "('TERMINAL_CONFIRMED','ABANDONED') "
                "ORDER BY created_at, job_id, attempt_id"
            ).fetchall()
            return tuple(self._projection_from_row(row) for row in rows)

    def _verify_integrity(self) -> None:
        with closing(self._connect()) as connection:
            attempts = connection.execute(
                "SELECT * FROM pccc_local_attempts"
            ).fetchall()
            for attempt in attempts:
                events = connection.execute(
                    "SELECT * FROM pccc_local_events "
                    "WHERE job_id=? AND attempt_id=? "
                    "ORDER BY event_sequence",
                    (attempt["job_id"], attempt["attempt_id"]),
                ).fetchall()
                predecessor = ZERO_SHA256
                for expected_sequence, event in enumerate(
                    events,
                    start=1,
                ):
                    if (
                        event["event_sequence"] != expected_sequence
                        or event["predecessor_event_digest"] != predecessor
                    ):
                        raise JournalCorrupt(
                            "LOCAL_JOURNAL_EVENT_CHAIN_INVALID"
                        )
                    recomputed = self._event_digest(
                        local_event_id=event["local_event_id"],
                        job_id=event["job_id"],
                        attempt_id=event["attempt_id"],
                        event_sequence=event["event_sequence"],
                        predecessor_event_digest=event[
                            "predecessor_event_digest"
                        ],
                        event_type=event["event_type"],
                        prior_state=event["prior_state"],
                        committed_state=event["committed_state"],
                        state_version=event["state_version"],
                        claim_generation=event["claim_generation"],
                        lease_id=event["lease_id"],
                        lease_fence=event["lease_fence"],
                        payload_digest=event["payload_digest"],
                        server_time_anchor=event["server_time_anchor"],
                        local_monotonic_ns=event["local_monotonic_ns"],
                        record_time=event["record_time"],
                    )
                    if recomputed != event["event_digest"]:
                        raise JournalCorrupt(
                            "LOCAL_JOURNAL_EVENT_CHAIN_INVALID"
                        )
                    predecessor = event["event_digest"]
                if (
                    not events
                    or attempt["state_version"] != len(events)
                    or attempt["last_event_digest"] != predecessor
                    or attempt["local_state"]
                    != events[-1]["committed_state"]
                ):
                    raise JournalCorrupt(
                        "LOCAL_JOURNAL_PROJECTION_DIVERGENCE"
                    )


__all__ = [
    "AlreadyStartedRequiresReconciliation",
    "AttemptIdentity",
    "AttemptProjection",
    "FIXED_RELATIVE_PATH",
    "JOURNAL_SCHEMA",
    "JobJournal",
    "JournalConflict",
    "JournalCorrupt",
    "JournalError",
    "JournalEvent",
    "JournalState",
    "JournalStateError",
    "MAX_RECEIPT_BYTES",
    "VerifiedJournalPath",
]
