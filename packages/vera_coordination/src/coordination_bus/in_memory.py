"""Deterministic append-only repository for tests and local evaluation."""

from .contracts import (
    CoordinationEvent, CoordinationEventDraft, canonical_hash, canonicalize,
)


class InMemoryCoordinationRepository:
    def __init__(self) -> None:
        self._events: list[CoordinationEvent] = []

    def append(self, draft: CoordinationEventDraft) -> CoordinationEvent:
        draft.validate()
        sequence = len(self._events) + 1
        event_id = canonical_hash({
            "schema": "VERA_COORDINATION_EVENT_ID_V1", "sequence": sequence,
            **draft.canonical_dict(),
        })[:32]
        event = CoordinationEvent(
            event_id=event_id, event_sequence=sequence,
            thread_key=draft.thread_key, source_branch=draft.source_branch,
            target_branch=draft.target_branch, event_type=draft.event_type,
            status=draft.status, objective=draft.objective, summary=draft.summary,
            active_issue=draft.active_issue,
            requested_perspective=draft.requested_perspective,
            supersedes_event_id=draft.supersedes_event_id,
            acknowledges_event_id=draft.acknowledges_event_id,
            payload=canonicalize(draft.payload),
            reference_data=canonicalize(draft.reference_data),
            record_time=f"2026-07-30T21:13:{sequence:02d}+00:00",
        )
        self._events.append(event)
        return event

    def get(self, event_id: str) -> CoordinationEvent | None:
        return next((event for event in self._events if event.event_id == event_id), None)

    def list_thread(self, thread_key: str) -> tuple[CoordinationEvent, ...]:
        return tuple(event for event in self._events if event.thread_key == thread_key)

    def read_inbox(
        self, target_branch: str, *, after_sequence: int = 0, limit: int = 100,
        include_acknowledged: bool = False,
    ) -> tuple[CoordinationEvent, ...]:
        acknowledged_or_responded = {
            event.acknowledges_event_id for event in self._events
            if event.source_branch == target_branch and event.acknowledges_event_id
        }
        events = [
            event for event in self._events
            if event.target_branch == target_branch
            and event.event_sequence > after_sequence
            and (include_acknowledged or event.event_id not in acknowledged_or_responded)
        ]
        return tuple(sorted(events, key=lambda item: item.event_sequence)[:limit])
