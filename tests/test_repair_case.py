import pytest

from vera_core.repair_case import (
    EffectState,
    IncidentState,
    RepairAttemptState,
    RepairCase,
    RepairTransitionError,
)


def test_repair_case_keeps_incident_attempt_and_effect_state_separate():
    case = RepairCase(
        repair_id="repair-1",
        title="Fix source defect",
        subject_id="repo@sha",
    )

    case.transition_incident(IncidentState.ACTIVE)
    case.create_attempt("attempt-1")
    case.transition_attempt("attempt-1", RepairAttemptState.DIAGNOSING)
    case.transition_attempt("attempt-1", RepairAttemptState.PLANNED)
    case.transition_attempt("attempt-1", RepairAttemptState.BUILDING)
    case.transition_attempt("attempt-1", RepairAttemptState.REVIEWING)
    case.transition_attempt("attempt-1", RepairAttemptState.READY)

    assert case.incident_state is IncidentState.ACTIVE
    assert case.attempt_states["attempt-1"] is RepairAttemptState.READY
    assert case.effect_states == {}

    case.create_effect("effect-1")
    assert case.effect_states["effect-1"] is EffectState.PREPARED

    with pytest.raises(RepairTransitionError):
        case.transition_effect("effect-1", EffectState.OBSERVED_APPLIED)

    case.transition_effect("effect-1", EffectState.ATTEMPTED)
    case.transition_effect("effect-1", EffectState.OUTCOME_UNKNOWN)
    assert case.effect_states["effect-1"] is EffectState.OUTCOME_UNKNOWN
    assert case.attempt_states["attempt-1"] is RepairAttemptState.READY
