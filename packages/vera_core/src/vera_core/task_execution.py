from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any, Mapping, Sequence

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)


class TaskExecutionError(ValueError):
    pass


CLOSEOUT_SURFACES = (
    "source",
    "build/package",
    "install/registration",
    "current route",
    "runtime consumption",
    "behavior/effect",
    "docs/rules",
    "memory/privacy",
    "workspace/coordination",
)

CLOSEOUT_STATES = frozenset(
    {
        "verified-current",
        "changed-and-verified",
        "pending",
        "out-of-scope",
        "not-applicable",
    }
)


def _require_text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise TaskExecutionError(f"{label} must be a non-empty exact string")
    return value


def _require_texts(values: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TaskExecutionError(f"{label} must be a sequence of strings")
    result = tuple(_require_text(value, f"{label}[]") for value in values)
    return result


@dataclass(frozen=True, slots=True)
class TaskPacket:
    purpose: str
    subject: str
    completion_state: str
    evidence_requirements: tuple[str, ...]
    writable_scope: tuple[str, ...]
    non_targets: tuple[str, ...]
    forbidden_shortcuts_or_effects: tuple[str, ...]
    priority_order: tuple[str, ...]
    unknowns: tuple[str, ...]
    return_shape: tuple[str, ...]
    relevant_surfaces: tuple[str, ...]

    def validate(self) -> None:
        _require_text(self.purpose, "purpose")
        _require_text(self.subject, "subject")
        _require_text(self.completion_state, "completion_state")
        _require_texts(self.evidence_requirements, "evidence_requirements")
        _require_texts(self.writable_scope, "writable_scope")
        _require_texts(self.non_targets, "non_targets")
        _require_texts(
            self.forbidden_shortcuts_or_effects,
            "forbidden_shortcuts_or_effects",
        )
        _require_texts(self.priority_order, "priority_order")
        _require_texts(self.unknowns, "unknowns")
        _require_texts(self.return_shape, "return_shape")
        surfaces = _require_texts(
            self.relevant_surfaces,
            "relevant_surfaces",
        )
        if not surfaces:
            raise TaskExecutionError(
                "substantial task packet must declare relevant closeout surfaces"
            )
        if len(set(surfaces)) != len(surfaces):
            raise TaskExecutionError("relevant_surfaces contains duplicates")
        unknown = sorted(set(surfaces) - set(CLOSEOUT_SURFACES))
        if unknown:
            raise TaskExecutionError(
                "unknown closeout surfaces: " + ", ".join(unknown)
            )

    def canonical_body(self) -> dict[str, Any]:
        self.validate()
        return {
            "purpose": self.purpose,
            "subject": self.subject,
            "completion_state": self.completion_state,
            "evidence_requirements": list(self.evidence_requirements),
            "writable_scope": list(self.writable_scope),
            "non_targets": list(self.non_targets),
            "forbidden_shortcuts_or_effects": list(
                self.forbidden_shortcuts_or_effects
            ),
            "priority_order": list(self.priority_order),
            "unknowns": list(self.unknowns),
            "return_shape": list(self.return_shape),
            "relevant_surfaces": list(self.relevant_surfaces),
        }

    @property
    def packet_digest(self) -> str:
        return sha256_hex(canonical_json_bytes(self.canonical_body()))


@dataclass(frozen=True, slots=True)
class TaskEvent:
    sequence: int
    event_id: str
    task_id: str
    event_type: str
    predecessor_digest: str
    event_digest: str
    payload: Mapping[str, Any]


TASK_DEPENDENCY_KINDS = frozenset(
    {
        "EFFECT",
        "COORDINATION_COMMAND",
        "PROVIDER_EFFECT",
    }
)


@dataclass(frozen=True, slots=True)
class TaskDependency:
    dependency_id: str
    kind: str
    target_id: str
    event_digest: str


@dataclass(frozen=True, slots=True)
class TaskCorrection:
    correction_id: str
    summary: str
    obsolete_route: str
    required_change: str
    current_owner_ref: str
    provenance_refs: tuple[str, ...]
    event_digest: str


@dataclass(frozen=True, slots=True)
class TaskCloseout:
    closeout_id: str
    surfaces: Mapping[str, str]
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]
    claim_ceiling: str
    next_frontier: str
    lifecycle_evidence_digest: str
    event_digest: str


