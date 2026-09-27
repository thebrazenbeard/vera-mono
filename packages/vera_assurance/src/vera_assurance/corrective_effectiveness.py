"""Observed post-correction effectiveness assurance.

Adapted from Fuckup's effectiveness layer. This compares bound baseline and
active observations for one exact correction subject. It does not authorize
promotion or prove causal attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EffectivenessPhase(StrEnum):
    BASELINE = "BASELINE"
    ACTIVE = "ACTIVE"


class CorrectionEffectivenessState(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    IMPROVEMENT_OBSERVED = "IMPROVEMENT_OBSERVED"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    REGRESSION_OBSERVED = "REGRESSION_OBSERVED"


@dataclass(frozen=True, slots=True)
class EffectivenessSubject:
    correction_id: str
    correction_revision: int
    scope_digest: str
    promotion_id: str | None = None
    binding_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.correction_id) is not str or not self.correction_id:
            raise ValueError("correction_id must be a non-empty exact string")
        if (
            type(self.correction_revision) is not int
            or self.correction_revision < 1
        ):
            raise ValueError(
                "correction_revision must be a positive exact integer"
            )
        if type(self.scope_digest) is not str or not self.scope_digest:
            raise ValueError("scope_digest must be a non-empty exact string")
        for label, value in (
            ("promotion_id", self.promotion_id),
            ("binding_id", self.binding_id),
        ):
            if value is not None and (type(value) is not str or not value):
                raise ValueError(
                    f"{label} must be null or a non-empty exact string"
                )


@dataclass(frozen=True, slots=True)
class EffectivenessObservation:
    phase: EffectivenessPhase
    failure_occurred: bool
    subject: EffectivenessSubject | None = None
    correction_triggered: bool = False
    prevented: bool = False
    regression: bool = False
    verification_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.phase) is not EffectivenessPhase:
            raise TypeError("phase must be exact EffectivenessPhase")
        for label in (
            "failure_occurred",
            "correction_triggered",
            "prevented",
            "regression",
        ):
            if type(getattr(self, label)) is not bool:
                raise TypeError(f"{label} must be an exact bool")
        if self.subject is not None and type(self.subject) is not EffectivenessSubject:
            raise TypeError("subject must be null or exact EffectivenessSubject")
        if self.verification_evidence_ref is not None and (
            type(self.verification_evidence_ref) is not str
            or not self.verification_evidence_ref
        ):
            raise ValueError(
                "verification_evidence_ref must be null or non-empty"
            )


@dataclass(frozen=True, slots=True)
class CorrectionEffectivenessSummary:
    state: CorrectionEffectivenessState
    baseline_exposures: int
    baseline_failures: int
    active_exposures: int
    active_failures: int
    prevented_attempts: int
    regressions: int
    baseline_failure_rate: float | None
    active_failure_rate: float | None
    subject: EffectivenessSubject | None
    authorization_effect: str = "NONE"


def _bound_subject(
    observations: tuple[EffectivenessObservation, ...],
) -> EffectivenessSubject | None:
    if not observations:
        return None

    bound = tuple(item.subject is not None for item in observations)
    if any(bound) and not all(bound):
        raise ValueError(
            "cannot mix bound and unbound effectiveness observations"
        )
    if not any(bound):
        return None

    subjects = tuple(
        item.subject for item in observations if item.subject is not None
    )
    exact = {
        (
            subject.correction_id,
            subject.correction_revision,
            subject.scope_digest,
        )
        for subject in subjects
    }
    if len(exact) != 1:
        raise ValueError("mixed effectiveness subjects")

    active_subjects = tuple(
        item.subject
        for item in observations
        if item.phase is EffectivenessPhase.ACTIVE and item.subject is not None
    )
    if active_subjects:
        if any(
            not subject.promotion_id or not subject.binding_id
            for subject in active_subjects
        ):
            raise ValueError(
                "active effectiveness observations require promotion and binding identity"
            )
        active_bindings = {
            (subject.promotion_id, subject.binding_id)
            for subject in active_subjects
        }
        if len(active_bindings) != 1:
            raise ValueError("mixed active bindings")
        return active_subjects[0]

    return subjects[0]


def summarize_correction_effectiveness(
    observations: tuple[EffectivenessObservation, ...],
    *,
    minimum_active_exposures: int = 5,
) -> CorrectionEffectivenessSummary:
    observations = tuple(observations)
    if any(type(item) is not EffectivenessObservation for item in observations):
        raise TypeError(
            "observations must contain exact EffectivenessObservation values"
        )
    if (
        type(minimum_active_exposures) is not int
        or minimum_active_exposures < 1
    ):
        raise ValueError(
            "minimum_active_exposures must be a positive exact integer"
        )

    subject = _bound_subject(observations)
    baseline = tuple(
        item for item in observations
        if item.phase is EffectivenessPhase.BASELINE
    )
    active = tuple(
        item for item in observations
        if item.phase is EffectivenessPhase.ACTIVE
    )

    baseline_failures = sum(item.failure_occurred for item in baseline)
    active_failures = sum(item.failure_occurred for item in active)
    prevented = sum(item.prevented for item in active)
    regressions = sum(item.regression for item in active)

    baseline_rate = (
        baseline_failures / len(baseline) if baseline else None
    )
    active_rate = active_failures / len(active) if active else None

    if regressions:
        state = CorrectionEffectivenessState.REGRESSION_OBSERVED
    elif not baseline or len(active) < minimum_active_exposures:
        state = CorrectionEffectivenessState.INSUFFICIENT_EVIDENCE
    elif (
        active_rate is not None
        and baseline_rate is not None
        and active_rate < baseline_rate
    ):
        state = CorrectionEffectivenessState.IMPROVEMENT_OBSERVED
    else:
        state = CorrectionEffectivenessState.NO_IMPROVEMENT

    return CorrectionEffectivenessSummary(
        state=state,
        baseline_exposures=len(baseline),
        baseline_failures=baseline_failures,
        active_exposures=len(active),
        active_failures=active_failures,
        prevented_attempts=prevented,
        regressions=regressions,
        baseline_failure_rate=baseline_rate,
        active_failure_rate=active_rate,
        subject=subject,
    )
