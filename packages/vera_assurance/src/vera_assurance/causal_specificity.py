"""Nuisance-matched causal-specificity assurance.

Adapted from SPM's causal-evidence receipt. A PASS means the supplied
directional effect clears the declared delta beyond matched nuisance and null
controls. It does not establish causal truth, authorize effects, or perform the
underlying experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math


_EVIDENCE_CLASS = "SEMANTIC_RELATION_SPECIFICITY"
_RELATIVE_TOLERANCE = 0.05


def _finite_number(value: float, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be a finite number")
    return normalized


@dataclass(frozen=True, slots=True)
class NuisanceMatch:
    same_sequence: bool
    same_update_count: bool
    same_state_shape: bool
    same_dtype: bool
    same_text_context: bool
    perturbation_l2_relative_difference: float
    state_norm_relative_difference: float

    def __post_init__(self) -> None:
        for label in (
            "same_sequence",
            "same_update_count",
            "same_state_shape",
            "same_dtype",
            "same_text_context",
        ):
            if type(getattr(self, label)) is not bool:
                raise TypeError(f"{label} must be an exact bool")
        for label in (
            "perturbation_l2_relative_difference",
            "state_norm_relative_difference",
        ):
            value = _finite_number(getattr(self, label), field=label)
            if value < 0.0:
                raise ValueError(f"{label} must be non-negative")
            object.__setattr__(self, label, value)

    def mismatch_fields(self) -> tuple[str, ...]:
        mismatches: list[str] = []
        for field in (
            "same_sequence",
            "same_update_count",
            "same_state_shape",
            "same_dtype",
            "same_text_context",
        ):
            if getattr(self, field) is not True:
                mismatches.append(field)
        if self.perturbation_l2_relative_difference > _RELATIVE_TOLERANCE:
            mismatches.append("perturbation_l2_relative_difference")
        if self.state_norm_relative_difference > _RELATIVE_TOLERANCE:
            mismatches.append("state_norm_relative_difference")
        return tuple(mismatches)


@dataclass(frozen=True, slots=True)
class CausalSpecificityReceipt:
    evidence_class: str
    verdict: str
    predicted_direction: str
    relevant_effect: float
    nuisance_effect: float
    null_effect: float
    delta_min: float
    mismatches: tuple[str, ...]
    digest: str
    authorization_effect: str = "NONE"
    causal_truth_effect: str = "NONE"


def evaluate_causal_specificity(
    *,
    relevant_effect: float,
    nuisance_effect: float,
    null_effect: float,
    delta_min: float,
    nuisance_match: NuisanceMatch,
    predicted_direction: str,
) -> CausalSpecificityReceipt:
    if type(nuisance_match) is not NuisanceMatch:
        raise TypeError("nuisance_match must be exact NuisanceMatch")
    if predicted_direction not in {"increase", "decrease"}:
        raise ValueError("predicted_direction must be increase or decrease")

    relevant = _finite_number(relevant_effect, field="relevant_effect")
    nuisance = _finite_number(nuisance_effect, field="nuisance_effect")
    null = _finite_number(null_effect, field="null_effect")
    delta = _finite_number(delta_min, field="delta_min")
    if delta <= 0.0:
        raise ValueError("delta_min must be a finite positive number")

    mismatches = nuisance_match.mismatch_fields()
    sign = 1.0 if predicted_direction == "increase" else -1.0
    directional_relevant = sign * relevant
    directional_nuisance = sign * nuisance
    directional_null = sign * null

    if mismatches:
        verdict = "UNKNOWN"
    elif directional_relevant < delta:
        verdict = "FAIL"
    elif directional_relevant - directional_nuisance < delta:
        verdict = "FAIL"
    elif directional_null >= delta:
        verdict = "FAIL"
    else:
        verdict = "PASS"

    identity = {
        "schema": "VERA_CAUSAL_SPECIFICITY_RECEIPT_V1",
        "evidence_class": _EVIDENCE_CLASS,
        "verdict": verdict,
        "predicted_direction": predicted_direction,
        "relevant_effect": relevant,
        "nuisance_effect": nuisance,
        "null_effect": null,
        "delta_min": delta,
        "nuisance_match": {
            "same_sequence": nuisance_match.same_sequence,
            "same_update_count": nuisance_match.same_update_count,
            "same_state_shape": nuisance_match.same_state_shape,
            "same_dtype": nuisance_match.same_dtype,
            "same_text_context": nuisance_match.same_text_context,
            "perturbation_l2_relative_difference": (
                nuisance_match.perturbation_l2_relative_difference
            ),
            "state_norm_relative_difference": (
                nuisance_match.state_norm_relative_difference
            ),
        },
        "mismatches": list(mismatches),
        "authorization_effect": "NONE",
        "causal_truth_effect": "NONE",
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")

    return CausalSpecificityReceipt(
        evidence_class=_EVIDENCE_CLASS,
        verdict=verdict,
        predicted_direction=predicted_direction,
        relevant_effect=relevant,
        nuisance_effect=nuisance,
        null_effect=null,
        delta_min=delta,
        mismatches=mismatches,
        digest=hashlib.sha256(encoded).hexdigest(),
    )
