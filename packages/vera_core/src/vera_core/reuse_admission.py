"""Evidence-gated promotion for reusable portfolio mechanisms.

Adapted from Discovery's candidate lifecycle. Reuse suitability is a bounded
source-governance claim; it grants no installation, runtime, or effect authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import re


_EXACT_SUBJECT = re.compile(r"^(?:[A-Za-z0-9._/-]+@)?[0-9a-f]{40}$")


class ReusePromotionError(ValueError):
    pass


class ReuseCandidateState(StrEnum):
    OBSERVED = "OBSERVED"
    HYPOTHESIS = "HYPOTHESIS"
    EXPERIMENTING = "EXPERIMENTING"
    PROVEN_REUSABLE = "PROVEN_REUSABLE"
    PROJECT_SPECIFIC = "PROJECT_SPECIFIC"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class HostileReview:
    status: str
    critical_objections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not str or not self.status:
            raise ValueError("hostile review status must be a non-empty exact string")
        object.__setattr__(self, "critical_objections", tuple(self.critical_objections))
        if any(type(item) is not str or not item for item in self.critical_objections):
            raise ValueError("critical objections must be non-empty exact strings")


@dataclass(frozen=True, slots=True)
class ReuseConsumer:
    repository: str
    exact_subject: str | None
    visibility: str = "PUBLIC"

    def __post_init__(self) -> None:
        if type(self.repository) is not str or not self.repository:
            raise ValueError("consumer repository must be a non-empty exact string")
        if self.visibility not in {"PUBLIC", "PRIVATE_OPAQUE"}:
            raise ValueError("consumer visibility must be PUBLIC or PRIVATE_OPAQUE")
        if self.visibility == "PUBLIC":
            if type(self.exact_subject) is not str or not _EXACT_SUBJECT.fullmatch(
                self.exact_subject
            ):
                raise ValueError("public consumer requires an exact commit subject")
        elif self.exact_subject is not None:
            raise ValueError("opaque private consumer must not expose a raw subject")


@dataclass(frozen=True, slots=True)
class ReuseCandidate:
    candidate_id: str
    state: ReuseCandidateState
    consumers: tuple[ReuseConsumer, ...] = ()
    promotion_evidence: tuple[str, ...] = ()
    rollback_ref: str | None = None
    bounded_blast_radius: bool = False
    hostile_review: HostileReview | None = None
    authorization_effect: str = "NONE"

    def __post_init__(self) -> None:
        if type(self.candidate_id) is not str or not self.candidate_id:
            raise ValueError("candidate_id must be a non-empty exact string")
        if type(self.state) is not ReuseCandidateState:
            raise TypeError("state must be exact ReuseCandidateState")
        object.__setattr__(self, "consumers", tuple(self.consumers))
        object.__setattr__(self, "promotion_evidence", tuple(self.promotion_evidence))
        if any(type(item) is not ReuseConsumer for item in self.consumers):
            raise TypeError("consumers must contain exact ReuseConsumer values")
        if any(type(item) is not str or not item for item in self.promotion_evidence):
            raise ValueError("promotion evidence must be non-empty exact strings")
        if self.authorization_effect != "NONE":
            raise ValueError("reuse admission cannot mint authorization")

    def promote_proven_reusable(self) -> "ReuseCandidate":
        if self.state is not ReuseCandidateState.EXPERIMENTING:
            raise ReusePromotionError(
                "PROVEN_REUSABLE promotion requires EXPERIMENTING state"
            )
        if len(self.consumers) < 2:
            raise ReusePromotionError(
                "PROVEN_REUSABLE requires at least two real consumers"
            )
        if any(consumer.visibility != "PUBLIC" for consumer in self.consumers):
            raise ReusePromotionError(
                "PROVEN_REUSABLE cannot rely on opaque private consumers"
            )
        identities = {
            (consumer.repository, consumer.exact_subject)
            for consumer in self.consumers
        }
        repositories = {consumer.repository for consumer in self.consumers}
        if len(identities) != len(self.consumers) or len(repositories) < 2:
            raise ReusePromotionError(
                "PROVEN_REUSABLE consumers must be materially independent"
            )
        if len(set(self.promotion_evidence)) < 2:
            raise ReusePromotionError(
                "PROVEN_REUSABLE requires independent promotion evidence"
            )
        if type(self.rollback_ref) is not str or not self.rollback_ref:
            raise ReusePromotionError("PROVEN_REUSABLE requires rollback evidence")
        if self.bounded_blast_radius is not True:
            raise ReusePromotionError(
                "PROVEN_REUSABLE requires a bounded blast radius"
            )
        if self.hostile_review is None:
            raise ReusePromotionError(
                "PROVEN_REUSABLE requires a hostile review"
            )
        if (
            self.hostile_review.status != "PASS"
            or self.hostile_review.critical_objections
        ):
            raise ReusePromotionError(
                "PROVEN_REUSABLE requires a clean hostile-review PASS"
            )
        return replace(self, state=ReuseCandidateState.PROVEN_REUSABLE)
