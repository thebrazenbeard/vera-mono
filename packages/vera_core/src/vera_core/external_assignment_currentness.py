"""Fail-closed, read-only assessment of unqualified external assignment views.

This is deliberately separate from the local TaskExecutionLedger. An external
event subset and the source's own ``COMPLETE`` assertion cannot establish a
controlling assignment graph or grant execution authority. There is currently
no independently verified source-completeness adapter in this module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExternalAssignmentEvent:
    event_id: str
    relation: str
    predecessor: str | None = None
    owner: str | None = None
    admitted: bool = True


@dataclass(frozen=True, slots=True)
class ExternalAssignmentObservation:
    assignment_ref: str
    events: tuple[ExternalAssignmentEvent, ...]
    authority_binding_claim: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalSourceCompletenessClaim:
    """Untrusted source-reported completeness, not a verification receipt."""

    source_ref: str
    status: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExternalAssignmentCurrentnessAssessment:
    assignment_state: str
    owner: str | None
    blocking_state: str
    workload_capacity: str
    effect_eligible: bool
    source_completeness_qualified: bool
    reason: str


def assess_external_assignment_currentness(
    observation: ExternalAssignmentObservation,
    completeness: ExternalSourceCompletenessClaim | None = None,
) -> ExternalAssignmentCurrentnessAssessment:
    """Classify an external view without interpreting it as permission.

    CUR19/CUR20 require that an incomplete source remain unresolved even if its
    visible events suggest a reassignment or terminal completion. A caller's
    asserted ``COMPLETE`` status is likewise insufficient: until a separately
    reviewed and bound completeness verifier exists, even a complete-looking
    graph remains unresolved. No provider I/O or execution occurs here.
    """

    if type(observation) is not ExternalAssignmentObservation:
        raise TypeError("observation must be an ExternalAssignmentObservation")

    reason = "SOURCE_COMPLETENESS_NOT_ESTABLISHED"
    if (
        type(completeness) is ExternalSourceCompletenessClaim
        and type(completeness.status) is str
        and completeness.status == "COMPLETE"
    ):
        reason = "INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE"

    return ExternalAssignmentCurrentnessAssessment(
        assignment_state="UNRESOLVED",
        owner=None,
        blocking_state="UNRESOLVED",
        workload_capacity="UNRESOLVED",
        effect_eligible=False,
        source_completeness_qualified=False,
        reason=reason,
    )
