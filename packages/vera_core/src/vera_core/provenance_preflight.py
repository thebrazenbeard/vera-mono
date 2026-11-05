from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


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
    source_repository: str = "roots"
    source_head: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProvenancePreflightStatus):
            raise TypeError("status must be ProvenancePreflightStatus")
        if (
            type(self.source_repository) is not str
            or self.source_repository != "roots"
        ):
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



@dataclass(frozen=True, slots=True)
class RootsSearchResult:
    """Caller-verified candidate references; does not assert factual truth."""

    candidate_refs: tuple[str, ...] = ()
    source_head: str | None = None


def build_roots_preflight(
    *,
    resolve_trigger: Callable[[str], object],
    search_candidates: Callable[[str, str], RootsSearchResult],
) -> Callable[[str], ProvenancePreflight]:
    """Compose the Roots candidate detector with a read-only search provider.

    The detector's recognized status and hit shape match the optional
    roots.triggers.resolve_provenance_trigger source contract. This module
    deliberately does not import Roots or assume it is installed/current.

    search_candidates is an injected, host-authorized Roots search; it sees
    only the matched rule's bounded query and scope, never the full user text.
    Its result is evidence metadata, not admission or response content.
    """
    if not callable(resolve_trigger) or not callable(search_candidates):
        raise TypeError("roots detector and search provider must be callable")

    def preflight(text: str) -> ProvenancePreflight:
        try:
            decision = resolve_trigger(text)
            status = getattr(decision, "status", None)
            status = getattr(status, "value", status)
            if status == "NO_TRIGGER":
                return ProvenancePreflight(
                    status=ProvenancePreflightStatus.NOT_REQUIRED,
                )
            if status == "AMBIGUOUS":
                return ProvenancePreflight(
                    status=ProvenancePreflightStatus.AMBIGUOUS,
                )
            if status != "LOOKUP_REQUESTED":
                return ProvenancePreflight(
                    status=ProvenancePreflightStatus.UNAVAILABLE,
                )

            hits = getattr(decision, "hits", None)
            if type(hits) is not tuple or len(hits) != 1:
                return ProvenancePreflight(
                    status=ProvenancePreflightStatus.AMBIGUOUS,
                )
            hit = hits[0]
            query = getattr(hit, "query", None)
            scope_key = getattr(hit, "scope_key", None)
            if (
                type(query) is not str or not query.strip()
                or len(query) > 256
                or type(scope_key) is not str or not scope_key.strip()
                or len(scope_key) > 128
            ):
                return ProvenancePreflight(
                    status=ProvenancePreflightStatus.UNAVAILABLE,
                )
            searched = search_candidates(query, scope_key)
            if type(searched) is not RootsSearchResult:
                raise TypeError("Roots search provider returned malformed result")
            return ProvenancePreflight(
                status=ProvenancePreflightStatus.SEARCHED,
                candidate_refs=searched.candidate_refs,
                source_head=searched.source_head,
            )
        except Exception:
            # Host errors and unavailable Roots are not memory search receipts.
            return ProvenancePreflight(
                status=ProvenancePreflightStatus.UNAVAILABLE,
            )

    return preflight
