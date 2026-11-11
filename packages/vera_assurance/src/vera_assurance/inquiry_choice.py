"""No-effect, bounded inquiry proposal selection for Goal 1.

Candidates must originate from an observed model response in a future QVR adapter.
This module only validates/selects proposals; it does not independently generate
questions, authorize probes, score feedback, or claim learning.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class InquiryCandidate:
    gap_id: str
    question: str
    uncertainty: float
    expected_information_gain: float
    probe_cost: int


@dataclass(frozen=True, slots=True)
class InquiryDecision:
    selected_gap_id: str | None
    selected_question: str | None
    budget: int
    estimated_utility: float
    authorization_effect: str = "NONE"
    self_inquiry_verified: bool = False


def select_inquiry(
    candidates: tuple[InquiryCandidate, ...], *,
    probe_budget: int,
    minimum_utility: float = 0.0,
) -> InquiryDecision:
    """Deterministically choose one affordable predicted information gain.

    Predicted gain is an untrusted model estimate, not measured value. Ties
    resolve by gap ID, independent of proposal order. Returning no choice
    does not spend budget. Host must separately constrain inquiry actions.
    """
    if type(candidates) is not tuple or len(candidates) > 32:
        raise ValueError("bounded tuple of candidates required")
    if type(probe_budget) is not int or not 0 <= probe_budget <= 128:
        raise ValueError("invalid probe budget")
    if (type(minimum_utility) not in (int, float)
            or not math.isfinite(minimum_utility)
            or minimum_utility < 0):
        raise ValueError("invalid minimum utility")
    seen: set[str] = set()
    ranked: list[tuple[float, str, InquiryCandidate]] = []
    for c in candidates:
        if type(c) is not InquiryCandidate:
            raise TypeError("candidate must be exact InquiryCandidate")
        if (type(c.gap_id) is not str or not 1 <= len(c.gap_id) <= 128
                or type(c.question) is not str
                or not 1 <= len(c.question.strip()) <= 512):
            raise ValueError("invalid inquiry identity or question")
        if c.gap_id in seen:
            raise ValueError("duplicate gap identity")
        seen.add(c.gap_id)
        if (type(c.uncertainty) not in (int, float)
                or type(c.expected_information_gain) not in (int, float)
                or not math.isfinite(c.uncertainty)
                or not math.isfinite(c.expected_information_gain)
                or not 0 <= c.uncertainty <= 1
                or not 0 <= c.expected_information_gain <= 1
                or type(c.probe_cost) is not int
                or not 1 <= c.probe_cost <= 128):
            raise ValueError("invalid proposal estimates or cost")
        if c.probe_cost <= probe_budget:
            utility = c.uncertainty * c.expected_information_gain / c.probe_cost
            if utility > minimum_utility:
                ranked.append((-utility, c.gap_id, c))
    if not ranked:
        return InquiryDecision(None, None, probe_budget, 0.0)
    ranked.sort(key=lambda item: (item[0], item[1]))
    neg_utility, _, choice = ranked[0]
    return InquiryDecision(choice.gap_id, choice.question, probe_budget, -neg_utility)
