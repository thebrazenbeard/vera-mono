"""Separated repair lifecycle state.

Adapted from RepairTracker V0. Incident recovery, repair-attempt progress, and
external-effect state are deliberately independent; progress in one track does
not promote another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RepairTransitionError(ValueError):
    pass


class IncidentState(StrEnum):
    DETECTED = "DETECTED"
    ACTIVE = "ACTIVE"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class RepairAttemptState(StrEnum):
    PROPOSED = "PROPOSED"
    REPRODUCING = "REPRODUCING"
    DIAGNOSING = "DIAGNOSING"
    PLANNED = "PLANNED"
    BUILDING = "BUILDING"
    REVIEWING = "REVIEWING"
    READY = "READY"
    EFFECT_PENDING = "EFFECT_PENDING"
    VERIFYING = "VERIFYING"
    QUALIFIED = "QUALIFIED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class EffectState(StrEnum):
    PREPARED = "PREPARED"
    ATTEMPTED = "ATTEMPTED"
    OBSERVED_APPLIED = "OBSERVED_APPLIED"
    OBSERVED_NOT_APPLIED = "OBSERVED_NOT_APPLIED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECONCILED_APPLIED = "RECONCILED_APPLIED"
    RECONCILED_NOT_APPLIED = "RECONCILED_NOT_APPLIED"
    RECONCILED_UNRESOLVED = "RECONCILED_UNRESOLVED"


_INCIDENT_TRANSITIONS = {
    IncidentState.DETECTED: frozenset({IncidentState.ACTIVE}),
    IncidentState.ACTIVE: frozenset({IncidentState.MITIGATED, IncidentState.RESOLVED}),
    IncidentState.MITIGATED: frozenset({IncidentState.ACTIVE, IncidentState.RESOLVED}),
    IncidentState.RESOLVED: frozenset({IncidentState.MONITORING, IncidentState.ACTIVE}),
    IncidentState.MONITORING: frozenset({IncidentState.CLOSED, IncidentState.ACTIVE}),
    IncidentState.CLOSED: frozenset(),
}

_ATTEMPT_TRANSITIONS = {
    RepairAttemptState.PROPOSED: frozenset({
        RepairAttemptState.REPRODUCING,
        RepairAttemptState.DIAGNOSING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.REPRODUCING: frozenset({
        RepairAttemptState.DIAGNOSING,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.DIAGNOSING: frozenset({
        RepairAttemptState.PLANNED,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.PLANNED: frozenset({
        RepairAttemptState.BUILDING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.BUILDING: frozenset({
        RepairAttemptState.REVIEWING,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.REVIEWING: frozenset({
        RepairAttemptState.BUILDING,
        RepairAttemptState.READY,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.READY: frozenset({
        RepairAttemptState.EFFECT_PENDING,
        RepairAttemptState.VERIFYING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.EFFECT_PENDING: frozenset({
        RepairAttemptState.VERIFYING,
        RepairAttemptState.FAILED,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.VERIFYING: frozenset({
        RepairAttemptState.QUALIFIED,
        RepairAttemptState.FAILED,
        RepairAttemptState.BUILDING,
        RepairAttemptState.SUPERSEDED,
    }),
    RepairAttemptState.QUALIFIED: frozenset(),
    RepairAttemptState.FAILED: frozenset(),
    RepairAttemptState.SUPERSEDED: frozenset(),
}

_EFFECT_TRANSITIONS = {
    EffectState.PREPARED: frozenset({EffectState.ATTEMPTED}),
    EffectState.ATTEMPTED: frozenset({
        EffectState.OBSERVED_APPLIED,
        EffectState.OBSERVED_NOT_APPLIED,
        EffectState.OUTCOME_UNKNOWN,
    }),
    EffectState.OBSERVED_APPLIED: frozenset({EffectState.RECONCILED_APPLIED}),
    EffectState.OBSERVED_NOT_APPLIED: frozenset({EffectState.RECONCILED_NOT_APPLIED}),
    EffectState.OUTCOME_UNKNOWN: frozenset({
        EffectState.RECONCILED_APPLIED,
        EffectState.RECONCILED_NOT_APPLIED,
        EffectState.RECONCILED_UNRESOLVED,
    }),
    EffectState.RECONCILED_APPLIED: frozenset(),
    EffectState.RECONCILED_NOT_APPLIED: frozenset(),
    EffectState.RECONCILED_UNRESOLVED: frozenset(),
}


def _transition(current: StrEnum, successor: StrEnum, table: dict) -> None:
    if successor not in table.get(current, frozenset()):
        raise RepairTransitionError(f"invalid transition: {current} -> {successor}")


@dataclass(slots=True)
class RepairCase:
    repair_id: str
    title: str
    subject_id: str
    incident_state: IncidentState = IncidentState.DETECTED
    attempt_states: dict[str, RepairAttemptState] = field(default_factory=dict)
    effect_states: dict[str, EffectState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (
            ("repair_id", self.repair_id),
            ("title", self.title),
            ("subject_id", self.subject_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{label} must be a non-empty exact string")

    def transition_incident(self, successor: IncidentState) -> None:
        _transition(self.incident_state, successor, _INCIDENT_TRANSITIONS)
        self.incident_state = successor

    def create_attempt(self, attempt_id: str) -> None:
        if type(attempt_id) is not str or not attempt_id:
            raise ValueError("attempt_id must be a non-empty exact string")
        if attempt_id in self.attempt_states:
            raise ValueError(f"attempt already exists: {attempt_id}")
        self.attempt_states[attempt_id] = RepairAttemptState.PROPOSED

    def transition_attempt(
        self,
        attempt_id: str,
        successor: RepairAttemptState,
    ) -> None:
        current = self.attempt_states[attempt_id]
        _transition(current, successor, _ATTEMPT_TRANSITIONS)
        self.attempt_states[attempt_id] = successor

    def create_effect(self, effect_id: str) -> None:
        if type(effect_id) is not str or not effect_id:
            raise ValueError("effect_id must be a non-empty exact string")
        if effect_id in self.effect_states:
            raise ValueError(f"effect already exists: {effect_id}")
        self.effect_states[effect_id] = EffectState.PREPARED

    def transition_effect(
        self,
        effect_id: str,
        successor: EffectState,
    ) -> None:
        current = self.effect_states[effect_id]
        _transition(current, successor, _EFFECT_TRANSITIONS)
        self.effect_states[effect_id] = successor
