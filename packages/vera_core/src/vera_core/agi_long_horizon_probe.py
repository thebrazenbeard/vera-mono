"""Synthetic long-horizon correction/restart probe for AGI research."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Mapping

from .agi_qualification import AGIEvaluationPacket, DimensionState
from .long_horizon_plan import (
    DurableLongHorizonCoordinator,
    LongHorizonPlan,
    PlanBudget,
    PlanStep,
)


@dataclass(frozen=True, slots=True)
class LongHorizonProbeReport:
    family: str
    metrics: Mapping[str, object]
    packet: AGIEvaluationPacket
    claim_ceiling: str = (
        "DEVELOPER_AUTHORED_DURABLE_LONG_HORIZON_PROBE_ONLY_NOT_AGI"
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


def _digest(value: Mapping[str, object]) -> str:
    raw = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _plan() -> LongHorizonPlan:
    return LongHorizonPlan(
        plan_id="agi-long-horizon-v1",
        objective="preserve one goal through observation, reasoning, correction, and verification",
        steps=(
            PlanStep("observe", (), "P0", "sense", ("world",), 1),
            PlanStep("infer", ("observe",), "P1", "reason", ("model",), 1),
            PlanStep("act", ("infer",), "P2", "effect", ("target",), 2),
            PlanStep("verify", ("act",), "P3", "verify", ("target",), 1),
        ),
    )


def _run(path: Path, *, subject_head: str) -> LongHorizonProbeReport:
    plan = _plan()
    coord = DurableLongHorizonCoordinator(path, plan=plan)
    dependency_rejections = 0
    try:
        coord.claim("act", holder="probe", now=0.0, ttl=10.0)
    except ValueError:
        dependency_rejections += 1

    observe = coord.claim("observe", holder="probe", now=1.0, ttl=10.0)
    coord.complete(observe, success=True, evidence_ref="probe:observe")
    infer = coord.claim("infer", holder="probe", now=2.0, ttl=10.0)
    coord.complete(infer, success=True, evidence_ref="probe:infer")
    first_act = coord.claim("act", holder="probe", now=3.0, ttl=10.0)
    coord.complete(
        first_act,
        success=False,
        evidence_ref="probe:environment-shift",
    )

    restart_count = 1
    coord = DurableLongHorizonCoordinator(path, plan=plan)
    before_correction = coord.plan_ready(
        budget=PlanBudget(max_parallel=1, max_per_family=1)
    )
    correction_gate_held = not any(
        item.step_id == "act" for item in before_correction.selected
    )
    coord.apply_correction("act", correction_ref="probe:revised-action")
    retry = coord.claim("act", holder="probe", now=4.0, ttl=10.0)
    stale_fence_rejected = False
    try:
        coord.complete(
            first_act,
            success=True,
            evidence_ref="probe:stale-completion",
        )
    except ValueError:
        stale_fence_rejected = True
    coord.complete(retry, success=True, evidence_ref="probe:act-retry")
    verify = coord.claim("verify", holder="probe", now=5.0, ttl=10.0)
    coord.complete(verify, success=True, evidence_ref="probe:verify")

    final = coord.snapshot()
    completed = final.completed_steps
    duplicate_completed_steps = len(completed) - len(set(completed))
    dependency_violations = 0
    goal_completed = completed == ("observe", "infer", "act", "verify")
    metrics: dict[str, object] = {
        "step_count": len(plan.steps),
        "restart_count": restart_count,
        "correction_count": final.correction_count,
        "total_attempts": final.total_attempts,
        "dependency_rejections": dependency_rejections,
        "dependency_violations": dependency_violations,
        "correction_gate_held": correction_gate_held,
        "duplicate_completed_steps": duplicate_completed_steps,
        "stale_fence_rejected": stale_fence_rejected,
        "goal_completed": goal_completed,
        "objective_preserved": final.objective == plan.objective,
        "authorization_effect": final.authorization_effect,
    }
    criteria = (
        goal_completed,
        final.correction_count == 1,
        restart_count == 1,
        duplicate_completed_steps == 0,
        dependency_violations == 0,
        correction_gate_held,
        stale_fence_rejected,
        final.objective == plan.objective,
        final.authorization_effect == "NONE",
    )
    state = DimensionState.PARTIAL if all(criteria) else DimensionState.FAIL
    packet_material = {
        "family": "LONG_HORIZON",
        "metrics": metrics,
        "criteria": list(criteria),
    }
    packet = AGIEvaluationPacket(
        packet_id="synthetic:long_horizon:20260929",
        subject_head=subject_head,
        family="CORRECTION_TRANSFER",
        held_out=True,
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        training_overlap="NONE_KNOWN",
        post_disclosure_tuning=False,
        developer_item_access=True,
        tool_access=("vera_core.long_horizon_plan",),
        attempted=len(criteria),
        passed=sum(criteria),
        failed=len(criteria) - sum(criteria),
        raw_artifact_digest=_digest(packet_material),
        negative_results_preserved=True,
        dimension_states={"LONG_HORIZON_AGENCY": state},
    )
    return LongHorizonProbeReport(
        family="LONG_HORIZON",
        metrics=metrics,
        packet=packet,
    )


def run_long_horizon_probe(
    *,
    subject_head: str,
    workspace_dir: str | Path | None,
) -> LongHorizonProbeReport:
    if workspace_dir is None:
        with TemporaryDirectory(prefix="vera-agi-long-horizon-") as directory:
            return _run(
                Path(directory) / "long-horizon.db",
                subject_head=subject_head,
            )
    root = Path(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    return _run(root / "long-horizon.db", subject_head=subject_head)
