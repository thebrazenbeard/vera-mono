from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProvenancePreflightStatus(StrEnum):
    """A host-supplied read-only roots lookup result, never an authority grant."""

    NOT_REQUIRED = "NOT_REQUIRED"
    SEARCHED = "SEARCHED"
    UNAVAILABLE = "UNAVAILABLE"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ProvenancePreflight:
    """Metadata receipt from a caller-owned, pre-answer roots lookup.

    The caller performs candidate detection and any authorized search. The
    console cannot authenticate the provider, make memory admissions, or infer
    whether a source is current merely because this receipt exists.
    """

    status: ProvenancePreflightStatus
    candidate_refs: tuple[str, ...] = ()
    source_repository: str = "thebrazenbeard/roots"
    source_head: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProvenancePreflightStatus):
            raise TypeError("status must be ProvenancePreflightStatus")
        if type(self.source_repository) is not str or self.source_repository != "thebrazenbeard/roots":
            raise ValueError("source_repository must be the exact roots repository")
        if type(self.candidate_refs) is not tuple or any(
            type(item) is not str or not item.strip()
            for item in self.candidate_refs
        ):
            raise ValueError("candidate_refs must be a tuple of nonempty source references")
        if self.source_head is not None and (
            type(self.source_head) is not str or not self.source_head.strip()
        ):
            raise ValueError("source_head must be null or nonempty")
        if self.status is not ProvenancePreflightStatus.SEARCHED and (
            self.candidate_refs or self.source_head is not None
        ):
            raise ValueError("only SEARCHED can carry retrieved source metadata")

    @property
    def answer_may_continue(self) -> bool:
        return self.status in {
            ProvenancePreflightStatus.NOT_REQUIRED,
            ProvenancePreflightStatus.SEARCHED,
        }
