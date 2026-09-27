from vera_assurance.corrective_effectiveness import (
    CorrectionEffectivenessState,
    EffectivenessObservation,
    EffectivenessPhase,
    EffectivenessSubject,
    summarize_correction_effectiveness,
)


def test_effectiveness_requires_bound_baseline_and_active_evidence_and_regression_dominates():
    baseline = EffectivenessSubject(
        correction_id="corr-1",
        correction_revision=2,
        scope_digest="scope:abc",
    )
    active = EffectivenessSubject(
        correction_id="corr-1",
        correction_revision=2,
        scope_digest="scope:abc",
        promotion_id="promo-1",
        binding_id="bind-1",
    )
    observations = tuple(
        [
            EffectivenessObservation(
                phase=EffectivenessPhase.BASELINE,
                failure_occurred=True,
                subject=baseline,
            )
            for _ in range(5)
        ]
        + [
            EffectivenessObservation(
                phase=EffectivenessPhase.ACTIVE,
                failure_occurred=False,
                correction_triggered=True,
                subject=active,
            )
            for _ in range(5)
        ]
    )

    improved = summarize_correction_effectiveness(observations)
    assert improved.state is CorrectionEffectivenessState.IMPROVEMENT_OBSERVED
    assert improved.baseline_failure_rate == 1.0
    assert improved.active_failure_rate == 0.0
    assert improved.subject == active
    assert improved.authorization_effect == "NONE"

    regressed = summarize_correction_effectiveness(
        observations
        + (
            EffectivenessObservation(
                phase=EffectivenessPhase.ACTIVE,
                failure_occurred=False,
                regression=True,
                subject=active,
            ),
        )
    )
    assert regressed.state is CorrectionEffectivenessState.REGRESSION_OBSERVED


def test_effectiveness_cannot_report_improvement_without_exact_subject_binding():
    observations = tuple(
        [
            EffectivenessObservation(
                phase=EffectivenessPhase.BASELINE,
                failure_occurred=True,
            )
            for _ in range(5)
        ]
        + [
            EffectivenessObservation(
                phase=EffectivenessPhase.ACTIVE,
                failure_occurred=False,
                correction_triggered=True,
            )
            for _ in range(5)
        ]
    )

    import pytest
    with pytest.raises(ValueError, match="exact subject"):
        summarize_correction_effectiveness(observations)
