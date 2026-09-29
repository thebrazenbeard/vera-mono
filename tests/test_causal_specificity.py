import math

import pytest

from vera_assurance.causal_specificity import (
    NuisanceMatch,
    evaluate_causal_specificity,
)


def matched() -> NuisanceMatch:
    return NuisanceMatch(
        same_sequence=True,
        same_update_count=True,
        same_state_shape=True,
        same_dtype=True,
        same_text_context=True,
        perturbation_l2_relative_difference=0.01,
        state_norm_relative_difference=0.02,
    )


def test_causal_specificity_requires_effect_beyond_matched_nuisance_and_null():
    receipt = evaluate_causal_specificity(
        relevant_effect=0.12,
        nuisance_effect=0.02,
        null_effect=0.01,
        delta_min=0.03,
        nuisance_match=matched(),
        predicted_direction="increase",
    )

    assert receipt.verdict == "PASS"
    assert receipt.evidence_class == "SEMANTIC_RELATION_SPECIFICITY"
    assert receipt.authorization_effect == "NONE"
    assert receipt.causal_truth_effect == "NONE"
    assert len(receipt.digest) == 64


def test_causal_specificity_is_unknown_when_nuisance_match_fails():
    mismatch = NuisanceMatch(
        same_sequence=True,
        same_update_count=True,
        same_state_shape=True,
        same_dtype=True,
        same_text_context=True,
        perturbation_l2_relative_difference=0.06,
        state_norm_relative_difference=0.01,
    )
    receipt = evaluate_causal_specificity(
        relevant_effect=0.80,
        nuisance_effect=0.00,
        null_effect=0.00,
        delta_min=0.03,
        nuisance_match=mismatch,
        predicted_direction="increase",
    )

    assert receipt.verdict == "UNKNOWN"
    assert "perturbation_l2_relative_difference" in receipt.mismatches


@pytest.mark.parametrize(
    "field,value",
    [
        ("relevant_effect", math.nan),
        ("nuisance_effect", math.inf),
        ("null_effect", -math.inf),
        ("delta_min", math.nan),
    ],
)
def test_causal_specificity_rejects_nonfinite_numeric_evidence(field, value):
    kwargs = dict(
        relevant_effect=0.12,
        nuisance_effect=0.02,
        null_effect=0.01,
        delta_min=0.03,
        nuisance_match=matched(),
        predicted_direction="increase",
    )
    kwargs[field] = value
    with pytest.raises(ValueError, match="finite"):
        evaluate_causal_specificity(**kwargs)


def test_causal_specificity_receipt_binds_decision_policy():
    receipt = evaluate_causal_specificity(
        relevant_effect=0.12,
        nuisance_effect=0.02,
        null_effect=0.01,
        delta_min=0.03,
        nuisance_match=matched(),
        predicted_direction="increase",
    )

    assert receipt.policy_id == "VERA_CAUSAL_SPECIFICITY_V1"
    assert receipt.nuisance_relative_tolerance == 0.05
