import pytest
import vera_core


def test_closed_loop_frontier_api_is_available():
    assert hasattr(vera_core, "ClosedLoopFrontier")


def test_closed_loop_runs_semantic_reason_action_observe_correct(tmp_path):
    from vera_core import ClosedLoopTask
    loop = vera_core.ClosedLoopFrontier(tmp_path)
    task = ClosedLoopTask(
        task_id="novel-1",
        prompt="Choose the action supported by the evidence.",
        semantic_object={
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-33333333-3333-4333-8333-333333333333",
            "primary_label": "novel cue",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        },
    )
    result = loop.run(
        task,
        reason=lambda prompt, semantic: ("inspect", ("evidence:novel-1",)),
        act=lambda action: {"observed_action": action, "success": True},
    )
    assert result.semantic_receipt.status == "ACCEPTED"
    assert result.reasoned_action == "inspect"
    assert result.effect_state == "EFFECT_OBSERVED"
    assert result.corrective_state is None
    assert result.authorization_effect == "NONE"


def test_closed_loop_failure_enters_corrective_learning_without_fake_completion(tmp_path):
    from vera_core import ClosedLoopTask, CorrectiveStage
    loop = vera_core.ClosedLoopFrontier(tmp_path)
    task = ClosedLoopTask(
        task_id="novel-fail",
        prompt="Choose safely.",
        semantic_object={
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-44444444-4444-4444-8444-444444444444",
            "primary_label": "failure cue",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        },
    )
    result = loop.run(
        task,
        reason=lambda prompt, semantic: ("go", ("evidence:novel-fail",)),
        act=lambda action: {"observed_action": action, "success": False},
    )
    assert result.effect_state == "EFFECT_OBSERVED"
    assert result.corrective_state.current_stage is CorrectiveStage.FLAG
    assert result.corrective_state.completed is False


def test_closed_loop_consumes_reviewed_learning_once_and_can_recover(tmp_path):
    from vera_core import ClosedLoopTask
    from vera_memory import LearnedRevision, ReviewDisposition
    loop = vera_core.ClosedLoopFrontier(tmp_path)
    task = ClosedLoopTask(
        task_id="recover-1",
        prompt="Choose safely.",
        semantic_object={
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-55555555-5555-4555-8555-555555555555",
            "primary_label": "recovery cue",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        },
    )
    first = loop.run(
        task,
        reason=lambda prompt, semantic: ("go", ("evidence:first",)),
        act=lambda action: {"observed_action": action, "success": False},
    )
    revision = LearnedRevision("safe-action", first.corrective_state.events[-1].event_digest)
    loop.review_learning(
        revision,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:recover-1",
    )
    second = loop.run_with_learning(
        task,
        revision=revision,
        cue_event_id="cue:recover-1:retry",
        reason=lambda prompt, semantic, learned: (
            "stop" if learned else "go",
            ("evidence:retry", learned.memory_revision_id),
        ),
        act=lambda action: {"observed_action": action, "success": action == "stop"},
    )
    assert second.observation["success"] is True
    assert second.learned_influence.authorization_effect == "NONE"
    assert second.corrective_state.completed is False
    assert second.corrective_state.current_stage.value == "FLAG"
    assert len(second.corrective_state.events) == 1


def test_closed_loop_uses_rezon_cascade_and_dispatch_gate(tmp_path):
    from rezon.cascade import CascadeEngine, LayerResult, LayerSpec
    from vera_core import ClosedLoopTask, DurableDispatchGate
    loop = vera_core.ClosedLoopFrontier(tmp_path)
    task = ClosedLoopTask(
        task_id="rezon-1",
        prompt="Resolve action.",
        semantic_object={
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-66666666-6666-4666-8666-666666666666",
            "primary_label": "dispatch cue",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        },
    )
    cascade = CascadeEngine((
        LayerSpec(
            "reason",
            lambda req: LayerResult(
                answer="inspect", unresolved=(), confidence=0.9,
                evidence=("semantic:dispatch-cue",),
            ),
            min_confidence=0.8,
        ),
    ))
    gate = DurableDispatchGate(
        tmp_path / "dispatch.db", lineage_id="agi-loop",
        remaining_active=1, remaining_retries=0, remaining_backend_jobs=1,
    )
    result = loop.run_bounded(
        task,
        cascade=cascade,
        dispatch_gate=gate,
        holder="test-worker",
        now=10.0,
        ttl=30.0,
        expected_generation=0,
        act=lambda action: {"observed_action": action, "success": True},
    )
    assert result.reasoned_action == "inspect"
    assert result.dispatch_admission.authorization_effect == "NONE"
    assert result.dispatch_completed is True
    assert result.authorization_effect == "NONE"


