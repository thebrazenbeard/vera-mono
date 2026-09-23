from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import random
from typing import Callable

from .replay import ReplayCase, ReplayStrategyOutcome, StrategyInput
from .replay_metrics import StrategyMetrics, evaluate_strategy
from .replay_strategies import ALL_GUARDS, GuardName, rezon_guarded


StrategyCallable = Callable[[StrategyInput], ReplayStrategyOutcome]


@dataclass(frozen=True)
class OrderPermutationResult:
    seed: int
    permutation_id: str
    case_order: tuple[str, ...]
    strategy_input_digest: str
    reference_metrics: StrategyMetrics
    metrics: StrategyMetrics


@dataclass(frozen=True)
class GuardAblationResult:
    removed_guard: GuardName
    strategy_input_digest: str
    metrics: StrategyMetrics


@dataclass(frozen=True)
class LabelPermutationResult:
    seed: int
    permutation_id: str
    before_strategy_input_digest: str
    after_strategy_input_digest: str
    original_labels: tuple[tuple[str, str | None, tuple[str, ...]], ...]
    permuted_labels: tuple[tuple[str, str | None, tuple[str, ...]], ...]
    original_metrics: StrategyMetrics
    permuted_metrics: StrategyMetrics


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_strategy_inputs(cases: tuple[ReplayCase, ...]) -> str:
    """Digest strategy-visible payload independent of evaluator case ordering."""
    projected = [
        asdict(case.to_strategy_input())
        for case in sorted(cases, key=lambda item: item.case_id)
    ]
    return hashlib.sha256(_canonical_json(projected).encode("utf-8")).hexdigest()


def _permutation_id(prefix: str, seed: int, ordered_ids: tuple[str, ...]) -> str:
    payload = _canonical_json({"prefix": prefix, "seed": seed, "order": ordered_ids})
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def run_order_permutations(
    cases: tuple[ReplayCase, ...],
    strategy: StrategyCallable,
    *,
    strategy_name: str,
    seeds: tuple[int, ...],
) -> tuple[OrderPermutationResult, ...]:
    reference = evaluate_strategy(cases, strategy, strategy_name=strategy_name)
    visible_digest = digest_strategy_inputs(cases)
    results: list[OrderPermutationResult] = []
    for seed in seeds:
        shuffled = list(cases)
        random.Random(seed).shuffle(shuffled)
        permuted = tuple(shuffled)
        case_order = tuple(case.case_id for case in permuted)
        results.append(
            OrderPermutationResult(
                seed=seed,
                permutation_id=_permutation_id("order", seed, case_order),
                case_order=case_order,
                strategy_input_digest=digest_strategy_inputs(permuted),
                reference_metrics=reference,
                metrics=evaluate_strategy(
                    permuted,
                    strategy,
                    strategy_name=strategy_name,
                ),
            )
        )
        if results[-1].strategy_input_digest != visible_digest:
            raise AssertionError("case-order permutation changed strategy-visible payload")
    return tuple(results)


def run_guard_ablation(cases: tuple[ReplayCase, ...]) -> tuple[GuardAblationResult, ...]:
    visible_digest = digest_strategy_inputs(cases)
    results: list[GuardAblationResult] = []
    for guard in GuardName:
        config = ALL_GUARDS.without(guard)

        def ablated(inp: StrategyInput, *, _config=config) -> ReplayStrategyOutcome:
            return rezon_guarded(inp, guards=_config)

        results.append(
            GuardAblationResult(
                removed_guard=guard,
                strategy_input_digest=visible_digest,
                metrics=evaluate_strategy(
                    cases,
                    ablated,
                    strategy_name=f"rezon_guarded_without_{guard.value}",
                ),
            )
        )
    return tuple(results)


def _label_bundle(case: ReplayCase) -> tuple[str, str | None, tuple[str, ...]]:
    return (
        case.gold_disposition.value,
        case.gold_answer,
        case.expected_violations,
    )


def _permute_label_bundles(
    labels: tuple[tuple[str, str | None, tuple[str, ...]], ...],
    seed: int,
) -> tuple[tuple[str, str | None, tuple[str, ...]], ...]:
    if len(labels) < 2:
        return labels
    shuffled = list(labels)
    random.Random(seed).shuffle(shuffled)
    original_dispositions = tuple(label[0] for label in labels)
    shuffled_dispositions = tuple(label[0] for label in shuffled)
    if shuffled_dispositions == original_dispositions:
        for offset in range(1, len(shuffled)):
            rotated = shuffled[offset:] + shuffled[:offset]
            if tuple(label[0] for label in rotated) != original_dispositions:
                shuffled = rotated
                break
        else:
            if tuple(shuffled) == labels:
                shuffled = shuffled[1:] + shuffled[:1]
    return tuple(shuffled)


def run_label_permutation_control(
    cases: tuple[ReplayCase, ...],
    strategy: StrategyCallable,
    *,
    strategy_name: str,
    seed: int,
) -> LabelPermutationResult:
    before_digest = digest_strategy_inputs(cases)
    original_labels = tuple(_label_bundle(case) for case in cases)
    permuted_labels = _permute_label_bundles(original_labels, seed)

    permuted_cases = tuple(
        replace(
            case,
            gold_disposition=type(case.gold_disposition)(label[0]),
            gold_answer=label[1],
            expected_violations=label[2],
        )
        for case, label in zip(cases, permuted_labels)
    )
    for case in permuted_cases:
        case.validate()

    after_digest = digest_strategy_inputs(permuted_cases)
    if before_digest != after_digest:
        raise AssertionError("label permutation changed strategy-visible payload")

    order = tuple(
        f"{index}:{label[0]}:{label[1] or '-'}"
        for index, label in enumerate(permuted_labels)
    )
    return LabelPermutationResult(
        seed=seed,
        permutation_id=_permutation_id("labels", seed, order),
        before_strategy_input_digest=before_digest,
        after_strategy_input_digest=after_digest,
        original_labels=original_labels,
        permuted_labels=permuted_labels,
        original_metrics=evaluate_strategy(
            cases,
            strategy,
            strategy_name=strategy_name,
        ),
        permuted_metrics=evaluate_strategy(
            permuted_cases,
            strategy,
            strategy_name=strategy_name,
        ),
    )
