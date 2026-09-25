from __future__ import annotations

import sqlite3

import pytest

from vera_core.coordination_command_journal import (
    CoordinationCommandJournal,
    CoordinationCommandJournalError,
)


def _bind(
    journal: CoordinationCommandJournal,
    command_id: str,
    *,
    effect_id: str,
    seed: str,
) -> None:
    journal.bind(
        command_id=command_id,
        effect_id=effect_id,
        command="coordination_post",
        actor_workstream="workstream/integration",
        lifecycle_permit_digest=seed * 64,
        invocation_digest=chr(ord(seed) + 1) * 64,
        request_digest=chr(ord(seed) + 2) * 64,
    )


def test_health_projection_derives_result_classes_writes_and_unresolved(tmp_path):
    journal = CoordinationCommandJournal(tmp_path / "commands.sqlite")
    _bind(journal, "cmd-complete", effect_id="effect-complete", seed="1")
    _bind(journal, "cmd-denied", effect_id="effect-denied", seed="4")
    _bind(journal, "cmd-unresolved", effect_id="effect-unresolved", seed="7")

    journal.record_result(
        "cmd-complete",
        result_digest="a" * 64,
        result_class="COMPLETE",
        database_write_confirmed=True,
        event_id="event-1",
        event_sequence=1,
    )
    journal.record_result(
        "cmd-denied",
        result_digest="b" * 64,
        result_class="DENIED",
        database_write_confirmed=False,
        event_id=None,
        event_sequence=None,
    )

    health = journal.health_projection()

    assert health["schema"] == "VERA_MONO_COORDINATION_COMMAND_HEALTH_V1"
    assert health["binding_count"] == 3
    assert health["result_count"] == 2
    assert health["unresolved_command_count"] == 1
    assert health["unresolved_command_ids"] == ["cmd-unresolved"]
    assert health["confirmed_write_count"] == 1
    assert health["unconfirmed_result_count"] == 1
    assert health["result_class_counts"] == {
        "COMPLETE": 1,
        "DENIED": 1,
    }
    assert health["projection_digest"] == journal.verify_integrity()
    assert health["health_effect"] == "NONE"


def test_health_projection_is_restart_stable_and_context_exposes_same_view(tmp_path):
    path = tmp_path / "commands.sqlite"
    journal = CoordinationCommandJournal(path)
    _bind(journal, "cmd-one", effect_id="effect-one", seed="1")
    journal.record_result(
        "cmd-one",
        result_digest="c" * 64,
        result_class="COMPLETE",
        database_write_confirmed=True,
        event_id="event-1",
        event_sequence=1,
    )

    first = journal.health_projection()
    reopened = CoordinationCommandJournal(path)
    second = reopened.health_projection()

    assert second == first
    assert reopened.context()["health"] == second


def test_health_projection_fails_closed_on_journal_integrity_tamper(tmp_path):
    path = tmp_path / "commands.sqlite"
    journal = CoordinationCommandJournal(path)
    _bind(journal, "cmd-tamper", effect_id="effect-tamper", seed="1")
    journal.record_result(
        "cmd-tamper",
        result_digest="d" * 64,
        result_class="COMPLETE",
        database_write_confirmed=True,
        event_id="event-1",
        event_sequence=1,
    )

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE command_results SET result_class='DENIED' "
            "WHERE command_id='cmd-tamper'"
        )
        db.commit()

    with pytest.raises(CoordinationCommandJournalError):
        journal.health_projection()