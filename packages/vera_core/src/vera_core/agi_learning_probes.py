"""Seeded lower-bound learning probes for the AGI research program.

These probes exercise retention and compositional reuse with exact
predict-score-update ordering. They are developer-authored synthetic evidence,
not independent qualification and not an AGI claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import random
from types import MappingProxyType
from typing import Mapping

from .adaptive_linear import (
    ContextualOnlineLinearPredictor,
    OnlineLinearPredictor,
    squared_error,
)
from .agi_qualification import AGIEvaluationPacket, DimensionState
from .prequential_evaluation import PrequentialCase, evaluate_prequential


@dataclass(frozen=True, slots=True)
class SyntheticProbeReport:
    family: str
    seed: int
    metrics: Mapping[str, object]
    packet: AGIEvaluationPacket
    claim_ceiling: str = "DEVELOPER_AUTHORED_SYNTHETIC_PROBE_ONLY_NOT_AGI"

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))


def _canonical_digest(value: Mapping[str, object]) -> str:
    raw = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _regime_cases(
    coefficient: float,
    *,
    start: int,
    count: int,
) -> tuple[PrequentialCase, ...]:
    return tuple(
        PrequentialCase(
            case_id=f"regime-{start + index}",
            model_input=(1.0 if index % 2 == 0 else -1.0,),
            expected=coefficient * (1.0 if index % 2 == 0 else -1.0),
        )
        for index in range(count)
    )


def _run(learner, cases: tuple[PrequentialCase, ...]):
    return evaluate_prequential(
        cases,
        predict=learner.predict,
        score=squared_error,
        update=learner.update,
    )


def _packet(
    *,
    family: str,
    seed: int,
    subject_head: str,
    metrics: Mapping[str, object],
    criteria: tuple[bool, ...],
    dimension_states: Mapping[str, DimensionState],
) -> AGIEvaluationPacket:
    artifact = {
        "family": family,
        "seed": seed,
        "metrics": dict(metrics),
        "criteria": list(criteria),
    }
    passed = sum(criteria)
    return AGIEvaluationPacket(
        packet_id=f"synthetic:{family.lower()}:{seed}",
        subject_head=subject_head,
        family=family,
        held_out=True,
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        training_overlap="NONE_KNOWN",
        post_disclosure_tuning=False,
        developer_item_access=True,
        tool_access=("vera_core.prequential_evaluation",),
        attempted=len(criteria),
        passed=passed,
        failed=len(criteria) - passed,
        raw_artifact_digest=_canonical_digest(artifact),
        negative_results_preserved=True,
        dimension_states=dimension_states,
    )


def run_regime_return_probe(
    *,
    seed: int,
    subject_head: str,
) -> SyntheticProbeReport:
    rng = random.Random(seed)
    coefficients = [-0.9, -0.3, 0.3, 0.9]
    rng.shuffle(coefficients)

    naive = OnlineLinearPredictor.zeros(dimension=1, learning_rate=0.25)
    candidate = ContextualOnlineLinearPredictor.zeros(
        dimension=1,
        learning_rate=0.25,
    )

    cursor = 0
    for coefficient in coefficients:
        cases = _regime_cases(coefficient, start=cursor, count=24)
        _run(naive, cases)
        _run(candidate, cases)
        cursor += len(cases)

    returning = _regime_cases(coefficients[0], start=cursor, count=3)
    naive_return = _run(naive, returning)
    candidate_return = _run(candidate, returning)

    metrics: dict[str, object] = {
        "intervening_regimes": len(coefficients) - 1,
        "context_count": candidate.context_count,
        "naive_first_return_error": naive_return.steps[0].score,
        "naive_second_return_error": naive_return.steps[1].score,
        "candidate_first_return_error": candidate_return.steps[0].score,
        "candidate_second_return_error": candidate_return.steps[1].score,
    }
    criteria = (
        candidate.context_count >= 4,
        candidate_return.steps[1].score < 0.05,
        candidate_return.steps[1].score < naive_return.steps[1].score,
    )
    state = DimensionState.PARTIAL if all(criteria) else DimensionState.FAIL
    packet = _packet(
        family="REGIME_RETURN",
        seed=seed,
        subject_head=subject_head,
        metrics=metrics,
        criteria=criteria,
        dimension_states={"RETENTION_AND_INTERFERENCE": state},
    )
    return SyntheticProbeReport("REGIME_RETURN", seed, metrics, packet)


def _dot(weights: list[float], features: tuple[float, ...]) -> float:
    return sum(
        weight * feature
        for weight, feature in zip(weights, features, strict=True)
    )


def run_compositional_transfer_probe(
    *,
    seed: int,
    subject_head: str,
) -> SyntheticProbeReport:
    rng = random.Random(seed)
    coefficients = [0.8, -0.55, 0.35]
    rng.shuffle(coefficients)

    candidate = OnlineLinearPredictor.zeros(dimension=3, learning_rate=0.25)
    memorizer: dict[tuple[float, ...], float] = {}
    case_index = 0

    for dimension, coefficient in enumerate(coefficients):
        cases: list[PrequentialCase] = []
        for step in range(24):
            sign = 1.0 if step % 2 == 0 else -1.0
            features = tuple(
                sign if index == dimension else 0.0
                for index in range(3)
            )
            expected = coefficient * sign
            memorizer[features] = expected
            cases.append(
                PrequentialCase(
                    case_id=f"primitive-{case_index}",
                    model_input=features,
                    expected=expected,
                )
            )
            case_index += 1
        _run(candidate, tuple(cases))

    holdouts = [
        (1.0, 1.0, 0.0),
        (1.0, 0.0, -1.0),
        (0.0, 1.0, 1.0),
        (1.0, -1.0, 1.0),
    ]
    rng.shuffle(holdouts)
    expected = [_dot(coefficients, item) for item in holdouts]
    candidate_errors = [
        squared_error(candidate.predict(item), target)
        for item, target in zip(holdouts, expected, strict=True)
    ]
    memorizer_errors = [
        squared_error(memorizer.get(item, 0.0), target)
        for item, target in zip(holdouts, expected, strict=True)
    ]
    candidate_mse = sum(candidate_errors) / len(candidate_errors)
    memorizer_mse = sum(memorizer_errors) / len(memorizer_errors)
    all_unseen = all(item not in memorizer for item in holdouts)

    metrics: dict[str, object] = {
        "holdout_count": len(holdouts),
        "all_holdouts_unseen": all_unseen,
        "candidate_mse": candidate_mse,
        "memorizer_mse": memorizer_mse,
    }
    criteria = (
        all_unseen,
        candidate_mse < 0.01,
        candidate_mse < memorizer_mse * 0.1,
    )
    transfer_state = (
        DimensionState.PARTIAL if all(criteria) else DimensionState.FAIL
    )
    packet = _packet(
        family="COMPOSITIONAL_TRANSFER",
        seed=seed,
        subject_head=subject_head,
        metrics=metrics,
        criteria=criteria,
        dimension_states={
            "NOVEL_TASK_TRANSFER": transfer_state,
            "CROSS_DOMAIN_BREADTH": DimensionState.NOT_EVALUATED,
        },
    )
    return SyntheticProbeReport(
        "COMPOSITIONAL_TRANSFER",
        seed,
        metrics,
        packet,
    )