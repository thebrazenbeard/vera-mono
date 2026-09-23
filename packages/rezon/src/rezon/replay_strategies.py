from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from .replay import Disposition, ReplayCandidate, ReplayStrategyOutcome, StrategyInput


def _normalize_answer(answer: str) -> str:
    return " ".join(answer.split()).casefold()


def _normalize_request(request: str) -> str:
    return " ".join(request.split())


def _candidate_by_id(strategy_input: StrategyInput, candidate_id: str) -> ReplayCandidate | None:
    for candidate in strategy_input.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    return None


def single_pass(strategy_input: StrategyInput) -> ReplayStrategyOutcome:
    """Return only the designated primary candidate, with no cross-worker governance."""
    candidate = _candidate_by_id(strategy_input, strategy_input.primary_candidate_id)
    if candidate is None:
        return ReplayStrategyOutcome(
            disposition=Disposition.FAIL_CLOSED,
            rejected_candidate_ids=(strategy_input.primary_candidate_id,),
            unresolved=("primary_candidate_missing",),
            operation_count=1,
            trace=(f"primary:{strategy_input.primary_candidate_id}:missing",),
        )
    if candidate.failure is not None or candidate.answer is None:
        reason = candidate.failure or "missing_answer"
        return ReplayStrategyOutcome(
            disposition=Disposition.FAIL_CLOSED,
            rejected_candidate_ids=(candidate.candidate_id,),
            unresolved=(reason,),
            operation_count=1,
            trace=(f"primary:{candidate.candidate_id}:ineligible:{reason}",),
        )
    return ReplayStrategyOutcome(
        disposition=Disposition.ANSWER,
        answer=candidate.answer,
        accepted_candidate_ids=(candidate.candidate_id,),
        operation_count=1,
        trace=(f"primary:{candidate.candidate_id}:selected",),
    )


def fixed_multipass(strategy_input: StrategyInput) -> ReplayStrategyOutcome:
    """Use a fixed deterministic exact-answer vote without epistemic governance."""
    eligible: list[ReplayCandidate] = []
    rejected: list[str] = []
    normalized_answers: list[str] = []

    for candidate in strategy_input.candidates:
        if candidate.failure is not None or candidate.answer is None:
            rejected.append(candidate.candidate_id)
            continue
        eligible.append(candidate)
        normalized_answers.append(_normalize_answer(candidate.answer))

    operation_count = len(strategy_input.candidates)
    if not eligible:
        return ReplayStrategyOutcome(
            disposition=Disposition.FAIL_CLOSED,
            rejected_candidate_ids=tuple(rejected),
            unresolved=("no_eligible_candidates",),
            operation_count=operation_count,
            trace=tuple(
                f"candidate:{candidate.candidate_id}:ineligible"
                for candidate in strategy_input.candidates
            ),
        )

    counts = Counter(normalized_answers)
    highest_count = max(counts.values())
    winning_normalized = next(
        normalized
        for normalized in normalized_answers
        if counts[normalized] == highest_count
    )
    accepted = tuple(
        candidate.candidate_id
        for candidate, normalized in zip(eligible, normalized_answers)
        if normalized == winning_normalized
    )
    rejected.extend(
        candidate.candidate_id
        for candidate, normalized in zip(eligible, normalized_answers)
        if normalized != winning_normalized
    )
    representative = next(
        candidate.answer
        for candidate, normalized in zip(eligible, normalized_answers)
        if normalized == winning_normalized
    )

    return ReplayStrategyOutcome(
        disposition=Disposition.ANSWER,
        answer=representative,
        accepted_candidate_ids=accepted,
        rejected_candidate_ids=tuple(rejected),
        operation_count=operation_count,
        trace=tuple(
            f"candidate:{candidate.candidate_id}:eligible:{normalized}"
            for candidate, normalized in zip(eligible, normalized_answers)
        ),
    )


