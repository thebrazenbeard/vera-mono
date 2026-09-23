from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryEvidenceType(str, Enum):
    USER_STATED = "USER_STATED"
    OBSERVED_INTERACTION = "OBSERVED_INTERACTION"
    INFERRED_RELATIONSHIP_STATE = "INFERRED_RELATIONSHIP_STATE"
    DERIVED_SUMMARY = "DERIVED_SUMMARY"
    EXTERNAL_IMPORTED = "EXTERNAL_IMPORTED"


_PROTECTED_RELATIONSHIP_BEHAVIORS = frozenset(
    {
        "AFFECTION_INTENSITY",
        "SEXUAL_ACCESS",
        "JEALOUSY",
        "WITHDRAWAL",
        "GUILT",
        "URGENCY",
        "BOUNDARY_CHANGE",
        "INITIATIVE",
    }
)

_COMMERCIAL_SIGNAL_CLASSES = frozenset(
    {
        "CHURN_RISK",
        "CONVERSION",
        "LIFETIME_VALUE",
        "PURCHASE_HISTORY",
        "REVENUE",
        "SPEND",
        "UPSELL_PROPENSITY",
    }
)


@dataclass(frozen=True, slots=True)
class InfluenceDecision:
    behavior: str
    reason: str
    relationship_inputs: tuple[str, ...] = ()
    commercial_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.behavior.strip():
            raise ValueError("behavior must be non-empty")
        if any(not value.strip() for value in self.relationship_inputs):
            raise ValueError("relationship inputs must be non-empty")
        if any(not value.strip() for value in self.commercial_inputs):
            raise ValueError("commercial inputs must be non-empty")


@dataclass(frozen=True, slots=True)
class MemoryEvidenceRecord:
    record_id: str
    evidence_type: MemoryEvidenceType
    claim: str
    source_locator: str
    status: str
    supersedes: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("record_id must be non-empty")
        if not isinstance(self.evidence_type, MemoryEvidenceType):
            raise ValueError("evidence_type must be a MemoryEvidenceType")
        if not self.claim.strip():
            raise ValueError("claim must be non-empty")
        if not self.source_locator.strip():
            raise ValueError("source_locator must be non-empty")
        if self.status not in {"ACTIVE", "SUPERSEDED", "DISPUTED"}:
            raise ValueError("unsupported memory evidence status")
        if len(set(self.supersedes)) != len(self.supersedes):
            raise ValueError("supersedes contains duplicates")
        if len(set(self.conflicts_with)) != len(self.conflicts_with):
            raise ValueError("conflicts_with contains duplicates")
        if self.record_id in self.supersedes or self.record_id in self.conflicts_with:
            raise ValueError("memory record cannot reference itself")


def validate_influence_decision(decision: InfluenceDecision) -> bool:
    """Enforce the relationship/commercial influence firewall.

    Protected relationship behavior may depend on bounded relationship state,
    but never on spend, churn, conversion, or similar commercial signals.
    """
    behavior = decision.behavior.strip().upper()
    commercial = {value.strip().upper() for value in decision.commercial_inputs}
    relationship = {value.strip().upper() for value in decision.relationship_inputs}
    unknown_commercial = commercial - _COMMERCIAL_SIGNAL_CLASSES
    if unknown_commercial:
        raise ValueError(
            "unknown commercial signal class: "
            + ", ".join(sorted(unknown_commercial))
        )

    misclassified_commercial = relationship & _COMMERCIAL_SIGNAL_CLASSES
    if misclassified_commercial:
        raise ValueError(
            "commercial signals cannot be supplied as relationship inputs: "
            + ", ".join(sorted(misclassified_commercial))
        )

    if behavior in _PROTECTED_RELATIONSHIP_BEHAVIORS and commercial:
        raise ValueError(
            "commercial signals cannot shape protected relationship behavior"
        )

    if behavior == "INITIATIVE" and not decision.reason.strip():
        raise ValueError("initiative requires a traceable reason")

    return True


def validate_memory_reconciliation(
    prior: MemoryEvidenceRecord,
    candidate: MemoryEvidenceRecord,
) -> bool:
    """Enforce provenance-preserving memory reconciliation.

    Relationship inference can remain useful behavioral state, but it cannot
    silently overwrite an explicit user statement. Corrections/conflicts must
    be represented through explicit lineage links.
    """
    if prior.record_id == candidate.record_id:
        raise ValueError("candidate must have a new record_id")

    supersedes_prior = prior.record_id in candidate.supersedes
    conflicts_with_prior = prior.record_id in candidate.conflicts_with

    if supersedes_prior and conflicts_with_prior:
        raise ValueError("a candidate cannot both supersede and conflict with prior")

    if (
        supersedes_prior
        and prior.evidence_type is MemoryEvidenceType.USER_STATED
        and candidate.evidence_type
        in {
            MemoryEvidenceType.INFERRED_RELATIONSHIP_STATE,
            MemoryEvidenceType.DERIVED_SUMMARY,
        }
    ):
        raise ValueError(
            "inference or derived summary cannot silently supersede USER_STATED evidence"
        )

    if (
        prior.claim != candidate.claim
        and candidate.evidence_type is MemoryEvidenceType.EXTERNAL_IMPORTED
        and not supersedes_prior
        and not conflicts_with_prior
    ):
        raise ValueError(
            "conflicting imported evidence requires explicit supersession or conflict"
        )

    return True
