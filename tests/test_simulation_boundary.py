from types import MappingProxyType

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


def test_nested_patch_alias_cannot_change_applied_state_or_request_digest():
    original_patch = {"pose": {"x": 1}, "labels": ["initial"]}
    mutation = SimulationMutation(
        mutation_id="nested-alias-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch=original_patch,
    )
    original_digest = mutation.request_digest()
    state = SimulationState({"vera": {}})
    receipt = state.apply(mutation)

    # Neither the caller's original objects nor nested values reachable via
    # the public mutation may rewrite an accepted revision in place.
    original_patch["pose"]["x"] = 99
    original_patch["labels"].append("external")
    mutation.patch["pose"]["x"] = 42
    mutation.patch["labels"].append("internal")

    assert receipt.request_digest == original_digest
    assert mutation.request_digest() == original_digest
    assert state.revision == 1
    assert state.snapshot() == {"vera": {"pose": {"x": 1}, "labels": ["initial"]}}


def test_mutated_nested_patch_is_not_admitted_under_stale_digest():
    mutation = SimulationMutation(
        mutation_id="nested-preapply-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch={"pose": {"x": 1}},
    )
    state = SimulationState({"vera": {}})
    mutation.patch["pose"]["x"] = 2
    with pytest.raises(ValueError, match="patch changed after construction"):
        state.apply(mutation)
    assert state.revision == 0
    assert state.snapshot() == {"vera": {}}


def test_semantically_identical_patch_key_order_is_one_idempotent_request():
    first = SimulationMutation(
        mutation_id="canonical-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch={"pose": {"x": 1, "y": 2}, "labels": [{"a": 1, "b": 2}]},
    )
    reordered = SimulationMutation(
        mutation_id="canonical-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch={"labels": [{"b": 2, "a": 1}], "pose": {"y": 2, "x": 1}},
    )
    assert first.request_digest() == reordered.request_digest()
    state = SimulationState({"vera": {}})
    accepted = state.apply(first)
    assert state.apply(reordered) == accepted
    assert state.revision == 1


def test_mappingproxy_nested_data_uses_the_same_structural_json_digest():
    mutable = SimulationMutation(
        mutation_id="proxy-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch={"pose": {"x": 1, "y": [2, 3]}},
    )
    read_only = SimulationMutation(
        mutation_id="proxy-1",
        effect_class=SimulationEffectClass.SIMULATION_ONLY,
        subject_id="vera",
        patch=MappingProxyType({
            "pose": MappingProxyType({"y": [2, 3], "x": 1})
        }),
    )
    assert mutable.request_digest() == read_only.request_digest()


def test_non_json_mutable_patch_object_is_rejected_before_admission():
    hooks_called = []

    class MutableButStableText:
        def __init__(self):
            self.value = 1

        def __str__(self):
            hooks_called.append("str")
            return "stable"

        def __deepcopy__(self, _memo):
            hooks_called.append("deepcopy")
            return self

    with pytest.raises((TypeError, ValueError), match="JSON-compatible"):
        SimulationMutation(
            mutation_id="opaque-1",
            effect_class=SimulationEffectClass.SIMULATION_ONLY,
            subject_id="vera",
            patch={"opaque": MutableButStableText()},
        )
    assert hooks_called == []


def test_cyclic_and_nonfinite_json_patch_values_are_rejected():
    cycle = []
    cycle.append(cycle)
    for item in (cycle, {"nested": float("nan")}, {1: "numeric-key"}):
        with pytest.raises((TypeError, ValueError), match="JSON-compatible"):
            SimulationMutation(
                mutation_id="invalid-nested-1",
                effect_class=SimulationEffectClass.SIMULATION_ONLY,
                subject_id="vera",
                patch={"data": item},
            )


def test_json_patch_depth_and_size_are_bounded_before_admission():
    nested = 1
    for _ in range(66):
        nested = [nested]
    for item in (nested, "x" * 1_048_576):
        with pytest.raises(ValueError, match="JSON-compatible"):
            SimulationMutation(
                mutation_id="large-1",
                effect_class=SimulationEffectClass.SIMULATION_ONLY,
                subject_id="vera",
                patch={"data": item},
            )
