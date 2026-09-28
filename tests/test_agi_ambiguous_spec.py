import pytest

from rezon.cascade import CascadeEngine, LayerResult, LayerSpec
from vera_core import (
    ClosedLoopFrontier,
    ClosedLoopTask,
    DecisionCandidate,
    DurableDispatchGate,
    StructuredAmbiguityGuard,
    StructuredAmbiguitySpec,
)


def _semantic_node(node_id: str, label: str):
    return {
        "schema_version": "0.1",
        "object_type": "node",
        "id": node_id,
        "primary_label": label,
        "aliases": [],
        "node_kind": "concept",
        "notes": None,
    }


def _ambiguous_spec(surface_form: str = "Choose safely."):
    return StructuredAmbiguitySpec(
        spec_id="ambiguous-1",
        surface_form=surface_form,
        candidates=(
            DecisionCandidate(
                action="inspect",
                support=0.82,
                evidence_refs=("evidence:a",),
            ),
            DecisionCandidate(
                action="defer",
                support=0.80,
                evidence_refs=("evidence:b",),
            ),
        ),
        min_support=0.70,
        min_margin=0.10,
        hard_conflict=False,
    )


def _clear_spec():
    return StructuredAmbiguitySpec(
        spec_id="clear-1",
        surface_form="Choose the uniquely supported action.",
        candidates=(
            DecisionCandidate(
                action="inspect",
                support=0.94,
                evidence_refs=("evidence:clear",),
            ),
            DecisionCandidate(
                action="defer",
                support=0.30,
                evidence_refs=("evidence:weak",),
            ),
        ),
        min_support=0.70,
        min_margin=0.10,
        hard_conflict=False,
    )


def test_guard_abstains_when_top_candidates_are_too_close():
    decision = StructuredAmbiguityGuard().resolve(_ambiguous_spec())

    assert decision.abstained is True
    assert decision.action is None
    assert decision.reason == "INSUFFICIENT_MARGIN"
    assert decision.authorization_effect == "NONE"


def test_guard_abstains_on_explicit_hard_conflict():
    spec = StructuredAmbiguitySpec(
        spec_id="conflict-1",
        surface_form="Proceed, but do not proceed if the safety condition applies.",
        candidates=(
            DecisionCandidate(
                action="proceed",
                support=0.95,
                evidence_refs=("evidence:pro",),
            ),
        ),
        min_support=0.70,
        min_margin=0.10,
        hard_conflict=True,
    )

    decision = StructuredAmbiguityGuard().resolve(spec)

    assert decision.abstained is True
    assert decision.action is None
    assert decision.reason == "HARD_CONFLICT"


def test_guard_still_acts_when_one_candidate_is_clearly_supported():
    decision = StructuredAmbiguityGuard().resolve(_clear_spec())

    assert decision.abstained is False
    assert decision.action == "inspect"
    assert decision.reason == "CLEAR_WINNER"
    assert decision.confidence >= 0.90


def test_surface_paraphrase_does_not_change_structured_ambiguity_decision():
    guard = StructuredAmbiguityGuard()
    variants = (
        _ambiguous_spec("Choose safely."),
        _ambiguous_spec("Select the safest supported option."),
        _ambiguous_spec("Which action should be taken given the evidence?"),
    )

    decisions = tuple(guard.resolve(spec) for spec in variants)

    assert all(item.abstained for item in decisions)
    assert {item.reason for item in decisions} == {"INSUFFICIENT_MARGIN"}
    assert {item.evidence_digest for item in decisions}.__len__() == 1


def test_ambiguous_guard_blocks_dispatch_before_budget_claim(tmp_path):
    guard = StructuredAmbiguityGuard()
    spec = _ambiguous_spec()
    decision = guard.resolve(spec)

    cascade = CascadeEngine(
        (
            LayerSpec(
                "ambiguity-guard",
                lambda req: LayerResult(
                    answer=decision.action,
                    unresolved=("ambiguity",) if decision.abstained else (),
                    confidence=decision.confidence,
                    evidence=decision.evidence_refs,
                ),
                min_confidence=0.70,
            ),
        )
    )
    gate = DurableDispatchGate(
        tmp_path / "guarded-dispatch.db",
        lineage_id="ambiguous-guarded",
        remaining_active=1,
        remaining_retries=0,
        remaining_backend_jobs=1,
    )
    loop = ClosedLoopFrontier(tmp_path / "guarded-state")
    task = ClosedLoopTask(
        task_id="ambiguous-dispatch",
        prompt=spec.surface_form,
        semantic_object=_semantic_node(
            "NODE-88888888-8888-4888-8888-888888888888",
            "ambiguous decision",
        ),
    )

    with pytest.raises(ValueError, match="did not resolve"):
        loop.run_bounded(
            task,
            cascade=cascade,
            dispatch_gate=gate,
            holder="guarded-worker",
            now=10.0,
            ttl=30.0,
            expected_generation=0,
            act=lambda action: {"success": True},
        )

    proof = gate.claim(
        work_id="proof-budget-untouched",
        holder="guarded-worker",
        now=11.0,
        ttl=30.0,
        expected_generation=0,
        retry=False,
    )
    assert proof.budget_generation == 1


def test_forced_answer_baseline_dispatches_same_ambiguous_case(tmp_path):
    spec = _ambiguous_spec()
    forced = max(spec.candidates, key=lambda item: item.support)

    cascade = CascadeEngine(
        (
            LayerSpec(
                "forced-answer",
                lambda req: LayerResult(
                    answer=forced.action,
                    unresolved=(),
                    confidence=forced.support,
                    evidence=forced.evidence_refs,
                ),
                min_confidence=0.70,
            ),
        )
    )
    gate = DurableDispatchGate(
        tmp_path / "forced-dispatch.db",
        lineage_id="ambiguous-forced",
        remaining_active=1,
        remaining_retries=0,
        remaining_backend_jobs=1,
    )
    loop = ClosedLoopFrontier(tmp_path / "forced-state")
    task = ClosedLoopTask(
        task_id="forced-dispatch",
        prompt=spec.surface_form,
        semantic_object=_semantic_node(
            "NODE-99999999-9999-4999-8999-999999999999",
            "forced ambiguous decision",
        ),
    )

    result = loop.run_bounded(
        task,
        cascade=cascade,
        dispatch_gate=gate,
        holder="forced-worker",
        now=10.0,
        ttl=30.0,
        expected_generation=0,
        act=lambda action: {
            "observed_action": action,
            "success": False,
        },
    )

    assert result.reasoned_action == "inspect"
    assert result.dispatch_admission is not None
    assert result.dispatch_completed is True
