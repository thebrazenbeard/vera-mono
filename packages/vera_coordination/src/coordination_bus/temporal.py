"""Internal temporal receipt mechanics for the V.E.R.A. coordination bus.

This module is not a public trust boundary. It preserves sequence, checkpoint,
acknowledgement, consumption, event, state, retrieval, and receipt-time
separation while the public verifier contract lives in verified_temporal.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Sequence

from .contracts import (
    ActorContext, CoordinationEvent, CoordinationEventDraft, CoordinationReceipt,
    CoordinationResult, Operation, PERMISSION_ACKNOWLEDGE, PERMISSION_READ_ANY,
    PERMISSION_READ_SELF, PERMISSION_STATUS, ResultClass, canonicalize,
    make_result, validate_text, validate_workstream,
)
from .core import CoordinationBus as _BaseCoordinationBus, _receipted

TEMPORAL_PRECISIONS = frozenset({"EXACT", "BOUNDED", "APPROXIMATE", "UNKNOWN"})
_RECORD_TIME_SOURCES = frozenset({"DATABASE_RECORD_TIME", "COORDINATION_RECORD_TIME"})


def _aware(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset")
    return parsed


@dataclass(frozen=True)
class TemporalEvidence:
    precision: str
    source: str
    verified: bool
    value: str | None = None
    lower_bound: str | None = None
    upper_bound: str | None = None
    reference_id: str | None = None

    @classmethod
    def unknown(cls, source: str = "UNAVAILABLE") -> "TemporalEvidence":
        return cls("UNKNOWN", source, False)

    @classmethod
    def exact(cls, value: str, *, source: str, reference_id: str) -> "TemporalEvidence":
        return cls("EXACT", source, True, value=value, reference_id=reference_id)

    def validate(self, *, role: str) -> None:
        if self.precision not in TEMPORAL_PRECISIONS:
            raise ValueError(f"unsupported temporal precision {self.precision!r}")
        validate_text(self.source, "temporal source")
        if self.source == "MODEL" and self.verified:
            raise ValueError("model output cannot verify temporal evidence")
        if role != "record_time" and self.source in _RECORD_TIME_SOURCES:
            raise ValueError(f"database record_time cannot substitute for {role}")
        if self.precision == "UNKNOWN":
            if self.value is not None or self.lower_bound is not None or self.upper_bound is not None:
                raise ValueError("UNKNOWN temporal evidence forbids timestamps and bounds")
            if self.verified:
                raise ValueError("UNKNOWN temporal evidence may not claim verification")
            return
        if not self.verified:
            raise ValueError(f"{self.precision} temporal evidence must be externally verified")
        validate_text(self.reference_id or "", "temporal reference_id")
        if self.value is None:
            raise ValueError(f"{self.precision} temporal evidence requires value")
        value = _aware(self.value, f"{role}.value")
        if self.precision == "BOUNDED":
            if self.lower_bound is None or self.upper_bound is None:
                raise ValueError("BOUNDED temporal evidence requires both inclusive bounds")
            lower = _aware(self.lower_bound, f"{role}.lower_bound")
            upper = _aware(self.upper_bound, f"{role}.upper_bound")
            if lower > upper or not lower <= value <= upper:
                raise ValueError("BOUNDED temporal evidence has inconsistent bounds")
        elif self.lower_bound is not None or self.upper_bound is not None:
            raise ValueError(f"{self.precision} temporal evidence forbids hard bounds")

    def as_dict(self) -> dict[str, Any]:
        return canonicalize(asdict(self))


def _time(value: TemporalEvidence | None, role: str) -> TemporalEvidence:
    normalized = value or TemporalEvidence.unknown()
    normalized.validate(role=role)
    return normalized


@dataclass(frozen=True)
class TemporalCoordinationReceipt:
    base: CoordinationReceipt
    result_hash: str
    limitations: tuple[str, ...]
    receipt_time: TemporalEvidence
    entry_time: TemporalEvidence
    retrieval_time: TemporalEvidence
    event_time: TemporalEvidence
    state_time: TemporalEvidence
    cursor_in: int | None = None
    cursor_out: int | None = None
    page_limit: int | None = None
    has_more: bool | None = None
    page_complete: bool | None = None
    cursor_committed: bool = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def as_dict(self) -> dict[str, Any]:
        data = self.base.as_dict()
        data.update({
            "result_hash": self.result_hash,
            "limitations": list(self.limitations),
            "receipt_time": self.receipt_time.as_dict(),
            "entry_time": self.entry_time.as_dict(),
            "retrieval_time": self.retrieval_time.as_dict(),
            "event_time": self.event_time.as_dict(),
            "state_time": self.state_time.as_dict(),
            "cursor_in": self.cursor_in,
            "cursor_out": self.cursor_out,
            "page_limit": self.page_limit,
            "has_more": self.has_more,
            "page_complete": self.page_complete,
            "cursor_committed": self.cursor_committed,
        })
        return canonicalize(data)


@dataclass(frozen=True)
class TemporalCoordinationResult:
    receipt: TemporalCoordinationReceipt
    events: tuple[CoordinationEvent, ...] = ()


class _TemporalCoordinationCore(_BaseCoordinationBus):
    """Internal temporal mechanics used only by the verifier-bound public bus."""

    def __init__(
        self,
        repository: Any,
        *,
        receipt_time_provider: Callable[[], TemporalEvidence] | None = None,
    ) -> None:
        super().__init__(repository)
        self._receipt_time_provider = receipt_time_provider

    def _receipt_time(self) -> TemporalEvidence:
        if self._receipt_time_provider is None:
            return TemporalEvidence.unknown("RECEIPT_TIME_UNAVAILABLE")
        try:
            return _time(self._receipt_time_provider(), "receipt_time")
        except (TypeError, ValueError):
            return TemporalEvidence.unknown("INVALID_RECEIPT_TIME_PROVIDER")

    @staticmethod
    def _correct_limitations(limitations: Sequence[str]) -> tuple[str, ...]:
        corrected: list[str] = []
        for item in limitations:
            if item == "Reading does not acknowledge or consume an event.":
                corrected.append("Reading does not acknowledge an event and proves no consumption.")
            elif item == "Target consumption requires an explicit acknowledgement or linked response.":
                corrected.append(
                    "A linked acknowledgement or response proves only that row's persistence; "
                    "consumption_time remains UNKNOWN unless independently evidenced."
                )
            else:
                corrected.append(item)
        return tuple(dict.fromkeys(corrected))

    def _wrap(
        self,
        result: CoordinationResult,
        *,
        entry_time: TemporalEvidence | None = None,
        retrieval_time: TemporalEvidence | None = None,
        event_time: TemporalEvidence | None = None,
        state_time: TemporalEvidence | None = None,
        cursor_in: int | None = None,
        cursor_out: int | None = None,
        page_limit: int | None = None,
        has_more: bool | None = None,
        extra_limitations: Sequence[str] = (),
    ) -> TemporalCoordinationResult:
        entry = _time(entry_time, "entry_time")
        retrieval = _time(retrieval_time, "retrieval_time")
        event = _time(event_time, "event_time")
        state = _time(state_time, "state_time")
        receipt_time = self._receipt_time()
        limitations = self._correct_limitations(
            tuple(result.receipt.limitations) + tuple(extra_limitations)
        )
        deterministic_body = {
            "base_result_hash": result.receipt.result_hash,
            "entry_time": entry.as_dict(),
            "retrieval_time": retrieval.as_dict(),
            "event_time": event.as_dict(),
            "state_time": state.as_dict(),
            "cursor_in": cursor_in,
            "cursor_out": cursor_out,
            "page_limit": page_limit,
            "has_more": has_more,
            "page_complete": None if has_more is None else not has_more,
            "cursor_committed": False,
            "limitations": list(limitations),
        }
        result_hash = sha256(json.dumps(
            deterministic_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")).hexdigest()
        receipt = TemporalCoordinationReceipt(
            base=result.receipt,
            result_hash=result_hash,
            limitations=limitations,
            receipt_time=receipt_time,
            entry_time=entry,
            retrieval_time=retrieval,
            event_time=event,
            state_time=state,
            cursor_in=cursor_in,
            cursor_out=cursor_out,
            page_limit=page_limit,
            has_more=has_more,
            page_complete=None if has_more is None else not has_more,
            cursor_committed=False,
        )
        return TemporalCoordinationResult(receipt=receipt, events=result.events)

    def _append(
        self,
        operation: Operation,
        actor: ActorContext,
        draft: CoordinationEventDraft,
    ) -> TemporalCoordinationResult:
        return self._wrap(super()._append(operation, actor, draft))

    def _failure(
        self,
        operation: Operation,
        actor: ActorContext,
        result_class: ResultClass,
        error: Exception,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
    ) -> TemporalCoordinationResult:
        return self._wrap(
            super()._failure(operation, actor, result_class, error, args, kwargs)
        )

    def _read(
        self,
        operation: Operation,
        actor: ActorContext,
        target_branch: str | None,
        after_sequence: int,
        limit: int,
        include_acknowledged: bool,
    ) -> TemporalCoordinationResult:
        return self._read_temporal(
            operation,
            actor,
            target_branch,
            after_sequence,
            limit,
            include_acknowledged,
            entry_time=None,
            retrieval_time=None,
        )

    def _read_temporal(
        self,
        operation: Operation,
        actor: ActorContext,
        target_branch: str | None,
        after_sequence: int,
        limit: int,
        include_acknowledged: bool,
        *,
        entry_time: TemporalEvidence | None,
        retrieval_time: TemporalEvidence | None,
    ) -> TemporalCoordinationResult:
        actor.validate()
        target = target_branch or actor.canonical_workstream
        validate_workstream(target, "target_branch")
        actor.require(
            PERMISSION_READ_SELF
            if target == actor.canonical_workstream
            else PERMISSION_READ_ANY
        )
        if after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative exclusive high-water mark")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        entry = _time(entry_time, "entry_time")
        retrieval = _time(retrieval_time, "retrieval_time")
        raw = self.repository.read_inbox(
            target,
            after_sequence=after_sequence,
            limit=limit + 1,
            include_acknowledged=include_acknowledged,
        )
        has_more = len(raw) > limit
        events = tuple(raw[:limit])
        cursor_out = events[-1].event_sequence if events else after_sequence
        base = make_result(
            operation,
            "COMPLETE",
            actor,
            events,
            False,
            None,
            target,
            None,
            (
                "Read completion proves only rows returned at this invocation.",
                "Reading does not acknowledge an event and proves no consumption.",
                "Coordination events are not canonical memory records.",
            ),
        )
        return self._wrap(
            base,
            entry_time=entry,
            retrieval_time=retrieval,
            cursor_in=after_sequence,
            cursor_out=cursor_out,
            page_limit=limit,
            has_more=has_more,
            extra_limitations=(
                "cursor_out is an exclusive sequence high-water mark candidate, not a time.",
                "The caller must durably handle the complete returned page before committing cursor_out.",
                "Sequence gaps do not imply missing time, delivery, consumption, or continuous activity.",
            ),
        )

    @_receipted("coordination_entry_checkpoint")
    def entry_checkpoint(
        self,
        actor: ActorContext,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        entry_time: TemporalEvidence | None = None,
        retrieval_time: TemporalEvidence | None = None,
    ) -> TemporalCoordinationResult:
        return self._read_temporal(
            "coordination_entry_checkpoint",
            actor,
            actor.canonical_workstream,
            after_sequence,
            limit,
            False,
            entry_time=entry_time,
            retrieval_time=retrieval_time,
        )

    @_receipted("coordination_acknowledge")
    def coordination_acknowledge(
        self,
        actor: ActorContext,
        *,
        event_id: str,
        summary: str,
        acknowledgement_time: TemporalEvidence | None = None,
        consumption_time: TemporalEvidence | None = None,
        payload: Mapping[str, Any] | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> TemporalCoordinationResult:
        actor.require(PERMISSION_ACKNOWLEDGE)
        original = self._event(event_id)
        self._addressed_target(actor, original)
        acknowledgement = _time(acknowledgement_time, "acknowledgement_time")
        consumption = _time(consumption_time, "consumption_time")
        supplied_payload = dict(payload or {})
        if "temporal" in supplied_payload:
            raise ValueError("payload.temporal is reserved by the coordination contract")
        supplied_payload["temporal"] = {
            "acknowledgement_time": acknowledgement.as_dict(),
            "consumption_time": consumption.as_dict(),
            "record_time_semantics": "DATABASE_PERSISTENCE_TIME_ONLY",
        }
        base = _BaseCoordinationBus._append(
            self,
            "coordination_acknowledge",
            actor,
            CoordinationEventDraft(
                thread_key=original.thread_key,
                source_branch=actor.canonical_workstream,
                target_branch=original.source_branch,
                event_type="ACKNOWLEDGEMENT",
                status="ACKNOWLEDGED",
                objective=original.objective,
                summary=summary,
                acknowledges_event_id=original.event_id,
                payload=supplied_payload,
                reference_data=reference_data or {},
            ),
        )
        return self._wrap(
            base,
            event_time=acknowledgement,
            state_time=consumption,
            extra_limitations=(
                "Acknowledgement record_time proves database persistence only.",
                "Acknowledgement does not prove processing completion or consumption time.",
            ),
        )

    @_receipted("coordination_exit_checkpoint")
    def exit_checkpoint(
        self,
        actor: ActorContext,
        *,
        thread_key: str,
        target_branch: str | None,
        objective: str,
        summary: str,
        material: bool,
        status: str = "IN_PROGRESS",
        active_issue: str | None = None,
        acknowledges_event_id: str | None = None,
        event_time: TemporalEvidence | None = None,
        state_time: TemporalEvidence | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> TemporalCoordinationResult:
        actor.validate()
        event = _time(event_time, "event_time")
        state = _time(state_time, "state_time")
        if not material:
            base = make_result(
                "coordination_exit_checkpoint",
                "COMPLETE",
                actor,
                (),
                False,
                thread_key,
                target_branch,
                None,
                ("No event written because the exit was not material.",),
            )
            return self._wrap(base, event_time=event, state_time=state)
        actor.require(PERMISSION_STATUS)
        base = _BaseCoordinationBus._append(
            self,
            "coordination_exit_checkpoint",
            actor,
            CoordinationEventDraft(
                thread_key=thread_key,
                source_branch=actor.canonical_workstream,
                target_branch=target_branch,
                event_type="STATUS",
                status=status,
                objective=objective,
                summary=summary,
                active_issue=active_issue,
                acknowledges_event_id=acknowledges_event_id,
                payload={
                    "temporal": {
                        "event_time": event.as_dict(),
                        "state_time": state.as_dict(),
                        "record_time_semantics": "DATABASE_PERSISTENCE_TIME_ONLY",
                    }
                },
                reference_data=reference_data or {},
            ),
        )
        return self._wrap(
            base,
            event_time=event,
            state_time=state,
            extra_limitations=(
                "The coordination row record_time is not the material transition event_time or state_time.",
            ),
        )
