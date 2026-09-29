import sqlite3

import pytest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    CoordinationRepositoryCorrupt,
    RepositoryConflict,
    SQLiteCoordinationRepository,
)


MEMORY = ActorContext("workstream/memory", ALL_PERMISSIONS)
TIME = ActorContext("workstream/time", ALL_PERMISSIONS)


def issue_draft(**changes):
    values = {
        "thread_key": "native-coordination-v1",
        "source_branch": "workstream/memory",
        "target_branch": "workstream/time",
        "event_type": "ISSUE",
        "status": "READY_FOR_REVIEW",
        "objective": "Persist native coordination",
        "summary": "SQLite coordination event.",
        "active_issue": "Verify durable coordination.",
        "requested_perspective": "Check restart behavior.",
    }
    values.update(changes)
    return CoordinationEventDraft(**values)


def test_sqlite_coordination_repository_survives_restart(tmp_path):
    path = tmp_path / "coordination.sqlite"
    repo = SQLiteCoordinationRepository(path)
    bus = CoordinationBus(repo)

    written = bus.coordination_post(MEMORY, issue_draft())
    assert written.receipt.database_write_confirmed is True
    event = written.events[0]
    assert repo.event_sequence == 1
    head = repo.head

    reopened = SQLiteCoordinationRepository(path)
    restored = reopened.get(event.event_id)
    assert restored == event
    assert reopened.head == head
    assert reopened.event_sequence == 1
    assert reopened.verify_integrity() == head


def test_sqlite_coordination_acknowledgement_hides_inbox_after_restart(tmp_path):
    path = tmp_path / "coordination.sqlite"
    bus = CoordinationBus(SQLiteCoordinationRepository(path))
    original = bus.coordination_post(MEMORY, issue_draft()).events[0]
    ack = bus.coordination_acknowledge(
        TIME,
        event_id=original.event_id,
        summary="Consumed after durable write.",
    )
    assert ack.receipt.database_write_confirmed is True

    reopened = CoordinationBus(SQLiteCoordinationRepository(path))
    assert reopened.coordination_read_inbox(TIME).events == ()
    full = reopened.coordination_read_inbox(
        TIME,
        include_acknowledged=True,
    )
    assert [event.event_id for event in full.events] == [original.event_id]


def test_sqlite_coordination_repository_enforces_one_successor(tmp_path):
    repo = SQLiteCoordinationRepository(tmp_path / "coordination.sqlite")
    original = repo.append(
        CoordinationEventDraft(
            thread_key="status-thread",
            source_branch="workstream/memory",
            target_branch="workstream/time",
            event_type="STATUS",
            status="IN_PROGRESS",
            objective="Status",
            summary="Initial.",
        )
    )
    repo.append(
        CoordinationEventDraft(
            thread_key="status-thread",
            source_branch="workstream/memory",
            target_branch="workstream/time",
            event_type="STATUS",
            status="READY_FOR_REVIEW",
            objective="Status",
            summary="First successor.",
            supersedes_event_id=original.event_id,
        )
    )
    with pytest.raises(RepositoryConflict):
        repo.append(
            CoordinationEventDraft(
                thread_key="status-thread",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="STATUS",
                status="BLOCKED",
                objective="Status",
                summary="Competing successor.",
                active_issue="Competing successor must fail.",
                supersedes_event_id=original.event_id,
            )
        )


def test_sqlite_coordination_tamper_is_detected_on_reopen(tmp_path):
    path = tmp_path / "coordination.sqlite"
    repo = SQLiteCoordinationRepository(path)
    repo.append(issue_draft())

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE coordination_events SET summary=? WHERE event_sequence=1",
            ("tampered",),
        )

    with pytest.raises(CoordinationRepositoryCorrupt):
        SQLiteCoordinationRepository(path)


def test_sqlite_coordination_context_contains_only_integrity_metadata(tmp_path):
    repo = SQLiteCoordinationRepository(tmp_path / "coordination.sqlite")
    repo.append(issue_draft())
    context = repo.context()

    assert context["schema"] == "VERA_MONO_COORDINATION_SQLITE_CONTEXT_V1"
    assert context["event_sequence"] == 1
    assert len(context["head_digest"]) == 64
    assert "events" not in context