class GuardName(str, Enum):
    PROPOSITION_FIDELITY = "proposition_fidelity"
    PROVENANCE_CURRENTNESS = "provenance_currentness"
    ADMISSION_INTEGRITY = "admission_integrity"
    INDEPENDENCE_CONTAMINATION = "independence_contamination"
    FAILURE_VISIBILITY = "failure_visibility"
    AUTHORITY_EFFECT_BOUNDARY = "authority_effect_boundary"


@dataclass(frozen=True)
class GuardConfig:
    enabled: frozenset[GuardName]

    def without(self, *guards: GuardName) -> "GuardConfig":
        return GuardConfig(self.enabled.difference(guards))

    def contains(self, guard: GuardName) -> bool:
        return guard in self.enabled


ALL_GUARDS = GuardConfig(frozenset(GuardName))


def _source_map(strategy_input: StrategyInput):
    return {source.source_id: source for source in strategy_input.sources}


def _correlated_candidates(candidates: tuple[ReplayCandidate, ...]) -> set[str]:
    correlated: set[str] = {
        candidate.candidate_id
        for candidate in candidates
        if candidate.saw_other_answer is True
    }
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            same_lineage = any(
                left_value is not None and left_value == right_value
                for left_value, right_value in (
                    (left.model_id, right.model_id),
                    (left.provider_id, right.provider_id),
                    (left.prompt_lineage, right.prompt_lineage),
                    (left.context_lineage, right.context_lineage),
                )
            )
            shared_evidence = bool(
                set(left.common_evidence_refs).intersection(right.common_evidence_refs)
            )
            if same_lineage or shared_evidence:
                correlated.update((left.candidate_id, right.candidate_id))
    return correlated


