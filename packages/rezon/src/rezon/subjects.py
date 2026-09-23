from __future__ import annotations

from dataclasses import dataclass


class SubjectBindingError(ValueError):
    pass


@dataclass(frozen=True)
class SubjectBinding:
    subject_id: str
    observation_refs: tuple[str, ...] = ()
    association_evidence_refs: tuple[str, ...] = ()
    advisory_similarity_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise SubjectBindingError("subject_id is required")
        if self.observation_refs and not self.association_evidence_refs:
            raise SubjectBindingError(
                "observations cannot bind to a persistent subject without association evidence"
            )
