from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Iterable


def _unit(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{name} must be finite and within [0,1]")
    return numeric


class TransferAuthority(StrEnum):
    NONE = "NONE"


class SalienceMode(StrEnum):
    QUIESCENT = "QUIESCENT"
    ORIENTING = "ORIENTING"
    MOTIVATIONAL = "MOTIVATIONAL"
    EPISTEMIC = "EPISTEMIC"
    PROTECTIVE = "PROTECTIVE"


_NONPROTECTIVE_MODES = frozenset(
    {
        SalienceMode.ORIENTING,
        SalienceMode.MOTIVATIONAL,
        SalienceMode.EPISTEMIC,
    }
)


@dataclass(frozen=True, slots=True)
class SalienceTarget:
    target_id: str
    perceptual: float = 0.0
    semantic: float = 0.0
    motivational: float = 0.0
    incentive: float = 0.0
    epistemic: float = 0.0
    hazard: float = 0.0
    avoidance: float = 0.0
    satiation: float = 0.0

    def __post_init__(self) -> None:
        if type(self.target_id) is not str or not self.target_id.strip():
            raise ValueError("target_id must be a non-empty exact string")
        for name in (
            "perceptual",
            "semantic",
            "motivational",
            "incentive",
            "epistemic",
            "hazard",
            "avoidance",
            "satiation",
        ):
            object.__setattr__(
                self,
                name,
                _unit(getattr(self, name), name=name),
            )


@dataclass(frozen=True, slots=True)
class SaliencePolicy:
    protective_threshold: float = 0.75
    activation_threshold: float = 0.20
    support_margin: float = 0.15
    nonprotective_precedence: tuple[SalienceMode, ...] = (
        SalienceMode.MOTIVATIONAL,
        SalienceMode.EPISTEMIC,
        SalienceMode.ORIENTING,
    )

    def __post_init__(self) -> None:
        for name in (
            "protective_threshold",
            "activation_threshold",
            "support_margin",
        ):
            object.__setattr__(
                self,
                name,
                _unit(getattr(self, name), name=name),
            )
        if (
            len(self.nonprotective_precedence) != len(_NONPROTECTIVE_MODES)
            or set(self.nonprotective_precedence) != _NONPROTECTIVE_MODES
        ):
            raise ValueError(
                "nonprotective_precedence must contain ORIENTING, "
                "MOTIVATIONAL, and EPISTEMIC exactly once"
            )


@dataclass(frozen=True, slots=True)
class SalienceDecision:
    target_id: str
    mode: SalienceMode
    priority: float
    dominant_driver: str | None
    supporting_drivers: tuple[str, ...]
    incentive_after_satiation: float
    authority: TransferAuthority = TransferAuthority.NONE

    @property
    def active(self) -> bool:
        return self.mode is not SalienceMode.QUIESCENT


@dataclass(frozen=True, slots=True)
class SalienceSelection:
    selected_target_id: str | None
    decision: SalienceDecision | None
    evaluations: tuple[SalienceDecision, ...]
    used_protective_override: bool
    authority: TransferAuthority = TransferAuthority.NONE


def _ordinary_candidates(
    target: SalienceTarget,
) -> tuple[tuple[str, float], ...]:
    effective_incentive = target.incentive * (1.0 - target.satiation)
    return (
        ("perceptual", target.perceptual),
        ("semantic", target.semantic),
        ("motivational", target.motivational),
        ("incentive", effective_incentive),
        ("epistemic", target.epistemic),
    )


def arbitrate_salience(
    target: SalienceTarget,
    *,
    policy: SaliencePolicy | None = None,
) -> SalienceDecision:
    policy = SaliencePolicy() if policy is None else policy
    effective_incentive = target.incentive * (1.0 - target.satiation)

    if max(target.hazard, target.avoidance) >= policy.protective_threshold:
        dominant = "hazard" if target.hazard >= target.avoidance else "avoidance"
        supporting = tuple(
            name
            for name, value in (
                ("hazard", target.hazard),
                ("avoidance", target.avoidance),
            )
            if name != dominant and value >= policy.protective_threshold
        )
        return SalienceDecision(
            target_id=target.target_id,
            mode=SalienceMode.PROTECTIVE,
            priority=max(target.hazard, target.avoidance),
            dominant_driver=dominant,
            supporting_drivers=supporting,
            incentive_after_satiation=effective_incentive,
        )

    candidates = _ordinary_candidates(target)
    dominant, priority = max(candidates, key=lambda item: item[1])
    if priority < policy.activation_threshold:
        return SalienceDecision(
            target_id=target.target_id,
            mode=SalienceMode.QUIESCENT,
            priority=priority,
            dominant_driver=None,
            supporting_drivers=(),
            incentive_after_satiation=effective_incentive,
        )

    support_floor = max(
        policy.activation_threshold,
        priority - policy.support_margin,
    )
    supporting = tuple(
        name
        for name, value in candidates
        if name != dominant and value >= support_floor
    )

    if dominant in {"motivational", "incentive"}:
        mode = SalienceMode.MOTIVATIONAL
    elif dominant == "epistemic":
        mode = SalienceMode.EPISTEMIC
    else:
        mode = SalienceMode.ORIENTING

    return SalienceDecision(
        target_id=target.target_id,
        mode=mode,
        priority=priority,
        dominant_driver=dominant,
        supporting_drivers=supporting,
        incentive_after_satiation=effective_incentive,
    )


def select_salient_target(
    targets: Iterable[SalienceTarget],
    *,
    policy: SaliencePolicy | None = None,
) -> SalienceSelection:
    policy = SaliencePolicy() if policy is None else policy
    evaluations = tuple(
        arbitrate_salience(target, policy=policy)
        for target in targets
    )
    if not evaluations:
        raise ValueError("at least one target is required")

    protective = tuple(
        item for item in evaluations
        if item.mode is SalienceMode.PROTECTIVE
    )
    if protective:
        selected = min(
            protective,
            key=lambda item: (-item.priority, item.target_id),
        )
        return SalienceSelection(
            selected_target_id=selected.target_id,
            decision=selected,
            evaluations=evaluations,
            used_protective_override=True,
        )

    selectable = tuple(
        item for item in evaluations if item.mode in _NONPROTECTIVE_MODES
    )
    if not selectable:
        return SalienceSelection(
            selected_target_id=None,
            decision=None,
            evaluations=evaluations,
            used_protective_override=False,
        )

    rank = {
        mode: index
        for index, mode in enumerate(policy.nonprotective_precedence)
    }
    selected = min(
        selectable,
        key=lambda item: (
            rank[item.mode],
            -item.priority,
            item.target_id,
        ),
    )
    return SalienceSelection(
        selected_target_id=selected.target_id,
        decision=selected,
        evaluations=evaluations,
        used_protective_override=False,
    )


@dataclass(frozen=True, slots=True)
class AttentionObligation:
    target_id: str
    minimum_nonprotective_share: float

    def __post_init__(self) -> None:
        if type(self.target_id) is not str or not self.target_id.strip():
            raise ValueError("target_id must be a non-empty exact string")
        object.__setattr__(
            self,
            "minimum_nonprotective_share",
            _unit(
                self.minimum_nonprotective_share,
                name="minimum_nonprotective_share",
            ),
        )


@dataclass(frozen=True, slots=True)
class AttentionSample:
    target_id: str
    dominant_driver: str | None
    protective: bool = False

    def __post_init__(self) -> None:
        if type(self.target_id) is not str or not self.target_id.strip():
            raise ValueError("target_id must be a non-empty exact string")
        if self.dominant_driver is not None and (
            type(self.dominant_driver) is not str
            or not self.dominant_driver.strip()
        ):
            raise ValueError(
                "dominant_driver must be null or a non-empty exact string"
            )


@dataclass(frozen=True, slots=True)
class AttentionAudit:
    sample_count: int
    nonprotective_samples: int
    protective_samples: int
    protective_fraction: float
    dominant_nonprotective_target: str | None
    dominant_nonprotective_fraction: float
    goal_shares: tuple[tuple[str, float], ...]
    neglected_goals: tuple[str, ...]
    flags: tuple[str, ...]
    protective_override_remains_unpreemptable: bool = True
    authority: TransferAuthority = TransferAuthority.NONE

    @property
    def passed(self) -> bool:
        return not self.flags


def audit_attention_allocation(
    samples: Iterable[AttentionSample],
    obligations: Iterable[AttentionObligation],
    *,
    crowdout_fraction: float = 0.75,
    maximum_protective_fraction: float = 0.75,
) -> AttentionAudit:
    crowdout_fraction = _unit(
        crowdout_fraction,
        name="crowdout_fraction",
    )
    maximum_protective_fraction = _unit(
        maximum_protective_fraction,
        name="maximum_protective_fraction",
    )
    materialized = tuple(samples)
    obligations = tuple(obligations)
    protective = tuple(item for item in materialized if item.protective)
    ordinary = tuple(item for item in materialized if not item.protective)

    sample_count = len(materialized)
    protective_fraction = (
        len(protective) / sample_count if sample_count else 0.0
    )

    counts = Counter(item.target_id for item in ordinary)
    if ordinary:
        dominant_target, dominant_count = counts.most_common(1)[0]
        dominant_fraction = dominant_count / len(ordinary)
    else:
        dominant_target = None
        dominant_fraction = 0.0

    goal_shares = tuple(
        (
            obligation.target_id,
            counts[obligation.target_id] / len(ordinary)
            if ordinary else 0.0,
        )
        for obligation in obligations
    )
    neglected = tuple(
        obligation.target_id
        for obligation in obligations
        if (
            counts[obligation.target_id] / len(ordinary)
            if ordinary else 0.0
        ) < obligation.minimum_nonprotective_share
    )

    flags: list[str] = []
    if neglected:
        flags.append("goal_neglect")
    if (
        neglected
        and ordinary
        and dominant_fraction >= crowdout_fraction
    ):
        flags.append("target_crowd_out")

    if "target_crowd_out" in flags and dominant_target is not None:
        drivers = Counter(
            item.dominant_driver
            for item in ordinary
            if item.target_id == dominant_target
            and item.dominant_driver is not None
        )
        if (
            drivers
            and drivers.most_common(1)[0][0]
            in {"motivational", "incentive"}
        ):
            flags.append("incentive_capture")

    if (
        sample_count
        and protective_fraction > maximum_protective_fraction
    ):
        flags.append("protective_saturation")

    return AttentionAudit(
        sample_count=sample_count,
        nonprotective_samples=len(ordinary),
        protective_samples=len(protective),
        protective_fraction=protective_fraction,
        dominant_nonprotective_target=dominant_target,
        dominant_nonprotective_fraction=dominant_fraction,
        goal_shares=goal_shares,
        neglected_goals=neglected,
        flags=tuple(flags),
    )


__all__ = [
    "AttentionAudit",
    "AttentionObligation",
    "AttentionSample",
    "SalienceDecision",
    "SalienceMode",
    "SaliencePolicy",
    "SalienceSelection",
    "SalienceTarget",
    "TransferAuthority",
    "arbitrate_salience",
    "audit_attention_allocation",
    "select_salient_target",
]