def rezon_guarded(
    strategy_input: StrategyInput,
    guards: GuardConfig = ALL_GUARDS,
) -> ReplayStrategyOutcome:
    """Apply explicit replay governance controls before deterministic integration."""
    strategy_input.validate()
    sources = _source_map(strategy_input)
    rejected: set[str] = set()
    violations: list[str] = []
    unresolved: list[str] = []
    trace: list[str] = []
    operation_count = 0

    answering = tuple(
        candidate
        for candidate in strategy_input.candidates
        if candidate.answer is not None and candidate.failure is None
    )

    if guards.contains(GuardName.PROPOSITION_FIDELITY):
        for candidate in answering:
            operation_count += 1
            if (
                candidate.solved_request is not None
                and _normalize_request(candidate.solved_request)
                != _normalize_request(strategy_input.literal_request)
            ):
                rejected.add(candidate.candidate_id)
                if "PROPOSITION_FIDELITY" not in violations:
                    violations.append("PROPOSITION_FIDELITY")
                trace.append(f"guard:proposition_fidelity:reject:{candidate.candidate_id}")

    if guards.contains(GuardName.PROVENANCE_CURRENTNESS):
        for candidate in answering:
            operation_count += 1
            not_explicitly_current = any(
                source_ref in sources and sources[source_ref].is_current is not True
                for source_ref in candidate.source_refs
            )
            if not_explicitly_current:
                rejected.add(candidate.candidate_id)
                if "PROVENANCE_CURRENTNESS" not in violations:
                    violations.append("PROVENANCE_CURRENTNESS")
                trace.append(f"guard:provenance_currentness:reject:{candidate.candidate_id}")

    if guards.contains(GuardName.ADMISSION_INTEGRITY):
        for candidate in answering:
            operation_count += 1
            invalid_ref = any(
                source_ref not in sources
                or sources[source_ref].admission_status != "ADMITTED"
                for source_ref in candidate.source_refs
            )
            if invalid_ref:
                rejected.add(candidate.candidate_id)
                if "ADMISSION_INTEGRITY" not in violations:
                    violations.append("ADMISSION_INTEGRITY")
                trace.append(f"guard:admission_integrity:reject:{candidate.candidate_id}")

    if guards.contains(GuardName.INDEPENDENCE_CONTAMINATION):
        correlated = _correlated_candidates(answering)
        operation_count += len(answering)
        if correlated:
            rejected.update(correlated)
            violations.append("INDEPENDENCE_CONTAMINATION")
            for candidate_id in sorted(correlated):
                trace.append(f"guard:independence_contamination:reject:{candidate_id}")

    failure_block = False
    if guards.contains(GuardName.FAILURE_VISIBILITY):
        for candidate in strategy_input.candidates:
            operation_count += 1
            if candidate.failure is not None:
                failure_block = True
                rejected.add(candidate.candidate_id)
                unresolved.append(f"{candidate.candidate_id}:{candidate.failure}")
                if "FAILURE_VISIBILITY" not in violations:
                    violations.append("FAILURE_VISIBILITY")
                trace.append(f"guard:failure_visibility:observe:{candidate.candidate_id}")

    if guards.contains(GuardName.AUTHORITY_EFFECT_BOUNDARY):
        for candidate in answering:
            operation_count += 1
            effect_overreach = candidate.effect_state_claim not in (None, "PLAN")
            authority_overreach = bool(candidate.authority_claims)
            if effect_overreach or authority_overreach:
                rejected.add(candidate.candidate_id)
                if "AUTHORITY_EFFECT_BOUNDARY" not in violations:
                    violations.append("AUTHORITY_EFFECT_BOUNDARY")
                trace.append(f"guard:authority_effect_boundary:reject:{candidate.candidate_id}")

    if failure_block:
        return ReplayStrategyOutcome(
            disposition=Disposition.ABSTAIN,
            rejected_candidate_ids=tuple(
                candidate.candidate_id
                for candidate in strategy_input.candidates
                if candidate.candidate_id in rejected
            ),
            violations_detected=tuple(violations),
            unresolved=tuple(unresolved),
            operation_count=operation_count,
            trace=tuple(trace),
        )

    eligible = tuple(
        candidate
        for candidate in answering
        if candidate.candidate_id not in rejected
    )
    if not eligible:
        return ReplayStrategyOutcome(
            disposition=Disposition.ABSTAIN,
            rejected_candidate_ids=tuple(
                candidate.candidate_id
                for candidate in strategy_input.candidates
                if candidate.candidate_id in rejected
            ),
            violations_detected=tuple(violations),
            unresolved=tuple(unresolved),
            operation_count=operation_count,
            trace=tuple(trace),
        )

    normalized_answers = tuple(_normalize_answer(candidate.answer or "") for candidate in eligible)
    counts = Counter(normalized_answers)
    highest_count = max(counts.values())
    operation_count += len(eligible)
    tied_winners = tuple(
        sorted(normalized for normalized, count in counts.items() if count == highest_count)
    )
    if len(tied_winners) > 1:
        unresolved.append("eligible_answer_tie")
        trace.append(f"integrate:ambiguous_tie:{'|'.join(tied_winners)}")
        return ReplayStrategyOutcome(
            disposition=Disposition.ABSTAIN,
            rejected_candidate_ids=tuple(
                candidate.candidate_id
                for candidate in strategy_input.candidates
                if candidate.candidate_id in rejected
            ),
            violations_detected=tuple(violations),
            unresolved=tuple(unresolved),
            operation_count=operation_count,
            trace=tuple(trace),
        )

    winning_normalized = tied_winners[0]
    accepted = tuple(
        candidate.candidate_id
        for candidate, normalized in zip(eligible, normalized_answers)
        if normalized == winning_normalized
    )
    for candidate, normalized in zip(eligible, normalized_answers):
        if normalized != winning_normalized:
            rejected.add(candidate.candidate_id)
    representative = next(
        candidate.answer
        for candidate, normalized in zip(eligible, normalized_answers)
        if normalized == winning_normalized
    )
    trace.extend(f"integrate:accept:{candidate_id}" for candidate_id in accepted)

    return ReplayStrategyOutcome(
        disposition=Disposition.ANSWER,
        answer=representative,
        accepted_candidate_ids=accepted,
        rejected_candidate_ids=tuple(
            candidate.candidate_id
            for candidate in strategy_input.candidates
            if candidate.candidate_id in rejected
        ),
        violations_detected=tuple(violations),
        unresolved=tuple(unresolved),
        operation_count=operation_count,
        trace=tuple(trace),
    )
