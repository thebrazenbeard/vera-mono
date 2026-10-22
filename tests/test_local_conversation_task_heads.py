"""Global ledger chain must not impersonate a task-scoped conversation head."""
from vera_core.task_execution import TaskExecutionLedger
from vera_core.local_conversation import open_message, conversation_history, recover_conversation


def test_independent_task_heads_survive_interleaving_and_cold_read(tmp_path):
    path = tmp_path / "tasks.sqlite"
    ledger = TaskExecutionLedger(path)
    a = open_message(ledger, "c", "a", "literal A")
    b = open_message(ledger, "c", "b", "literal B")
    assert open_message(ledger, "c", "a", "literal A") == a
    assert len(ledger.events(a["task_id"])) == 1
    expected = {a["task_id"]: a["opened_head"], b["task_id"]: b["opened_head"]}
    assert ledger.verify_chain() == b["opened_head"]
    assert ledger.verify_chain() != a["opened_head"]
    for row in conversation_history(ledger, "c"):
        assert row["task_journal_head"] == expected[row["task_id"]]
    cold = TaskExecutionLedger(path)
    history = recover_conversation(cold, None, "c")
    assert len(history) == 2
    assert all(x["status"] == "PENDING_NO_ADMITTED_PROVIDER" for x in history)
    assert all(x["task_journal_head"] == expected[x["task_id"]] for x in history)
    assert all(x["accepted_as_task_result"] is False for x in history)
