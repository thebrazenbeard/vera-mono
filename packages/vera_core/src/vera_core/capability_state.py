"""Orthogonal capability-state axes.

Adapted from HC Brain's capability presence/activation contract. These axes are
descriptive runtime/engineering state only; none of them grant effect authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityPresence(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXTERNAL_ONLY = "EXTERNAL_ONLY"
    UNKNOWN = "UNKNOWN"


class CapabilityActivation(StrEnum):
    DISABLED = "DISABLED"
    DORMANT = "DORMANT"
    DEVELOPING = "DEVELOPING"
    ACTIVE = "ACTIVE"
    INHIBITED = "INHIBITED"


class CapabilityHealth(StrEnum):
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    FAULTED = "FAULTED"
    QUARANTINED = "QUARANTINED"
    UNKNOWN = "UNKNOWN"


class CapabilityMaturity(StrEnum):
    UNDEVELOPED = "UNDEVELOPED"
    CALIBRATING = "CALIBRATING"
    LEARNING = "LEARNING"
    STABLE_WITHIN_SCOPE = "STABLE_WITHIN_SCOPE"
    ADAPTING = "ADAPTING"


class CapabilityImplementationStatus(StrEnum):
    DESIGN_ONLY = "DESIGN_ONLY"
    UNIMPLEMENTED = "UNIMPLEMENTED"
    PROTOTYPE = "PROTOTYPE"
    EXPERIMENTAL = "EXPERIMENTAL"
    QUALIFIED_WITHIN_SCOPE = "QUALIFIED_WITHIN_SCOPE"


class CapabilityLearningPolicy(StrEnum):
    NO_LEARNING = "NO_LEARNING"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    SHADOW_LEARNING = "SHADOW_LEARNING"
    BOUNDED_DEVELOPMENT = "BOUNDED_DEVELOPMENT"
    FULL_LEARNING_WITHIN_SCOPE = "FULL_LEARNING_WITHIN_SCOPE"


@dataclass(frozen=True, slots=True)
class CapabilityState:
    capability_id: str
    presence: CapabilityPresence
    activation: CapabilityActivation
    maturity: CapabilityMaturity
    health: CapabilityHealth
    implementation_status: CapabilityImplementationStatus
    learning_policy: CapabilityLearningPolicy
    effect_authorization: str = "EXTERNAL_DECISION_REQUIRED"
    authorization_effect: str = "NONE"

    def __post_init__(self) -> None:
        if type(self.capability_id) is not str or not self.capability_id:
            raise ValueError("capability_id must be a non-empty exact string")
        exact_axes = (
            (self.presence, CapabilityPresence, "presence"),
            (self.activation, CapabilityActivation, "activation"),
            (self.maturity, CapabilityMaturity, "maturity"),
            (self.health, CapabilityHealth, "health"),
            (
                self.implementation_status,
                CapabilityImplementationStatus,
                "implementation_status",
            ),
            (self.learning_policy, CapabilityLearningPolicy, "learning_policy"),
        )
        for value, expected, label in exact_axes:
            if type(value) is not expected:
                raise TypeError(f"{label} must be exact {expected.__name__}")
        if self.effect_authorization != "EXTERNAL_DECISION_REQUIRED":
            raise ValueError(
                "CapabilityState does not own effect authorization decisions"
            )
        if self.authorization_effect != "NONE":
            raise ValueError("capability state cannot mint authorization")

    @property
    def is_active(self) -> bool:
        return self.activation is CapabilityActivation.ACTIVE

    @property
    def is_implemented(self) -> bool:
        return self.implementation_status not in {
            CapabilityImplementationStatus.DESIGN_ONLY,
            CapabilityImplementationStatus.UNIMPLEMENTED,
        }

    @property
    def may_learn(self) -> bool:
        return self.learning_policy is not CapabilityLearningPolicy.NO_LEARNING
