"""Contracts and canonical serialization for V.E.R.A. coordination bus v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Any, Literal, Mapping, Protocol, Sequence

WORKSTREAMS = frozenset({
    "workstream/memory", "workstream/time", "workstream/initiatives",
    "workstream/integration", "workstream/coordination", "workstream/identity",
    "workstream/project-architecture", "workstream/github-repo",
})
OBSOLETE_WORKSTREAMS = frozenset({"workstream/initiative"})
# Historical aliases are decode-only. Strict actors and new drafts never normalize them.
ACTOR_WORKSTREAM_ALIASES: Mapping[str, str] = {}
LEGACY_STORED_ADDRESSES = frozenset({
    "chatgpt-project-current", "codex-independent-audit",
    "feature/branch-session-anchor-contract-v1",
    "feature/memory-cross-chat-contract-v1", "GitHub Connection",
    "github-review", "time-management", "workstream/initiative",
})
EVENT_TYPES = frozenset({
    "STATUS", "ISSUE", "ACKNOWLEDGEMENT", "REVIEW", "DECISION", "RESOLUTION"
})
STATUSES = frozenset({
    "DRAFT", "READY_FOR_REVIEW", "IN_PROGRESS", "BLOCKED", "DEGRADED",
    "ACKNOWLEDGED", "CHANGES_REQUESTED", "APPROVED", "RESOLVED", "CANCELLED",
})
EVENT_STATUS_PAIRS = frozenset({
    ("STATUS", "DRAFT"), ("STATUS", "READY_FOR_REVIEW"),
    ("STATUS", "IN_PROGRESS"), ("STATUS", "BLOCKED"),
    ("STATUS", "DEGRADED"), ("STATUS", "CANCELLED"),
    ("ISSUE", "READY_FOR_REVIEW"), ("ISSUE", "BLOCKED"),
    ("ISSUE", "DEGRADED"), ("ACKNOWLEDGEMENT", "ACKNOWLEDGED"),
    ("REVIEW", "READY_FOR_REVIEW"), ("REVIEW", "CHANGES_REQUESTED"),
    ("REVIEW", "APPROVED"), ("DECISION", "APPROVED"),
    ("DECISION", "CANCELLED"), ("RESOLUTION", "RESOLVED"),
    ("RESOLUTION", "CANCELLED"),
})

PERMISSION_READ_SELF = "coordination:read:self"
PERMISSION_READ_ANY = "coordination:read:any"
PERMISSION_POST = "coordination:post"
PERMISSION_ACKNOWLEDGE = "coordination:acknowledge"
PERMISSION_STATUS = "coordination:status"
PERMISSION_REVIEW = "coordination:review"
PERMISSION_RESOLVE = "coordination:resolve"
PERMISSION_DECIDE = "coordination:decide"
ALL_PERMISSIONS = frozenset({
    PERMISSION_READ_SELF, PERMISSION_READ_ANY, PERMISSION_POST,
    PERMISSION_ACKNOWLEDGE, PERMISSION_STATUS, PERMISSION_REVIEW,
    PERMISSION_RESOLVE, PERMISSION_DECIDE,
})
RECORD_CLASS = "OPERATIONAL_COORDINATION"
INSTRUCTION_TRUST = "DATA_NOT_INSTRUCTION"
CANONICAL_MEMORY_ELIGIBLE = False

Operation = Literal[
    "coordination_read_inbox", "coordination_post", "coordination_acknowledge",
    "coordination_publish_status", "coordination_request_review",
    "coordination_resolve_thread", "coordination_entry_checkpoint",
    "coordination_exit_checkpoint",
]
ResultClass = Literal["COMPLETE", "DENIED", "INVALID", "CONFLICT", "NOT_FOUND"]


class RepositoryConflict(RuntimeError):
    """Append-only lineage or uniqueness conflict."""


class CoordinationRepository(Protocol):
    def append(self, draft: "CoordinationEventDraft") -> "CoordinationEvent": ...
    def get(self, event_id: str) -> "CoordinationEvent | None": ...
    def list_thread(self, thread_key: str) -> tuple["CoordinationEvent", ...]: ...
    def read_inbox(
        self, target_branch: str, *, after_sequence: int = 0, limit: int = 100,
        include_acknowledged: bool = False,
    ) -> tuple["CoordinationEvent", ...]: ...


@dataclass(frozen=True)
class ActorContext:
    workstream: str
    permissions: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        try:
            validate_workstream(self.workstream, "workstream")
        except ValueError as exc:
            if self.workstream in OBSOLETE_WORKSTREAMS:
                raise ValueError(
                    "STRICT_ACTOR_OBSOLETE_ROUTE: use 'workstream/initiatives'"
                ) from exc
            raise

    @property
    def canonical_workstream(self) -> str:
        return self.workstream

    def validate(self) -> None:
        validate_workstream(self.workstream, "workstream")
        unknown = sorted(set(self.permissions) - ALL_PERMISSIONS)
        if unknown:
            raise ValueError(f"unknown permissions: {', '.join(unknown)}")

    def require(self, permission: str) -> None:
        self.validate()
        if permission not in self.permissions:
            raise PermissionError(
                f"{self.workstream} lacks required permission {permission!r}"
            )


@dataclass(frozen=True)
class CoordinationEventDraft:
    thread_key: str
    source_branch: str
    target_branch: str | None
    event_type: str
    status: str
    objective: str
    summary: str
    active_issue: str | None = None
    requested_perspective: str | None = None
    supersedes_event_id: str | None = None
    acknowledges_event_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    reference_data: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        validate_text(self.thread_key, "thread_key")
        validate_workstream(self.source_branch, "source_branch")
        if self.target_branch is not None:
            validate_workstream(self.target_branch, "target_branch")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported event_type {self.event_type!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unsupported status {self.status!r}")
        if (self.event_type, self.status) not in EVENT_STATUS_PAIRS:
            raise ValueError(f"invalid event_type/status pair: {self.event_type}/{self.status}")
        validate_text(self.objective, "objective")
        validate_text(self.summary, "summary")
        validate_optional_text(self.active_issue, "active_issue")
        validate_optional_text(self.requested_perspective, "requested_perspective")
        validate_optional_text(self.supersedes_event_id, "supersedes_event_id")
        validate_optional_text(self.acknowledges_event_id, "acknowledges_event_id")
        validate_json_object(self.payload, "payload")
        validate_json_object(self.reference_data, "reference_data")
        if self.event_type in {"ACKNOWLEDGEMENT", "REVIEW", "RESOLUTION"} and not self.acknowledges_event_id:
            raise ValueError(f"{self.event_type} requires acknowledges_event_id")
        if self.event_type == "ISSUE" and self.active_issue is None:
            raise ValueError("ISSUE requires active_issue")
        if self.event_type == "REVIEW" and self.requested_perspective is not None:
            raise ValueError("REVIEW must answer, not request, a perspective")

    def canonical_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "thread_key": self.thread_key, "source_branch": self.source_branch,
            "target_branch": self.target_branch, "event_type": self.event_type,
            "status": self.status, "objective": self.objective,
            "summary": self.summary, "active_issue": self.active_issue,
            "requested_perspective": self.requested_perspective,
            "supersedes_event_id": self.supersedes_event_id,
            "acknowledges_event_id": self.acknowledges_event_id,
            "payload": canonicalize(self.payload),
            "reference_data": canonicalize(self.reference_data),
        }


@dataclass(frozen=True)
class CoordinationEvent:
    event_id: str
    event_sequence: int
    thread_key: str
    source_branch: str
    target_branch: str | None
    event_type: str
    status: str
    objective: str
    summary: str
    active_issue: str | None
    requested_perspective: str | None
    supersedes_event_id: str | None
    acknowledges_event_id: str | None
    payload: Mapping[str, Any]
    reference_data: Mapping[str, Any]
    record_time: str
    source_address_class: str = "CANONICAL"
    target_address_class: str | None = None
    record_class: str = field(default=RECORD_CLASS, init=False)
    instruction_trust: str = field(default=INSTRUCTION_TRUST, init=False)
    canonical_memory_eligible: bool = field(default=CANONICAL_MEMORY_ELIGIBLE, init=False)

    def __post_init__(self) -> None:
        if self.target_branch is not None and self.target_address_class is None:
            object.__setattr__(
                self, "target_address_class",
                classify_stored_address(self.target_branch),
            )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CoordinationEvent":
        raw_time = row["record_time"]
        record_time = (
            raw_time.astimezone(timezone.utc).isoformat()
            if isinstance(raw_time, datetime) else str(raw_time)
        )
        source = str(row["source_branch"])
        target = nullable(row.get("target_branch"))
        event_type = str(row["event_type"])
        status = str(row["status"])
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported stored event_type {event_type!r}")
        if status not in STATUSES or (event_type, status) not in EVENT_STATUS_PAIRS:
            raise ValueError(f"invalid stored event_type/status pair: {event_type}/{status}")
        validate_stored_address(source, "source_branch")
        if target is not None:
            validate_stored_address(target, "target_branch")
        payload = row.get("payload", {})
        reference_data = row.get("reference_data", {})
        validate_json_object(payload, "payload")
        validate_json_object(reference_data, "reference_data")
        event = cls(
            event_id=str(row["event_id"]),
            event_sequence=int(row["event_sequence"]),
            thread_key=str(row["thread_key"]), source_branch=source,
            target_branch=target, event_type=event_type, status=status,
            objective=str(row["objective"]), summary=str(row["summary"]),
            active_issue=nullable(row.get("active_issue")),
            requested_perspective=nullable(row.get("requested_perspective")),
            supersedes_event_id=nullable(row.get("supersedes_event_id")),
            acknowledges_event_id=nullable(row.get("acknowledges_event_id")),
            payload=canonicalize(payload), reference_data=canonicalize(reference_data),
            record_time=record_time,
            source_address_class=classify_stored_address(source),
            target_address_class=None if target is None else classify_stored_address(target),
        )
        validate_text(event.event_id, "event_id")
        validate_text(event.thread_key, "thread_key")
        validate_text(event.objective, "objective")
        validate_text(event.summary, "summary")
        validate_text(event.record_time, "record_time")
        if event.event_sequence <= 0:
            raise ValueError("event_sequence must be positive")
        return event

    def as_dict(self) -> dict[str, Any]:
        return canonicalize(asdict(self))


@dataclass(frozen=True)
class CoordinationReceipt:
    schema: str
    operation: Operation
    result_class: ResultClass
    outcome_code: str
    actor_workstream: str
    thread_key: str | None
    event_id: str | None
    event_sequence: int | None
    target_branch: str | None
    database_write_confirmed: bool
    acknowledges_event_id: str | None
    result_hash: str
    error: str | None
    limitations: tuple[str, ...]
    record_class: str = field(default=RECORD_CLASS, init=False)
    instruction_trust: str = field(default=INSTRUCTION_TRUST, init=False)
    canonical_memory_eligible: bool = field(default=CANONICAL_MEMORY_ELIGIBLE, init=False)

    def as_dict(self) -> dict[str, Any]:
        return canonicalize(asdict(self))


@dataclass(frozen=True)
class CoordinationResult:
    receipt: CoordinationReceipt
    events: tuple[CoordinationEvent, ...] = ()


def make_result(
    operation: Operation, result_class: ResultClass, actor: ActorContext,
    events: Sequence[CoordinationEvent], database_write_confirmed: bool,
    thread_key: str | None, target_branch: str | None,
    acknowledges_event_id: str | None, limitations: tuple[str, ...],
    error: str | None = None,
) -> CoordinationResult:
    materialized = tuple(events)
    event = materialized[-1] if materialized else None
    outcome = f"{operation.upper()}_{result_class}"
    base = {
        "schema": "VERA_COORDINATION_RECEIPT_V1", "operation": operation,
        "result_class": result_class, "outcome_code": outcome,
        "actor_workstream": actor.workstream, "thread_key": thread_key,
        "event_id": None if event is None else event.event_id,
        "event_sequence": None if event is None else event.event_sequence,
        "target_branch": target_branch,
        "database_write_confirmed": database_write_confirmed,
        "acknowledges_event_id": acknowledges_event_id,
        "record_class": RECORD_CLASS,
        "instruction_trust": INSTRUCTION_TRUST,
        "canonical_memory_eligible": CANONICAL_MEMORY_ELIGIBLE,
        "events": [item.as_dict() for item in materialized],
        "error": error, "limitations": list(limitations),
    }
    receipt = CoordinationReceipt(
        schema=base["schema"], operation=operation, result_class=result_class,
        outcome_code=outcome, actor_workstream=actor.workstream,
        thread_key=thread_key, event_id=base["event_id"],
        event_sequence=base["event_sequence"], target_branch=target_branch,
        database_write_confirmed=database_write_confirmed,
        acknowledges_event_id=acknowledges_event_id,
        result_hash=canonical_hash(base), error=error, limitations=limitations,
    )
    return CoordinationResult(receipt=receipt, events=materialized)


def canonical_hash(value: Any) -> str:
    return sha256(json.dumps(
        canonicalize(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats are not valid JSON")
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ValueError(f"value is not JSON-serializable: {type(value).__name__}")


def validate_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise ValueError(f"{name} contains control characters")


def validate_optional_text(value: str | None, name: str) -> None:
    if value is not None:
        validate_text(value, name)


def validate_json_object(value: Mapping[str, Any], name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    canonicalize(value)


def validate_workstream(value: str, name: str) -> None:
    if value in OBSOLETE_WORKSTREAMS:
        raise ValueError(f"{name} uses obsolete route {value!r}; use 'workstream/initiatives'")
    if value not in WORKSTREAMS:
        raise ValueError(f"{name} must be one of {sorted(WORKSTREAMS)}")


def validate_stored_address(value: str, name: str) -> None:
    validate_text(value, name)
    if len(value) > 256:
        raise ValueError(f"{name} is too long")


def classify_stored_address(value: str) -> str:
    return "CANONICAL" if value in WORKSTREAMS else "LEGACY"


def nullable(value: Any) -> str | None:
    return None if value is None else str(value)
