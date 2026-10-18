"""Exact Mono task-head currentness under ordinary, separate-process checkpoint writers.

No receiver-owned issuer or atomic provider admission is installed by these tests.
The action_lock does not fence ordinary TaskExecutionLedger.checkpoint().
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from vera_core.local_conversation import open_message, recover_conversation
from vera_core.task_execution import TaskExecutionError, TaskExecutionLedger


COLD_CHECKPOINT = """
import json, os, sys
from pathlib import Path
from vera_core.task_execution import TaskExecutionLedger
p = json.load(sys.stdin)
ledger = TaskExecutionLedger(Path(p["database"]))
out = ledger.checkpoint(
    p["task_id"], p["checkpoint_id"],
    completed_evidence=("test-only",),
    blockers=("NO_AUTHENTICATED_RECEIVER",),
    protected_effects_still_gated=("PROVIDER_EFFECT",),
    next_frontier="HOLD",
    lifecycle_evidence_digest="a" * 64,
    expected_task_head=p["expected_task_head"],
)
print(json.dumps({"pid": os.getpid(), "task_id": out.task_id,
                  "closed": out.closed,
                  "new_head": ledger.events(p["task_id"])[-1].event_digest}))
"""


def cold_checkpoint(database, opened, checkpoint_id):
    payload = {
        "database": str(database),
        "task_id": opened["task_id"],
        "checkpoint_id": checkpoint_id,
        "expected_task_head": opened["opened_head"],
    }
    run = subprocess.run(
        [sys.executable, "-B", "-c", COLD_CHECKPOINT],
        input=json.dumps(payload), text=True, capture_output=True,
        env=os.environ.copy(), timeout=25)
    assert run.returncode == 0, run.stderr
    output = json.loads(run.stdout)
    assert output["pid"] != os.getpid()
    assert not output["closed"]
    return output


def checkpoint(ledger, task, name):
    return ledger.checkpoint(
        task["task_id"], name,
        completed_evidence=("test-only",),
        blockers=("NO_AUTHENTICATED_RECEIVER",),
        protected_effects_still_gated=("PROVIDER_EFFECT",),
        next_frontier="HOLD",
        lifecycle_evidence_digest="b" * 64,
        expected_task_head=task["opened_head"])


def test_cold_checkpoint_a_between_preflight_and_attempt_rejects_stale_cas(tmp_path):
    database = tmp_path / "canonical-tasks.sqlite3"
    ledger = TaskExecutionLedger(database)
    a = open_message(ledger, "conversation", "message-a", "exact literal A")
    # A read-only source/receiver preflight is a SNAPSHOT, not a permit.
    snapshot = ledger.read(a["task_id"])
    original_events = ledger.events(a["task_id"])
    assert len(original_events) == 1
    assert original_events[0].event_digest == a["opened_head"]
    assert snapshot.opened_lifecycle_evidence_digest == a["source_digest"]

    with ledger.action_lock():
        # Cold process does NOT acquire action_lock and commits regardless.
        remote = cold_checkpoint(database, a, "independent-A-checkpoint")
        assert len(ledger.events(a["task_id"])) == 2

    # The old preflight still looks eligible: evidence may be stale by return.
    assert not snapshot.closed
    assert original_events[-1].event_digest == a["opened_head"]
    assert remote["new_head"] != a["opened_head"]
    assert ledger.verify_chain() == remote["new_head"]

    # ONLY the existing canonical event-append CAS rejects that stale opener.
    with pytest.raises(TaskExecutionError):
        checkpoint(ledger, a, "stale-receiver-admit-attempt")
    cold = TaskExecutionLedger(database)
    with pytest.raises(TaskExecutionError):
        checkpoint(cold, a, "stale-receiver-admit-cold-attempt")
    assert len(cold.events(a["task_id"])) == 2
    assert not cold.read(a["task_id"]).closed
    assert recover_conversation(cold, None, "conversation")[0]["task_journal_head"] == remote["new_head"]


def test_unrelated_cold_checkpoint_b_does_not_stale_a_task_cas(tmp_path):
    database = tmp_path / "canonical-tasks.sqlite3"
    ledger = TaskExecutionLedger(database)
    a = open_message(ledger, "conversation", "message-a", "exact literal A")
    b = open_message(ledger, "conversation", "message-b", "exact literal B")
    original_a_events = ledger.events(a["task_id"])
    before_global = ledger.verify_chain()
    assert before_global == b["opened_head"]

    with ledger.action_lock():
        other = cold_checkpoint(database, b, "independent-B-checkpoint")
        assert ledger.events(a["task_id"]) == original_a_events

    assert ledger.verify_chain() == other["new_head"]
    assert ledger.verify_chain() != before_global
    assert ledger.events(a["task_id"])[-1].event_digest == a["opened_head"]
    assert ledger.read(a["task_id"]).opened_lifecycle_evidence_digest == a["source_digest"]
    # Native task A CAS accepts despite unrelated B global-journal changes.
    completed = checkpoint(ledger, a, "only-A-first-checkpoint")
    assert not completed.closed
    cold = TaskExecutionLedger(database)
    assert len(cold.events(a["task_id"])) == 2
    assert len(cold.events(b["task_id"])) == 2
    assert cold.verify_chain() == cold.head
    assert all(not task.closed for task in cold.tasks())
