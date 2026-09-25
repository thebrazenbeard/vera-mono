import pytest

from vera_core.reuse_admission import (
    HostileReview,
    ReuseCandidate,
    ReuseCandidateState,
    ReuseConsumer,
    ReusePromotionError,
)


def test_reusable_candidate_requires_independent_exact_consumers_and_clean_review():
    candidate = ReuseCandidate(
        candidate_id="shared-cas",
        state=ReuseCandidateState.EXPERIMENTING,
        consumers=(
            ReuseConsumer("repo-a", "main@" + "a" * 40, independence_ref="lineage:a"),
            ReuseConsumer("repo-b", "main@" + "b" * 40, independence_ref="lineage:b"),
        ),
        promotion_evidence=("receipt:a", "receipt:b"),
        rollback_ref="rollback:shared-cas-v1",
        bounded_blast_radius=True,
        hostile_review=HostileReview(status="PASS", critical_objections=()),
    )

    proven = candidate.promote_proven_reusable()
    assert proven.state is ReuseCandidateState.PROVEN_REUSABLE
    assert proven.authorization_effect == "NONE"

    with pytest.raises(ReusePromotionError):
        ReuseCandidate(
            candidate_id="one-consumer",
            state=ReuseCandidateState.EXPERIMENTING,
            consumers=(ReuseConsumer("repo-a", "main@" + "a" * 40),),
            promotion_evidence=("receipt:a", "receipt:b"),
            rollback_ref="rollback:one",
            bounded_blast_radius=True,
            hostile_review=HostileReview(status="PASS", critical_objections=()),
        ).promote_proven_reusable()

    with pytest.raises(ReusePromotionError):
        ReuseCandidate(
            candidate_id="dirty-review",
            state=ReuseCandidateState.EXPERIMENTING,
            consumers=(
                ReuseConsumer("repo-a", "main@" + "a" * 40),
                ReuseConsumer("repo-b", "main@" + "b" * 40),
            ),
            promotion_evidence=("receipt:a", "receipt:b"),
            rollback_ref="rollback:dirty",
            bounded_blast_radius=True,
            hostile_review=HostileReview(
                status="PASS_WITH_LIMITS",
                critical_objections=("semantic coupling remains",),
            ),
        ).promote_proven_reusable()


def test_reusable_promotion_requires_distinct_independence_evidence():
    candidate = ReuseCandidate(
        candidate_id="not-actually-independent",
        state=ReuseCandidateState.EXPERIMENTING,
        consumers=(
            ReuseConsumer(
                "repo-a",
                "main@" + "a" * 40,
                independence_ref="lineage:same",
            ),
            ReuseConsumer(
                "repo-b",
                "main@" + "b" * 40,
                independence_ref="lineage:same",
            ),
        ),
        promotion_evidence=("receipt:a", "receipt:b"),
        rollback_ref="rollback:test",
        bounded_blast_radius=True,
        hostile_review=HostileReview(status="PASS", critical_objections=()),
    )
    with pytest.raises(ReusePromotionError, match="independence"):
        candidate.promote_proven_reusable()
