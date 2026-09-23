"""Receipted coordination operations for V.E.R.A."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Mapping, Sequence, TypeVar, cast

from .contracts import (
    ActorContext, CoordinationEvent, CoordinationEventDraft, CoordinationRepository,
    CoordinationResult, Operation, PERMISSION_ACKNOWLEDGE, PERMISSION_POST,
    PERMISSION_READ_ANY, PERMISSION_READ_SELF, PERMISSION_RESOLVE,
    PERMISSION_REVIEW, PERMISSION_STATUS, RepositoryConflict, ResultClass,
    make_result, validate_text, validate_workstream,
)

F = TypeVar("F", bound=Callable[..., CoordinationResult])


def _receipted(operation: Operation) -> Callable[[F], F]:
    def decorate(function: F) -> F:
        @wraps(function)
        def wrapped(self: "CoordinationBus", actor: ActorContext, *args: Any, **kwargs: Any) -> CoordinationResult:
            try:
                return function(self, actor, *args, **kwargs)
            except PermissionError as exc:
                return self._failure(operation, actor, "DENIED", exc, args, kwargs)
            except (TypeError, ValueError) as exc:
                return self._failure(operation, actor, "INVALID", exc, args, kwargs)
            except RepositoryConflict as exc:
                return self._failure(operation, actor, "CONFLICT", exc, args, kwargs)
            except LookupError as exc:
                return self._failure(operation, actor, "NOT_FOUND", exc, args, kwargs)
            except RuntimeError as exc:
                return self._failure(operation, actor, "CONFLICT", exc, args, kwargs)
        return cast(F, wrapped)
    return decorate


class CoordinationBus:
    def __init__(self, repository: CoordinationRepository) -> None:
        self.repository = repository

    @_receipted("coordination_read_inbox")
    def coordination_read_inbox(
        self, actor: ActorContext, *, target_branch: str | None = None,
        after_sequence: int = 0, limit: int = 100,
        include_acknowledged: bool = False,
    ) -> CoordinationResult:
        return self._read(
            "coordination_read_inbox", actor, target_branch, after_sequence,
            limit, include_acknowledged,
        )

    @_receipted("coordination_post")
    def coordination_post(
        self, actor: ActorContext, draft: CoordinationEventDraft
    ) -> CoordinationResult:
        self._authorize_generic_post(actor, draft)
        return self._append("coordination_post", actor, draft)

    @_receipted("coordination_acknowledge")
    def coordination_acknowledge(
        self, actor: ActorContext, *, event_id: str, summary: str,
        payload: Mapping[str, Any] | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> CoordinationResult:
        actor.require(PERMISSION_ACKNOWLEDGE)
        original = self._event(event_id)
        self._addressed_target(actor, original)
        return self._append(
            "coordination_acknowledge", actor,
            CoordinationEventDraft(
                thread_key=original.thread_key,
                source_branch=actor.canonical_workstream,
                target_branch=original.source_branch,
                event_type="ACKNOWLEDGEMENT",
                status="ACKNOWLEDGED",
                objective=original.objective,
                summary=summary,
                acknowledges_event_id=original.event_id,
                payload=payload or {},
                reference_data=reference_data or {},
            ),
        )

    @_receipted("coordination_publish_status")
    def coordination_publish_status(
        self, actor: ActorContext, *, thread_key: str,
        target_branch: str | None, status: str, objective: str, summary: str,
        active_issue: str | None = None,
        acknowledges_event_id: str | None = None,
        supersedes_event_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> CoordinationResult:
        actor.require(PERMISSION_STATUS)
        return self._append(
            "coordination_publish_status", actor,
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
                supersedes_event_id=supersedes_event_id,
                payload=payload or {},
                reference_data=reference_data or {},
            ),
        )

    @_receipted("coordination_request_review")
    def coordination_request_review(
        self, actor: ActorContext, *, thread_key: str, target_branch: str,
        objective: str, summary: str, requested_perspective: str,
        acknowledges_event_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> CoordinationResult:
        actor.require(PERMISSION_REVIEW)
        validate_text(requested_perspective, "requested_perspective")
        return self._append(
            "coordination_request_review", actor,
            CoordinationEventDraft(
                thread_key=thread_key,
                source_branch=actor.canonical_workstream,
                target_branch=target_branch,
                event_type="STATUS",
                status="READY_FOR_REVIEW",
                objective=objective,
                summary=summary,
                requested_perspective=requested_perspective,
                acknowledges_event_id=acknowledges_event_id,
                payload=payload or {},
                reference_data=reference_data or {},
            ),
        )

    @_receipted("coordination_resolve_thread")
    def coordination_resolve_thread(
        self, actor: ActorContext, *, acknowledges_event_id: str, summary: str,
        payload: Mapping[str, Any] | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> CoordinationResult:
        actor.require(PERMISSION_RESOLVE)
        original = self._event(acknowledges_event_id)
        if actor.canonical_workstream not in {original.source_branch, original.target_branch}:
            raise PermissionError("only a participant may resolve the thread")
        target = (
            original.source_branch
            if actor.canonical_workstream != original.source_branch
            else original.target_branch
        )
        return self._append(
            "coordination_resolve_thread", actor,
            CoordinationEventDraft(
                thread_key=original.thread_key,
                source_branch=actor.canonical_workstream,
                target_branch=target,
                event_type="RESOLUTION",
                status="RESOLVED",
                objective=original.objective,
                summary=summary,
                acknowledges_event_id=original.event_id,
                payload=payload or {},
                reference_data=reference_data or {},
            ),
        )

    @_receipted("coordination_entry_checkpoint")
    def entry_checkpoint(
        self, actor: ActorContext, *, after_sequence: int = 0, limit: int = 100
    ) -> CoordinationResult:
        return self._read(
            "coordination_entry_checkpoint", actor,
            actor.canonical_workstream, after_sequence, limit, False,
        )

    @_receipted("coordination_exit_checkpoint")
    def exit_checkpoint(
        self, actor: ActorContext, *, thread_key: str,
        target_branch: str | None, objective: str, summary: str, material: bool,
        status: str = "IN_PROGRESS", active_issue: str | None = None,
        acknowledges_event_id: str | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> CoordinationResult:
        actor.validate()
        if not material:
            return make_result(
                "coordination_exit_checkpoint", "COMPLETE", actor, (), False,
                thread_key, target_branch, None,
                ("No event written because the exit was not material.",),
            )
        actor.require(PERMISSION_STATUS)
        return self._append(
            "coordination_exit_checkpoint", actor,
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
                reference_data=reference_data or {},
            ),
        )

    def _read(
        self, operation: Operation, actor: ActorContext,
        target_branch: str | None, after_sequence: int, limit: int,
        include_acknowledged: bool,
    ) -> CoordinationResult:
        actor.validate()
        target = target_branch or actor.canonical_workstream
        validate_workstream(target, "target_branch")
        actor.require(
            PERMISSION_READ_SELF
            if target == actor.canonical_workstream
            else PERMISSION_READ_ANY
        )
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        events = self.repository.read_inbox(
            target,
            after_sequence=after_sequence,
            limit=limit,
            include_acknowledged=include_acknowledged,
        )
        return make_result(
            operation, "COMPLETE", actor, events, False, None, target, None,
            (
                "Read completion proves only rows returned at this invocation.",
                "Reading does not acknowledge or consume an event.",
                "Coordination events are not canonical memory records.",
            ),
        )

    def _append(
        self, operation: Operation, actor: ActorContext,
        draft: CoordinationEventDraft,
    ) -> CoordinationResult:
        actor.validate()
        draft.validate()
        if draft.source_branch != actor.canonical_workstream:
            raise PermissionError("source_branch must equal actor workstream")
        self._lineage(draft)
        event = self.repository.append(draft)
        return make_result(
            operation, "COMPLETE", actor, (event,), True, event.thread_key,
            event.target_branch, event.acknowledges_event_id,
            (
                "Confirmed write proves persistence of this event only.",
                "Target consumption requires an explicit acknowledgement or linked response.",
                "Coordination events are not canonical memory records.",
                "Exactly-once delivery is not claimed; retry idempotency remains a runtime/storage gate.",
            ),
        )

    def _authorize_generic_post(
        self, actor: ActorContext, draft: CoordinationEventDraft
    ) -> None:
        draft.validate()
        if draft.event_type == "ACKNOWLEDGEMENT":
            actor.require(PERMISSION_ACKNOWLEDGE)
            original = self._event(draft.acknowledges_event_id or "")
            self._addressed_target(actor, original)
            if draft.target_branch != original.source_branch:
                raise PermissionError("acknowledgement target must be original source")
            return
        if draft.event_type == "REVIEW":
            actor.require(PERMISSION_REVIEW)
            original = self._event(draft.acknowledges_event_id or "")
            self._addressed_target(actor, original)
            if draft.target_branch != original.source_branch:
                raise PermissionError("review target must be original source")
            return
        if draft.event_type == "RESOLUTION":
            actor.require(PERMISSION_RESOLVE)
            original = self._event(draft.acknowledges_event_id or "")
            if actor.canonical_workstream not in {original.source_branch, original.target_branch}:
                raise PermissionError("only a participant may resolve the thread")
            target = (
                original.source_branch
                if actor.canonical_workstream != original.source_branch
                else original.target_branch
            )
            if draft.target_branch != target:
                raise PermissionError("resolution target must be other participant")
            return
        if draft.event_type == "DECISION":
            raise PermissionError(
                "DECISION requires an externally verified decision-authority capability"
            )
        actor.require(PERMISSION_POST)

    def _lineage(self, draft: CoordinationEventDraft) -> None:
        if draft.acknowledges_event_id:
            original = self._event(draft.acknowledges_event_id)
            if original.thread_key != draft.thread_key:
                raise RepositoryConflict("acknowledgement must stay in same thread")
            if original.event_id == draft.supersedes_event_id:
                raise RepositoryConflict("one reference cannot acknowledge and supersede")
        if draft.supersedes_event_id:
            prior = self._event(draft.supersedes_event_id)
            if prior.thread_key != draft.thread_key:
                raise RepositoryConflict("supersession must stay in same thread")
            if any(
                event.supersedes_event_id == prior.event_id
                for event in self.repository.list_thread(draft.thread_key)
            ):
                raise RepositoryConflict("superseded event already has a successor")

    def _event(self, event_id: str) -> CoordinationEvent:
        validate_text(event_id, "event_id")
        event = self.repository.get(event_id)
        if event is None:
            raise LookupError(f"event {event_id!r} not found")
        return event

    @staticmethod
    def _addressed_target(actor: ActorContext, event: CoordinationEvent) -> None:
        if event.target_branch != actor.canonical_workstream:
            raise PermissionError("only addressed target may acknowledge or review")

    def _failure(
        self, operation: Operation, actor: ActorContext, result_class: ResultClass,
        error: Exception, args: Sequence[Any], kwargs: Mapping[str, Any],
    ) -> CoordinationResult:
        draft = next(
            (item for item in args if isinstance(item, CoordinationEventDraft)), None
        )
        thread_key = kwargs.get("thread_key") or (
            None if draft is None else draft.thread_key
        )
        target = kwargs.get("target_branch") or (
            None if draft is None else draft.target_branch
        )
        ack = (
            kwargs.get("event_id") or kwargs.get("acknowledges_event_id")
            or (None if draft is None else draft.acknowledges_event_id)
        )
        return make_result(
            operation, result_class, actor, (), False, thread_key, target, ack,
            ("No database write was confirmed.",), error=str(error),
        )
