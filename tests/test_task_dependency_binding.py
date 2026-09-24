import json
import sqlite3

import pytest

from vera_core import (
    TaskExecutionError,
    TaskExecutionLedger,
    TaskPacket,
)


def packet() -> TaskPacket:
    return TaskPacket(
        purpose="Exercise durable task dependencies.",
        subject="thebrazenbeard/vera-mono@dependency-test",
        completion_state="Dependency bindings survive restart.",
        evidence_requirements=("exact dependency event",),
        writable_scope=("vera-mono/test",),
        non_targets=("provider deployment",),
        forbidden_shortcuts_or_effects=("do not infer effect completion",),
        priority_order=("correctness", "evidence"),
        unknowns=(),
        return_shape=("dependency state",),
        relevant_surfaces=("source",),
    )


def test_dependency_binding_survives_restart(tmp_path):
    path = tmp_path / "tasks.sqlite"
    ledger = TaskExecutionLedger(path)
    opened = ledger.open_task(
        "task-dependency",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    assert opened.dependencies == ()

    bound = ledger.record_dependency(
        "task-dependency",
        "dep-effect-1",
        kind="EFFECT",
        target_id="provider:test:effect-1",
    )
    assert len(bound.dependencies) == 1
    dependency = bound.dependencies[0]
    assert dependency.dependency_id == "dep-effect-1"
    assert dependency.kind == "EFFECT"
    assert dependency.target_id == "provider:test:effect-1"
    assert len(dependency.event_digest) == 64

    reopened = TaskExecutionLedger(path).read("task-dependency")
    assert reopened.dependencies == bound.dependencies
    context = TaskExecutionLedger(path).context()
    assert context["tasks_with_dependencies"][0]["task_id"] == "task-dependency"
    assert context["tasks_with_dependencies"][0]["dependencies"][0]["target_id"] == (
        "provider:test:effect-1"
    )


def test_dependency_kind_is_closed_enum(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-dependency-kind",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    with pytest.raises(TaskExecutionError, match="unsupported task dependency kind"):
        ledger.record_dependency(
            "task-dependency-kind",
            "dep-bad",
            kind="REPOSITORY_WRITE",
            target_id="repo:main",
        )


def test_dependency_identity_replay_cannot_change_target(tmp_path):
    ledger = TaskExecutionLedger(tmp_path / "tasks.sqlite")
    ledger.open_task(
        "task-dependency-replay",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.record_dependency(
        "task-dependency-replay",
        "dep-1",
        kind="COORDINATION_COMMAND",
        target_id="command-1",
    )
    with pytest.raises(TaskExecutionError, match="replay carries different evidence"):
        ledger.record_dependency(
            "task-dependency-replay",
            "dep-1",
            kind="COORDINATION_COMMAND",
            target_id="command-2",
        )


def test_dependency_payload_tamper_fails_closed(tmp_path):
    path = tmp_path / "tasks.sqlite"
    ledger = TaskExecutionLedger(path)
    ledger.open_task(
        "task-dependency-tamper",
        packet(),
        lifecycle_evidence_digest="a" * 64,
    )
    ledger.record_dependency(
        "task-dependency-tamper",
        "dep-1",
        kind="PROVIDER_EFFECT",
        target_id="provider-effect-1",
    )

    with sqlite3.connect(path) as db:
        row = db.execute(
            "SELECT payload_json FROM events WHERE event_type='TASK_DEPENDENCY'"
        ).fetchone()
        payload = json.loads(row[0])
        payload["target_id"] = "provider-effect-tampered"
        db.execute(
            "UPDATE events SET payload_json=? WHERE event_type='TASK_DEPENDENCY'",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")),),
        )

    with pytest.raises(TaskExecutionError, match="event digest mismatch"):
        TaskExecutionLedger(path).read("task-dependency-tamper")
