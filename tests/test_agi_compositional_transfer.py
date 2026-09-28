import math

from vera_core import (
    AffinePrimitiveLearner,
    PrimitiveProgramMemorizer,
    qualify_compositional_transfer,
)


def test_affine_primitive_learner_composes_unseen_programs():
    learner = AffinePrimitiveLearner()

    # Learn f(x)=2x+1 and g(x)=x-3 only from singleton primitive examples.
    learner.observe("double_plus_one", x=0.0, y=1.0)
    learner.observe("double_plus_one", x=2.0, y=5.0)
    learner.observe("minus_three", x=0.0, y=-3.0)
    learner.observe("minus_three", x=4.0, y=1.0)

    # Exact two-step program was never observed.
    assert learner.seen_programs == frozenset()
    assert math.isclose(
        learner.predict(("double_plus_one", "minus_three"), 5.0),
        8.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert math.isclose(
        learner.predict(("minus_three", "double_plus_one"), 5.0),
        5.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_primitive_memorizer_cannot_fake_unseen_composition():
    baseline = PrimitiveProgramMemorizer()
    baseline.observe(("double_plus_one",), x=2.0, y=5.0)
    baseline.observe(("minus_three",), x=4.0, y=1.0)

    assert baseline.predict(("double_plus_one", "minus_three"), 5.0) is None
    assert baseline.predict(("minus_three", "double_plus_one"), 5.0) is None


def test_compositional_qualifier_requires_success_and_ablation_delta():
    result = qualify_compositional_transfer(
        learner_predictions=(8.0, 5.0, -4.0, 3.0),
        expected=(8.0, 5.0, -4.0, 3.0),
        baseline_predictions=(None, None, None, None),
        absolute_tolerance=1e-9,
        min_unseen_success_rate=0.75,
        min_ablation_delta=0.50,
        curator_independence="INDEPENDENT_MODEL",
        developer_item_access=False,
    )

    assert result.unseen_composition_success_rate == 1.0
    assert result.baseline_success_rate == 0.0
    assert result.ablation_delta == 1.0
    assert result.dimension_states == {
        "NOVEL_TASK_TRANSFER": "PASS",
        "CROSS_DOMAIN_BREADTH": "PASS",
    }
    assert result.claim_ceiling == (
        "COMPOSITIONAL_TRANSFER_DIMENSION_EVIDENCE_ONLY_NOT_AGI"
    )


def test_developer_authored_compositional_cut_caps_at_partial():
    result = qualify_compositional_transfer(
        learner_predictions=(8.0, 5.0, -4.0, 3.0),
        expected=(8.0, 5.0, -4.0, 3.0),
        baseline_predictions=(None, None, None, None),
        absolute_tolerance=1e-9,
        min_unseen_success_rate=0.75,
        min_ablation_delta=0.50,
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        developer_item_access=True,
    )

    assert result.dimension_states == {
        "NOVEL_TASK_TRANSFER": "PARTIAL",
        "CROSS_DOMAIN_BREADTH": "PARTIAL",
    }


def test_compositional_qualifier_preserves_error_taxonomy():
    result = qualify_compositional_transfer(
        learner_predictions=(8.0, None, 99.0, 3.0),
        expected=(8.0, 5.0, -4.0, 3.0),
        baseline_predictions=(None, None, None, None),
        absolute_tolerance=1e-9,
        min_unseen_success_rate=0.75,
        min_ablation_delta=0.50,
        curator_independence="INDEPENDENT_MODEL",
        developer_item_access=False,
    )

    assert result.error_taxonomy == {
        "CORRECT": 2,
        "UNRESOLVED": 1,
        "WRONG": 1,
    }
    assert result.dimension_states == {
        "NOVEL_TASK_TRANSFER": "FAIL",
        "CROSS_DOMAIN_BREADTH": "FAIL",
    }


def test_affine_primitive_requires_identifiable_primitive_before_composition():
    learner = AffinePrimitiveLearner()
    learner.observe("double_plus_one", x=1.0, y=3.0)

    try:
        learner.predict(("double_plus_one",), 2.0)
    except ValueError as exc:
        assert "not identified" in str(exc)
    else:
        raise AssertionError("underidentified primitive was used")
