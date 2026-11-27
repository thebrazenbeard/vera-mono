
import json
import pytest
from vera_core import QualifiedVeraRuntime, VeraStateDirectory, TaskPacket
from vera_core.cli import main

def make_state(tmp_path):
    state=VeraStateDirectory(tmp_path/"state", project_id="vera-mono",
                             identity_id="vera", initialize=True)
    life=state.open()
    life.checkpoint(checkpoint_id="genesis", runtime_id="inspection-fixture",
                    expected_memory_head=life.memory.current_head,
                    expected_checkpoint_head=life.checkpoints.current_head,
                    expected_currentness_generation=None)
    rt=QualifiedVeraRuntime.from_state_directory(state)
    packet=TaskPacket(purpose="Restore a bounded study", subject="synthetic fixture",
        completion_state="Verified conclusion", evidence_requirements=("receipt",),
        writable_scope=("fixture only",), non_targets=("production",),
        forbidden_shortcuts_or_effects=("no protected action",), priority_order=("evidence",),
        unknowns=("fresh observation needed",), return_shape=("report",),
        relevant_surfaces=("workspace/coordination",))
    for task_id in ("study", "untouched", "finished"):
        rt.start_task(task_id, packet)
    rt.checkpoint_task("study","before-break",completed_evidence=("sha256:"+"a"*64,),
        blockers=("fresh observation required",),next_frontier="Reobserve the exhibit")
    rt.close_task("finished","done",surfaces={"workspace/coordination":"verified-current"},
        evidence_refs=("receipt",),claim_ceiling="SYNTHETIC_ONLY",next_frontier="No work")
    return state,rt,packet

def inspect_task(state, task_id, capsys, *, expected_head):
    args=["task",task_id,"--state-root",str(state.paths.root),"--project-id","vera-mono",
          "--identity-id","vera","--expected-journal-head",expected_head]
    try:
        code=main(args)
    except SystemExit as exc:
        pytest.fail(f"task inspection command failed: {exc.code}; {capsys.readouterr().err}")
    assert code==0
    return json.loads(capsys.readouterr().out)

def test_exact_task_recovers_saved_frontier_without_authority(tmp_path,capsys):
    state,rt,packet=make_state(tmp_path)
    head=rt.tasks.verify_chain()
    result=inspect_task(state,"study",capsys,expected_head=head)
    assert result["task_id"]=="study" and result["packet_digest"]==packet.packet_digest
    assert result["journal_head_digest"]==head
    assert result["latest_checkpoint"]["next_frontier"]=="Reobserve the exhibit"
    assert result["latest_checkpoint"]["completed_evidence"]==["sha256:"+"a"*64]
    assert result["latest_checkpoint"]["blockers"]==["fresh observation required"]
    assert result["checkpoint_status"]=="SAVED_UNASSESSED"
    assert result["authorization_effect"]=="NONE"
    assert "untouched" not in json.dumps(result)
    assert rt.tasks.verify_chain()==head

def test_no_checkpoint_and_closed_task_are_not_resume_grants(tmp_path,capsys):
    state,rt,_=make_state(tmp_path)
    head=rt.tasks.verify_chain()
    no_checkpoint=inspect_task(state,"untouched",capsys,expected_head=head)
    assert no_checkpoint["latest_checkpoint"] is None
    assert no_checkpoint["checkpoint_status"]=="NO_CHECKPOINT"
    closed=inspect_task(state,"finished",capsys,expected_head=head)
    assert closed["closed"] is True and closed["checkpoint_status"]=="CLOSED_TASK"
    assert closed["closeout"]["next_frontier"]=="No work"
    assert closed["authorization_effect"]=="NONE"
    assert rt.tasks.verify_chain()==head


@pytest.mark.parametrize("project,identity",[("wrong-project","vera"),("vera-mono","wrong-identity")])
def test_wrong_state_binding_refuses_before_output(tmp_path,capsys,project,identity):
    state,rt,_=make_state(tmp_path)
    head=rt.tasks.verify_chain()
    with pytest.raises(SystemExit) as exc:
        main(["task","study","--state-root",str(state.paths.root),
              "--project-id",project,"--identity-id",identity, "--expected-journal-head",head])
    captured=capsys.readouterr()
    assert exc.value.code==2 and captured.out==""
    assert rt.tasks.verify_chain()==head


def test_reject_transplanted_valid_foreign_journal(tmp_path,capsys):
    import sqlite3
    from contextlib import closing
    state,rt,_=make_state(tmp_path/"a")
    other,foreign,_=make_state(tmp_path/"b")
    # Use a distinct, internally valid history with the same task ID.
    foreign.checkpoint_task("study","foreign",completed_evidence=("foreign",),
        next_frontier="Foreign frontier must not be disclosed")
    expected=rt.tasks.verify_chain()
    foreign_head=foreign.tasks.verify_chain()
    assert expected != foreign_head
    # SQLite backup modifies only this synthetic disposable task ledger.
    with closing(sqlite3.connect(other.paths.tasks)) as src, closing(sqlite3.connect(state.paths.tasks)) as dst:
        src.backup(dst)
    assert rt.tasks.verify_chain()==foreign_head
    with pytest.raises(SystemExit) as exc:
        main(["task","study","--state-root",str(state.paths.root),
              "--project-id","vera-mono","--identity-id","vera",
              "--expected-journal-head",expected])
    captured=capsys.readouterr()
    assert exc.value.code==2 and captured.out==""
    assert "expected journal head" in captured.err
    assert rt.tasks.verify_chain()==foreign_head

def test_stale_expected_head_and_missing_pin_refuse(tmp_path,capsys):
    state,rt,_=make_state(tmp_path)
    old=rt.tasks.verify_chain()
    rt.checkpoint_task("study","later",completed_evidence=("later",),
        next_frontier="Later frontier")
    args=["task","study","--state-root",str(state.paths.root),
          "--project-id","vera-mono","--identity-id","vera"]
    for suffix in ([],["--expected-journal-head",old],
                   ["--expected-journal-head","not-a-digest"]):
        with pytest.raises(SystemExit) as exc:
            main(args+suffix)
        captured=capsys.readouterr()
        assert exc.value.code==2 and captured.out==""
