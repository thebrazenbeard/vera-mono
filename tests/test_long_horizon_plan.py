import pytest

from vera_core.long_horizon_plan import (
    DurableLongHorizonCoordinator,
    LongHorizonPlan,
    PlanBudget,
    PlanStep,
    StepState,
)


def _plan():
    return LongHorizonPlan(
        plan_id="goal-1",
        objective="complete the four-stage task without losing state",
        steps=(
            PlanStep(
                step_id="observe",
                dependencies=(),
                priority="P0",
                family_id="sense",
                collision_keys=("world",),
                max_attempts=1,
            ),
            PlanStep(
                step_id="infer",
                dependencies=("observe",),
                priority="P1",
                family_id="reason",
                collision_keys=("model",),
                max_attempts=1,
            ),
            PlanStep(
                step_id="act",
                dependencies=("infer",),
                priority="P2",
                family_id="effect",
                collision_keys=("target",),
                max_attempts=2,
            ),
            PlanStep(
                step_id="verify",
                dependencies=("act",),
                priority="P3",
                family_id="verify",
                collision_keys=("target",),
                max_attempts=1,
            ),
        ),
    )


def test_plan_is_immutable_and_reopen_rejects_definition_drift(tmp_path):
    path = tmp_path / "plan.db"
    DurableLongHorizonCoordinator(path, plan=_plan())
    changed = LongHorizonPlan(
        plan_id="goal-1",
        objective="silently changed objective",
        steps=_plan().steps,
    )
    with pytest.raises(ValueError, match="plan digest"):
        DurableLongHorizonCoordinator(path, plan=changed)


def test_ready_planning_respects_priority_family_budget_and_collisions(tmp_path):
    plan = LongHorizonPlan(
        plan_id="budget",
        objective="select a bounded collision-free frontier",
        steps=(
            PlanStep("a", (), "P1", "family-a", ("repo:a",), 1),
            PlanStep("b", (), "P0", "family-a", ("repo:b",), 1),
            PlanStep("c", (), "P0", "family-b", ("repo:c",), 1),
            PlanStep("d", (), "P0", "family-c", ("repo:c",), 1),
        ),
    )
    coord = DurableLongHorizonCoordinator(tmp_path / "budget.db", plan=plan)
    frontier = coord.plan_ready(
        budget=PlanBudget(max_parallel=2, max_per_family=1),
        occupied_collision_keys=("repo:c",),
    )
    assert [item.step_id for item in frontier.selected] == ["b"]
    assert {item.reason for item in frontier.deferred} >= {
        "COLLISION",
        "FAMILY_BUDGET",
    }


def test_failure_requires_explicit_correction_and_survives_restart(tmp_path):
    path = tmp_path / "plan.db"
    coord = DurableLongHorizonCoordinator(path, plan=_plan())

    observe = coord.claim("observe", holder="agent", now=1.0, ttl=10.0)
    coord.complete(observe, success=True, evidence_ref="obs:1")
    infer = coord.claim("infer", holder="agent", now=2.0, ttl=10.0)
    coord.complete(infer, success=True, evidence_ref="infer:1")

    act = coord.claim("act", holder="agent", now=3.0, ttl=10.0)
    failed = coord.complete(
        act,
        success=False,
        evidence_ref="environment:changed",
    )
    assert failed.state is StepState.FAILED_RETRYABLE

    reopened = DurableLongHorizonCoordinator(path, plan=_plan())
    assert reopened.plan_ready(
        budget=PlanBudget(max_parallel=1, max_per_family=1)
    ).selected == ()

    reopened.apply_correction(
        "act",
        correction_ref="correction:updated-action",
    )
    retry = reopened.claim("act", holder="agent", now=4.0, ttl=10.0)
    assert retry.fencing_token > act.fencing_token
    assert retry.attempt == 2

    with pytest.raises(ValueError, match="stale"):
        reopened.complete(act, success=True, evidence_ref="late:stale")

    reopened.complete(retry, success=True, evidence_ref="act:2")
    verify = reopened.claim("verify", holder="agent", now=5.0, ttl=10.0)
    reopened.complete(verify, success=True, evidence_ref="verify:1")

    state = reopened.snapshot()
    assert state.objective == _plan().objective
    assert state.completed_steps == ("observe", "infer", "act", "verify")
    assert state.failed_terminal_steps == ()
    assert state.total_attempts == 5
    assert state.correction_count == 1
    assert state.authorization_effect == "NONE"


def test_dependencies_cannot_be_skipped(tmp_path):
    coord = DurableLongHorizonCoordinator(tmp_path / "plan.db", plan=_plan())
    with pytest.raises(ValueError, match="dependencies"):
        coord.claim("act", holder="agent", now=1.0, ttl=10.0)
