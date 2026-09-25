import pytest

from vera_core.simulation_boundary import (
    SimulationEffectClass,
    SimulationMutation,
    SimulationState,
)


def test_simulation_boundary_rejects_external_effect_and_tracks_revisions():
    state = SimulationState({"vera": {"x": 0, "y": 0, "z": 0}})

    applied = state.apply(
        SimulationMutation(
            mutation_id="move-1",
            effect_class=SimulationEffectClass.SIMULATION_ONLY,
            subject_id="vera",
            patch={"x": 2, "z": 1},
        )
    )
    assert applied.accepted is True
    assert applied.revision_before == 0
    assert applied.revision_after == 1
    assert applied.external_effect is False
    assert state.snapshot()["vera"] == {"x": 2, "y": 0, "z": 1}

    rejected = state.apply(
        SimulationMutation(
            mutation_id="external-1",
            effect_class=SimulationEffectClass.EXTERNAL_REQUEST,
            subject_id="vera",
            patch={"x": 99},
        )
    )
    assert rejected.accepted is False
    assert rejected.disposition == "EXTERNAL_EFFECT_UNAVAILABLE"
    assert rejected.revision_before == 1
    assert rejected.revision_after == 1
    assert state.snapshot()["vera"]["x"] == 2

    with pytest.raises(ValueError, match="mutation_id replay carries different request"):
        state.apply(
            SimulationMutation(
                mutation_id="move-1",
                effect_class=SimulationEffectClass.SIMULATION_ONLY,
                subject_id="vera",
                patch={"x": 3},
            )
        )


def test_simulation_mutation_request_is_immutable_after_construction():
    mutation = SimulationMutation(
        mutation_id="immutable-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch={"x": 1},
    )
    original = mutation.request_digest()

    with pytest.raises(TypeError):
        mutation.patch["x"] = 9

    assert mutation.request_digest() == original
