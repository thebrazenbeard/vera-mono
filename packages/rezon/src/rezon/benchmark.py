from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    gold_answer: str | None
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class StrategyOutcome:
    answer: str | None
    unsupported_claim_count: int = 0
    execution_count: int = 0
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkMetrics:
    total: int
    correct: int
    failures: int
    executions: int
    unsupported_claims: int
    wall_clock_seconds: float


def run_benchmark(
    cases: tuple[BenchmarkCase, ...],
    strategies: Mapping[str, Callable[[BenchmarkCase], StrategyOutcome]],
) -> dict[str, BenchmarkMetrics]:
    report: dict[str, BenchmarkMetrics] = {}
    for name, strategy in strategies.items():
        correct = failures = executions = unsupported = 0
        start = perf_counter()
        for case in cases:
            try:
                outcome = strategy(case)
            except Exception:
                failures += 1
                continue
            if outcome.answer == case.gold_answer and not outcome.failures:
                correct += 1
            if outcome.failures:
                failures += 1
            executions += outcome.execution_count
            unsupported += outcome.unsupported_claim_count
        report[name] = BenchmarkMetrics(
            total=len(cases),
            correct=correct,
            failures=failures,
            executions=executions,
            unsupported_claims=unsupported,
            wall_clock_seconds=perf_counter() - start,
        )
    return report