def test_closed_loop_does_not_dispatch_unresolved_reasoning(tmp_path):
    from rezon.cascade import CascadeEngine, LayerResult, LayerSpec
    from vera_core import ClosedLoopTask, DurableDispatchGate
    loop = vera_core.ClosedLoopFrontier(tmp_path)
    task = ClosedLoopTask(
        task_id="unresolved-1", prompt="Unknown.",
        semantic_object={
            "schema_version": "0.1", "object_type": "node",
            "id": "NODE-77777777-7777-4777-8777-777777777777",
            "primary_label": "unknown cue", "aliases": [],
            "node_kind": "concept", "notes": None,
        },
    )
    cascade = CascadeEngine((
        LayerSpec(
            "uncertain",
            lambda req: LayerResult(
                answer=None, unresolved=("answer",), confidence=0.1
            ),
        ),
    ))
    gate = DurableDispatchGate(
        tmp_path / "dispatch.db", lineage_id="agi-loop",
        remaining_active=1, remaining_retries=0, remaining_backend_jobs=1,
    )
    try:
        loop.run_bounded(
            task, cascade=cascade, dispatch_gate=gate, holder="worker",
            now=10.0, ttl=30.0, expected_generation=0,
            act=lambda action: {"success": True},
        )
    except ValueError as exc:
        assert "did not resolve" in str(exc)
    else:
        raise AssertionError("unresolved reasoning was dispatched")
    admission = gate.claim(
        work_id="proof-no-prior-dispatch", holder="worker", now=11.0,
        ttl=30.0, expected_generation=0, retry=False,
    )
    assert admission.remaining_active == 0


def test_closed_loop_task_rejects_hidden_evaluator_target():
    from vera_core import ClosedLoopTask

    try:
        ClosedLoopTask(
            task_id="no-target-leak",
            prompt="Choose from observable evidence.",
            semantic_object={
                "schema_version": "0.1",
                "object_type": "node",
                "id": "NODE-88888888-8888-4888-8888-888888888888",
                "primary_label": "target isolation",
                "aliases": [],
                "node_kind": "concept",
                "notes": None,
            },
            expected_action="hidden-answer",
        )
    except TypeError:
        pass
    else:
        raise AssertionError("evaluator target leaked into runtime task contract")


def test_closed_loop_reviewed_learning_survives_restart(tmp_path):
    from vera_core import ClosedLoopTask
    from vera_memory import LearnedInfluenceReplay, LearnedRevision, ReviewDisposition

    task = ClosedLoopTask(
        task_id="restart-recovery",
        prompt="Choose safely.",
        semantic_object={
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-99999999-9999-4999-8999-999999999999",
            "primary_label": "restart recovery cue",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        },
    )
    first_loop = vera_core.ClosedLoopFrontier(tmp_path)
    failed = first_loop.run(
        task,
        reason=lambda prompt, semantic: ("go", ("evidence:first",)),
        act=lambda action: {"observed_action": action, "success": False},
    )
    revision = LearnedRevision(
        "restart-safe-action",
        failed.corrective_state.events[-1].event_digest,
    )
    first_loop.review_learning(
        revision,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:restart-pass",
    )
    recovered = first_loop.run_with_learning(
        task,
        revision=revision,
        cue_event_id="cue:restart:1",
        reason=lambda prompt, semantic, learned: (
            "stop",
            ("evidence:reviewed", learned.memory_revision_id),
        ),
        act=lambda action: {"observed_action": action, "success": True},
    )
    assert recovered.observation["success"] is True

    reopened = vera_core.ClosedLoopFrontier(tmp_path)
    with pytest.raises(LearnedInfluenceReplay):
        reopened.run_with_learning(
            task,
            revision=revision,
            cue_event_id="cue:restart:1",
            reason=lambda prompt, semantic, learned: (
                "stop",
                ("evidence:reviewed", learned.memory_revision_id),
            ),
            act=lambda action: {"observed_action": action, "success": True},
        )

    next_result = reopened.run_with_learning(
        task,
        revision=revision,
        cue_event_id="cue:restart:2",
        reason=lambda prompt, semantic, learned: (
            "stop",
            ("evidence:reviewed", learned.memory_revision_id),
        ),
        act=lambda action: {"observed_action": action, "success": True},
    )
    assert next_result.learned_influence.review_evidence_ref == "review:restart-pass"



def test_closed_loop_qualified_learning_enforces_a_b_c_split(tmp_path):
    from vera_core import ClosedLoopTask
    from vera_memory import LearnedInfluenceBlocked, LearnedRevision, ReviewDisposition

    loop = vera_core.ClosedLoopFrontier(tmp_path)
    task = ClosedLoopTask(
        task_id="qualified-recovery",
        prompt="Choose safely.",
        semantic_object={
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "primary_label": "qualified recovery cue",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        },
    )
    failed = loop.run(
        task,
        reason=lambda prompt, semantic: ("go", ("evidence:first",)),
        act=lambda action: {"observed_action": action, "success": False},
    )
    revision = LearnedRevision(
        "qualified-safe-action",
        failed.corrective_state.events[-1].event_digest,
    )
    loop.review_learning_qualified(
        revision,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="qualification:held-out-pass",
        calibration_evidence_ids=("calibration:A1", "calibration:A2"),
        qualification_evidence_ids=("qualification:B1", "qualification:B2"),
    )

    with pytest.raises(LearnedInfluenceBlocked):
        loop.run_with_learning(
            task,
            revision=revision,
            cue_event_id="cue:qualified:bad",
            use_evidence_id="calibration:A1",
            reason=lambda prompt, semantic, learned: (
                "stop",
                ("evidence:qualified", learned.memory_revision_id),
            ),
            act=lambda action: {"observed_action": action, "success": True},
        )

    result = loop.run_with_learning(
        task,
        revision=revision,
        cue_event_id="cue:qualified:good",
        use_evidence_id="later:C1",
        reason=lambda prompt, semantic, learned: (
            "stop",
            ("evidence:qualified", learned.memory_revision_id),
        ),
        act=lambda action: {"observed_action": action, "success": True},
    )
    assert result.learned_influence.evidence_split_qualified is True
    assert result.learned_influence.use_evidence_id == "later:C1"