@dataclass(frozen=True, slots=True)
class TaskCloseoutAssessment:
    task_id: str
    lifecycle_status: str
    surfaces_ready: bool
    unresolved_effect_ids: tuple[str, ...]
    coordination_recovery_ids: tuple[str, ...]
    provider_recovery_ids: tuple[str, ...]
    unresolved_correction_ids: tuple[str, ...]
    supplied_blockers: tuple[str, ...]
    ready: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskState:
    task_id: str
    packet: TaskPacket
    opened_lifecycle_evidence_digest: str
    latest_checkpoint: Mapping[str, Any] | None
    dependencies: tuple[TaskDependency, ...]
    corrections: tuple[TaskCorrection, ...]
    unresolved_correction_ids: tuple[str, ...]
    closeout: TaskCloseout | None
    journal_head_digest: str

    @property
    def closed(self) -> bool:
        return self.closeout is not None


class TaskExecutionLedger:
    """Durable event-sourced task packets, checkpoints, and closeout truth.

    The ledger records local task evidence only. It does not grant repository,
    provider, installation, publication, or other protected authority.
    """

    GENESIS_HEAD = sha256_hex(b"vera-mono-task-execution-genesis-v1")
    EVENT_TYPES = frozenset(
        {
            "TASK_OPENED",
            "TASK_DEPENDENCY",
            "TASK_CORRECTION",
            "TASK_CHECKPOINT",
            "TASK_CLOSED",
        }
    )

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    predecessor_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                """
            )
            if db.execute(
                "SELECT 1 FROM meta WHERE key='sequence'"
            ).fetchone() is None:
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('sequence','0')"
                )
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('head',?)",
                    (self.GENESIS_HEAD,),
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, str]:
        sequence = int(
            db.execute(
                "SELECT value FROM meta WHERE key='sequence'"
            ).fetchone()[0]
        )
        head = str(
            db.execute(
                "SELECT value FROM meta WHERE key='head'"
            ).fetchone()[0]
        )
        return sequence, head

    @property
    def head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    def append(
        self,
        *,
        event_id: str,
        task_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> TaskEvent:
        _require_text(event_id, "event_id")
        _require_text(task_id, "task_id")
        if event_type not in self.EVENT_TYPES:
            raise TaskExecutionError(
                f"unsupported task event type: {event_type}"
            )
        if not isinstance(payload, Mapping):
            raise TaskExecutionError("task event payload must be a mapping")
        payload_json = canonical_json(dict(payload))

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT * FROM events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if replay is not None:
                existing = self._row(replay)
                if (
                    existing.task_id != task_id
                    or existing.event_type != event_type
                    or canonical_json(dict(existing.payload)) != payload_json
                ):
                    raise TaskExecutionError(
                        "task event id replay carries different evidence"
                    )
                db.commit()
                return existing

            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            body = {
                "schema": "VERA_MONO_TASK_EXECUTION_EVENT_V1",
                "sequence": next_sequence,
                "event_id": event_id,
                "task_id": task_id,
                "event_type": event_type,
                "predecessor_digest": predecessor,
                "payload": dict(payload),
            }
            digest = sha256_hex(canonical_json_bytes(body))
            db.execute(
                """
                INSERT INTO events(
                    sequence,event_id,task_id,event_type,
                    predecessor_digest,event_digest,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    event_id,
                    task_id,
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
            db.execute(
                "UPDATE meta SET value=? WHERE key='head'",
                (digest,),
            )
            db.commit()
            return TaskEvent(
                sequence=next_sequence,
                event_id=event_id,
                task_id=task_id,
                event_type=event_type,
                predecessor_digest=predecessor,
                event_digest=digest,
                payload=dict(payload),
            )

    def open_task(
        self,
        task_id: str,
        packet: TaskPacket,
        *,
        lifecycle_evidence_digest: str,
    ) -> TaskState:
        packet.validate()
        _require_text(task_id, "task_id")
        self._require_digest(
            lifecycle_evidence_digest,
            "lifecycle_evidence_digest",
        )
        existing = self.events(task_id)
        if existing and existing[0].event_type != "TASK_OPENED":
            raise TaskExecutionError(
                "task history does not begin with TASK_OPENED"
            )
        self.append(
            event_id=f"{task_id}:OPEN",
            task_id=task_id,
            event_type="TASK_OPENED",
            payload={
                "schema": "VERA_MONO_TASK_PACKET_V1",
                "packet": packet.canonical_body(),
                "packet_digest": packet.packet_digest,
                "lifecycle_evidence_digest": lifecycle_evidence_digest,
            },
        )
        return self.read(task_id)

    def record_dependency(
        self,
        task_id: str,
        dependency_id: str,
        *,
        kind: str,
        target_id: str,
    ) -> TaskState:
        state = self.read(task_id)
        if state.closed:
            raise TaskExecutionError(
                "closed task cannot accept dependency binding"
            )
        dependency_id = _require_text(dependency_id, "dependency_id")
        kind = _require_text(kind, "dependency kind")
        target_id = _require_text(target_id, "dependency target_id")
        if kind not in TASK_DEPENDENCY_KINDS:
            raise TaskExecutionError(
                f"unsupported task dependency kind: {kind}"
            )
        self.append(
            event_id=f"{task_id}:DEPENDENCY:{dependency_id}",
            task_id=task_id,
            event_type="TASK_DEPENDENCY",
            payload={
                "schema": "VERA_MONO_TASK_DEPENDENCY_V1",
                "dependency_id": dependency_id,
                "subject": state.packet.subject,
                "packet_digest": state.packet.packet_digest,
                "kind": kind,
                "target_id": target_id,
            },
        )
        return self.read(task_id)

    def record_correction(
        self,
        task_id: str,
        correction_id: str,
        *,
        summary: str,
        obsolete_route: str,
        required_change: str,
        current_owner_ref: str,
        provenance_refs: Sequence[str],
    ) -> TaskState:
        state = self.read(task_id)
        if state.closed:
            raise TaskExecutionError(
                "closed task cannot accept correction"
            )
        _require_text(correction_id, "correction_id")
        _require_text(summary, "summary")
        _require_text(obsolete_route, "obsolete_route")
        _require_text(required_change, "required_change")
        _require_text(current_owner_ref, "current_owner_ref")
        refs = _require_texts(provenance_refs, "provenance_refs")
        if not refs:
            raise TaskExecutionError(
                "correction lineage requires provenance_refs"
            )
        self.append(
            event_id=f"{task_id}:CORRECTION:{correction_id}",
            task_id=task_id,
            event_type="TASK_CORRECTION",
            payload={
                "schema": "VERA_MONO_TASK_CORRECTION_V1",
                "correction_id": correction_id,
                "subject": state.packet.subject,
                "packet_digest": state.packet.packet_digest,
                "summary": summary,
                "obsolete_route": obsolete_route,
                "required_change": required_change,
                "current_owner_ref": current_owner_ref,
                "provenance_refs": list(refs),
            },
        )
        return self.read(task_id)

    def checkpoint(
        self,
        task_id: str,
        checkpoint_id: str,
        *,
        completed_evidence: Sequence[str],
        blockers: Sequence[str],
        protected_effects_still_gated: Sequence[str],
        next_frontier: str,
        lifecycle_evidence_digest: str,
        correction_ids_addressed: Sequence[str] = (),
        method_change: str | None = None,
        regression_guard: str | None = None,
        blocker_classification: str | None = None,
    ) -> TaskState:
        state = self.read(task_id)
        if state.closed:
            raise TaskExecutionError("closed task cannot accept checkpoint")
        _require_text(checkpoint_id, "checkpoint_id")
        _require_text(next_frontier, "next_frontier")
        self._require_digest(
            lifecycle_evidence_digest,
            "lifecycle_evidence_digest",
        )
        addressed = _require_texts(
            correction_ids_addressed,
            "correction_ids_addressed",
        )
        unresolved = set(state.unresolved_correction_ids)
        addressed_set = set(addressed)
        if addressed_set - unresolved:
            raise TaskExecutionError(
                "checkpoint addresses correction that is not unresolved"
            )
        if unresolved and addressed_set != unresolved:
            raise TaskExecutionError(
                "next checkpoint after correction must address all unresolved corrections"
            )
        normalized_response = {
            "method_change": (
                None
                if method_change is None
                else _require_text(method_change, "method_change")
            ),
            "regression_guard": (
                None
                if regression_guard is None
                else _require_text(regression_guard, "regression_guard")
            ),
            "blocker_classification": (
                None
                if blocker_classification is None
                else _require_text(
                    blocker_classification,
                    "blocker_classification",
                )
            ),
        }
        if addressed and not any(normalized_response.values()):
            raise TaskExecutionError(
                "correction recurrence requires method change, regression guard, or blocker classification"
            )
        self.append(
            event_id=f"{task_id}:CHECKPOINT:{checkpoint_id}",
            task_id=task_id,
            event_type="TASK_CHECKPOINT",
            payload={
                "schema": "VERA_MONO_TASK_CHECKPOINT_V1",
                "subject": state.packet.subject,
                "subject_digest": sha256_hex(
                    canonical_json_bytes(state.packet.subject)
                ),
                "completed_evidence": list(
                    _require_texts(
                        completed_evidence,
                        "completed_evidence",
                    )
                ),
                "blockers": list(_require_texts(blockers, "blockers")),
                "protected_effects_still_gated": list(
                    _require_texts(
                        protected_effects_still_gated,
                        "protected_effects_still_gated",
                    )
                ),
                "next_frontier": next_frontier,
                "correction_ids_addressed": list(addressed),
                "method_change": normalized_response["method_change"],
                "regression_guard": normalized_response["regression_guard"],
                "blocker_classification": normalized_response[
                    "blocker_classification"
                ],
                "lifecycle_evidence_digest": lifecycle_evidence_digest,
            },
        )
        return self.read(task_id)

    def close_task(
        self,
        task_id: str,
        closeout_id: str,
        *,
        surfaces: Mapping[str, str],
        evidence_refs: Sequence[str],
        blockers: Sequence[str],
        claim_ceiling: str,
        next_frontier: str,
        lifecycle_evidence_digest: str,
    ) -> TaskState:
        state = self.read(task_id)
        if state.closed:
            raise TaskExecutionError("task is already closed")
        if state.unresolved_correction_ids:
            raise TaskExecutionError(
                "task has unresolved correction recurrence gate: "
                + ", ".join(state.unresolved_correction_ids)
            )
        _require_text(closeout_id, "closeout_id")
        _require_text(claim_ceiling, "claim_ceiling")
        _require_text(next_frontier, "next_frontier")
        self._require_digest(
            lifecycle_evidence_digest,
            "lifecycle_evidence_digest",
        )
        evidence = _require_texts(evidence_refs, "evidence_refs")
        if not evidence:
            raise TaskExecutionError(
                "task closeout requires executed/readback evidence"
            )
        unresolved = _require_texts(blockers, "blockers")
        if unresolved:
            raise TaskExecutionError(
                "task with unresolved blockers cannot be closed"
            )
        normalized = self._validate_surfaces(
            state.packet,
            surfaces,
        )
        self.append(
            event_id=f"{task_id}:CLOSE:{closeout_id}",
            task_id=task_id,
            event_type="TASK_CLOSED",
            payload={
                "schema": "VERA_MONO_TASK_CLOSEOUT_V1",
                "surfaces": normalized,
                "evidence_refs": list(evidence),
                "blockers": [],
                "claim_ceiling": claim_ceiling,
                "next_frontier": next_frontier,
                "lifecycle_evidence_digest": lifecycle_evidence_digest,
            },
        )
        return self.read(task_id)

    @staticmethod
    def _validate_surfaces(
        packet: TaskPacket,
        surfaces: Mapping[str, str],
    ) -> dict[str, str]:
        if not isinstance(surfaces, Mapping):
            raise TaskExecutionError("surfaces must be a mapping")
        expected = set(packet.relevant_surfaces)
        observed = set(surfaces)
        if observed != expected:
            missing = sorted(expected - observed)
            extra = sorted(observed - expected)
            raise TaskExecutionError(
                "closeout surfaces do not match task packet; "
                f"missing={missing}, extra={extra}"
            )
        normalized: dict[str, str] = {}
        for surface in packet.relevant_surfaces:
            status = surfaces[surface]
            if status not in CLOSEOUT_STATES:
                raise TaskExecutionError(
                    f"invalid closeout state for {surface}: {status!r}"
                )
            if status == "pending":
                raise TaskExecutionError(
                    f"relevant closeout surface remains pending: {surface}"
                )
            normalized[surface] = status
        return normalized

    def read(self, task_id: str) -> TaskState:
        events = self.events(task_id)
        if not events:
            raise KeyError(task_id)
        opened = events[0]
        if opened.event_type != "TASK_OPENED":
            raise TaskExecutionError(
                "task history does not begin with TASK_OPENED"
            )
        raw_packet = opened.payload.get("packet")
        if not isinstance(raw_packet, dict):
            raise TaskExecutionError("task packet payload is missing")
        packet = TaskPacket(
            purpose=raw_packet["purpose"],
            subject=raw_packet["subject"],
            completion_state=raw_packet["completion_state"],
            evidence_requirements=tuple(
                raw_packet["evidence_requirements"]
            ),
            writable_scope=tuple(raw_packet["writable_scope"]),
            non_targets=tuple(raw_packet["non_targets"]),
            forbidden_shortcuts_or_effects=tuple(
                raw_packet["forbidden_shortcuts_or_effects"]
            ),
            priority_order=tuple(raw_packet["priority_order"]),
            unknowns=tuple(raw_packet["unknowns"]),
            return_shape=tuple(raw_packet["return_shape"]),
            relevant_surfaces=tuple(raw_packet["relevant_surfaces"]),
        )
        packet.validate()
        if opened.payload.get("packet_digest") != packet.packet_digest:
            raise TaskExecutionError("task packet digest mismatch")
        opened_lifecycle = self._require_digest(
            opened.payload.get("lifecycle_evidence_digest"),
            "opened lifecycle evidence digest",
        )

        latest_checkpoint: Mapping[str, Any] | None = None
        dependencies: list[TaskDependency] = []
        corrections: list[TaskCorrection] = []
        unresolved_corrections: set[str] = set()
        closeout: TaskCloseout | None = None
        for event in events[1:]:
            if closeout is not None:
                raise TaskExecutionError(
                    "task history continues after TASK_CLOSED"
                )
            if event.event_type == "TASK_DEPENDENCY":
                dependency_id = _require_text(
                    event.payload.get("dependency_id"),
                    "dependency_id",
                )
                if event.payload.get("subject") != packet.subject:
                    raise TaskExecutionError(
                        "dependency subject diverges from task packet"
                    )
                if event.payload.get("packet_digest") != packet.packet_digest:
                    raise TaskExecutionError(
                        "dependency packet digest mismatch"
                    )
                kind = _require_text(
                    event.payload.get("kind"),
                    "dependency kind",
                )
                if kind not in TASK_DEPENDENCY_KINDS:
                    raise TaskExecutionError(
                        f"persisted unsupported task dependency kind: {kind}"
                    )
                target_id = _require_text(
                    event.payload.get("target_id"),
                    "dependency target_id",
                )
                if dependency_id in {
                    item.dependency_id for item in dependencies
                }:
                    raise TaskExecutionError(
                        "duplicate dependency identity in task history"
                    )
                dependencies.append(
                    TaskDependency(
                        dependency_id=dependency_id,
                        kind=kind,
                        target_id=target_id,
                        event_digest=event.event_digest,
                    )
                )
            elif event.event_type == "TASK_CORRECTION":
                correction_id = _require_text(
                    event.payload.get("correction_id"),
                    "correction_id",
                )
                if event.payload.get("subject") != packet.subject:
                    raise TaskExecutionError(
                        "correction subject diverges from task packet"
                    )
                if event.payload.get("packet_digest") != packet.packet_digest:
                    raise TaskExecutionError(
                        "correction packet digest mismatch"
                    )
                correction = TaskCorrection(
                    correction_id=correction_id,
                    summary=_require_text(
                        event.payload.get("summary"),
                        "correction summary",
                    ),
                    obsolete_route=_require_text(
                        event.payload.get("obsolete_route"),
                        "obsolete_route",
                    ),
                    required_change=_require_text(
                        event.payload.get("required_change"),
                        "required_change",
                    ),
                    current_owner_ref=_require_text(
                        event.payload.get("current_owner_ref"),
                        "current_owner_ref",
                    ),
                    provenance_refs=_require_texts(
                        event.payload.get("provenance_refs", ()),
                        "provenance_refs",
                    ),
                    event_digest=event.event_digest,
                )
                if not correction.provenance_refs:
                    raise TaskExecutionError(
                        "persisted correction lacks provenance refs"
                    )
                if correction_id in {
                    item.correction_id for item in corrections
                }:
                    raise TaskExecutionError(
                        "duplicate correction identity in task history"
                    )
                corrections.append(correction)
                unresolved_corrections.add(correction_id)
            elif event.event_type == "TASK_CHECKPOINT":
                addressed = set(
                    _require_texts(
                        event.payload.get(
                            "correction_ids_addressed",
                            (),
                        ),
                        "correction_ids_addressed",
                    )
                )
                if addressed - unresolved_corrections:
                    raise TaskExecutionError(
                        "checkpoint addresses non-unresolved correction"
                    )
                if unresolved_corrections and addressed != unresolved_corrections:
                    raise TaskExecutionError(
                        "checkpoint failed correction recurrence gate"
                    )
                if addressed:
                    response = (
                        event.payload.get("method_change"),
                        event.payload.get("regression_guard"),
                        event.payload.get("blocker_classification"),
                    )
                    if not any(
                        isinstance(value, str) and value.strip()
                        for value in response
                    ):
                        raise TaskExecutionError(
                            "checkpoint correction response is missing changed method, regression guard, or blocker classification"
                        )
                    unresolved_corrections.difference_update(addressed)
                latest_checkpoint = dict(event.payload)
            elif event.event_type == "TASK_CLOSED":
                surfaces = self._validate_surfaces(
                    packet,
                    event.payload["surfaces"],
                )
                blockers = tuple(event.payload.get("blockers", ()))
                if blockers:
                    raise TaskExecutionError(
                        "persisted closed task contains blockers"
                    )
                closeout = TaskCloseout(
                    closeout_id=event.event_id.split(":CLOSE:", 1)[-1],
                    surfaces=surfaces,
                    evidence_refs=tuple(event.payload["evidence_refs"]),
                    blockers=blockers,
                    claim_ceiling=event.payload["claim_ceiling"],
                    next_frontier=event.payload["next_frontier"],
                    lifecycle_evidence_digest=self._require_digest(
                        event.payload["lifecycle_evidence_digest"],
                        "closeout lifecycle evidence digest",
                    ),
                    event_digest=event.event_digest,
                )
            else:
                raise TaskExecutionError(
                    f"unexpected task event type: {event.event_type}"
                )
        return TaskState(
            task_id=task_id,
            packet=packet,
            opened_lifecycle_evidence_digest=opened_lifecycle,
            latest_checkpoint=latest_checkpoint,
            dependencies=tuple(dependencies),
            corrections=tuple(corrections),
            unresolved_correction_ids=tuple(
                sorted(unresolved_corrections)
            ),
            closeout=closeout,
            journal_head_digest=self.verify_chain(),
        )

    def tasks(self) -> tuple[TaskState, ...]:
        self.verify_chain()
        with self._connect() as db:
            rows = db.execute(
                "SELECT DISTINCT task_id FROM events ORDER BY task_id"
            ).fetchall()
        return tuple(self.read(str(row[0])) for row in rows)

    def events(self, task_id: str | None = None) -> tuple[TaskEvent, ...]:
        with self._connect() as db:
            if task_id is None:
                rows = db.execute(
                    "SELECT * FROM events ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM events
                    WHERE task_id=?
                    ORDER BY sequence
                    """,
                    (task_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM events ORDER BY sequence"
            ).fetchall()
            meta_sequence, meta_head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        closed: set[str] = set()
        opened: set[str] = set()
        for row in rows:
            event = self._row(row)
            if event.sequence != expected_sequence:
                raise TaskExecutionError("task journal sequence gap")
            if event.predecessor_digest != predecessor:
                raise TaskExecutionError(
                    "task journal predecessor digest mismatch"
                )
            if event.event_type not in self.EVENT_TYPES:
                raise TaskExecutionError(
                    "task journal contains unsupported event type"
                )
            if event.task_id in closed:
                raise TaskExecutionError(
                    "task journal contains event after closeout"
                )
            if event.event_type == "TASK_OPENED":
                if event.task_id in opened:
                    raise TaskExecutionError(
                        "task contains multiple open events"
                    )
                opened.add(event.task_id)
            elif event.task_id not in opened:
                raise TaskExecutionError(
                    "task event appears before TASK_OPENED"
                )
            if event.event_type == "TASK_CLOSED":
                closed.add(event.task_id)

            body = {
                "schema": "VERA_MONO_TASK_EXECUTION_EVENT_V1",
                "sequence": event.sequence,
                "event_id": event.event_id,
                "task_id": event.task_id,
                "event_type": event.event_type,
                "predecessor_digest": event.predecessor_digest,
                "payload": dict(event.payload),
            }
            observed = sha256_hex(canonical_json_bytes(body))
            if observed != event.event_digest:
                raise TaskExecutionError(
                    "task journal event digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1

        if meta_sequence != expected_sequence - 1:
            raise TaskExecutionError(
                "task journal meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if meta_head != expected_head:
            raise TaskExecutionError("task journal meta head mismatch")
        return expected_head

    def context(self) -> dict[str, Any]:
        states = self.tasks()
        return {
            "schema": "VERA_MONO_TASK_EXECUTION_CONTEXT_V1",
            "journal_head_digest": self.verify_chain(),
            "task_count": len(states),
            "open_task_ids": [
                state.task_id for state in states if not state.closed
            ],
            "tasks_with_dependencies": [
                {
                    "task_id": state.task_id,
                    "dependencies": [
                        {
                            "dependency_id": dependency.dependency_id,
                            "kind": dependency.kind,
                            "target_id": dependency.target_id,
                            "event_digest": dependency.event_digest,
                        }
                        for dependency in state.dependencies
                    ],
                }
                for state in states
                if state.dependencies
            ],
            "tasks_with_unresolved_corrections": [
                {
                    "task_id": state.task_id,
                    "correction_ids": list(
                        state.unresolved_correction_ids
                    ),
                }
                for state in states
                if state.unresolved_correction_ids
            ],
            "closed_task_ids": [
                state.task_id for state in states if state.closed
            ],
        }

    @staticmethod
    def _require_digest(value: Any, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise TaskExecutionError(
                f"{label} must be an exact SHA-256 digest"
            )
        try:
            int(value, 16)
        except ValueError as exc:
            raise TaskExecutionError(
                f"{label} must be hexadecimal"
            ) from exc
        return value.lower()

    @staticmethod
    def _row(row: sqlite3.Row) -> TaskEvent:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise TaskExecutionError(
                "task event payload is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise TaskExecutionError(
                "task event payload must be an object"
            )
        return TaskEvent(
            sequence=int(row["sequence"]),
            event_id=str(row["event_id"]),
            task_id=str(row["task_id"]),
            event_type=str(row["event_type"]),
            predecessor_digest=str(row["predecessor_digest"]),
            event_digest=str(row["event_digest"]),
            payload=payload,
        )
