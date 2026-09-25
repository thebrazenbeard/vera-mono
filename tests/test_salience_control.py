from __future__ import annotations

from runtime_cohesion.salience_control import (
    AttentionObligation,
    AttentionSample,
    SalienceMode,
    SaliencePolicy,
    SalienceTarget,
    TransferAuthority,
    audit_attention_allocation,
    arbitrate_salience,
    select_salient_target,
)


def test_salience_arbitration_preserves_typed_driver_without_weighted_sum():
    decision = arbitrate_salience(
        SalienceTarget(
            target_id="target:a",
            perceptual=0.4,
            semantic=0.7,
            motivational=0.3,
            incentive=0.9,
            satiation=0.5,
            epistemic=0.65,
        )
    )
    assert decision.mode is SalienceMode.ORIENTING
    assert decision.dominant_driver == "semantic"
    assert decision.priority == 0.7
    assert "epistemic" in decision.supporting_drivers
    assert decision.authority is TransferAuthority.NONE


def test_protective_signal_overrides_attention_but_grants_no_effect_authority():
    result = select_salient_target(
        [
            SalienceTarget(target_id="goal:work", semantic=1.0),
            SalienceTarget(target_id="hazard:fire", hazard=0.9),
        ]
    )
    assert result.selected_target_id == "hazard:fire"
    assert result.used_protective_override is True
    assert result.decision is not None
    assert result.decision.mode is SalienceMode.PROTECTIVE
    assert result.decision.authority is TransferAuthority.NONE


def test_nonprotective_mode_precedence_is_explicit_policy_not_hidden_score():
    result = select_salient_target(
        [
            SalienceTarget(target_id="target:motivation", motivational=0.4),
            SalienceTarget(target_id="target:epistemic", epistemic=0.95),
        ],
        policy=SaliencePolicy(
            nonprotective_precedence=(
                SalienceMode.EPISTEMIC,
                SalienceMode.MOTIVATIONAL,
                SalienceMode.ORIENTING,
            )
        ),
    )
    assert result.selected_target_id == "target:epistemic"


def test_attention_audit_detects_goal_neglect_and_capture():
    audit = audit_attention_allocation(
        [
            AttentionSample(
                target_id="target:loop",
                dominant_driver="incentive",
                protective=False,
            )
            for _ in range(9)
        ]
        + [
            AttentionSample(
                target_id="goal:maintenance",
                dominant_driver="semantic",
                protective=False,
            )
        ],
        [AttentionObligation("goal:maintenance", minimum_nonprotective_share=0.2)],
    )
    assert "goal_neglect" in audit.flags
    assert "target_crowd_out" in audit.flags
    assert "incentive_capture" in audit.flags


def test_attention_audit_flags_protective_saturation_without_preempting_it():
    audit = audit_attention_allocation(
        [
            AttentionSample(
                target_id="hazard:fire",
                dominant_driver="hazard",
                protective=True,
            )
            for _ in range(9)
        ]
        + [
            AttentionSample(
                target_id="goal:maintenance",
                dominant_driver="semantic",
                protective=False,
            )
        ],
        [AttentionObligation("goal:maintenance", minimum_nonprotective_share=0.5)],
        maximum_protective_fraction=0.75,
    )
    assert audit.protective_fraction == 0.9
    assert "protective_saturation" in audit.flags
    assert audit.protective_override_remains_unpreemptable is True


def test_quiescent_targets_do_not_create_fake_attention():
    result = select_salient_target(
        [
            SalienceTarget(target_id="target:a"),
            SalienceTarget(target_id="target:b"),
        ]
    )
    assert result.selected_target_id is None
    assert result.decision is None