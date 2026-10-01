import pytest

from vera_core.rival_hypotheses import (
    RivalEvidence,
    RivalHypothesis,
    RivalHypothesisError,
    RivalResolutionState,
    resolve_rival_hypotheses,
)


H1 = RivalHypothesis("h1", "first explanation")
H2 = RivalHypothesis("h2", "second explanation")


def test_single_supported_survivor_is_supported():
    result = resolve_rival_hypotheses(
        (H1, H2),
        (
            RivalEvidence(
                "e1",
                "independent-a",
                supports=frozenset({"h1"}),
            ),
            RivalEvidence(
                "e2",
                "independent-b",
                contradicts=frozenset({"h2"}),
            ),
        ),
    )

    assert result.state is RivalResolutionState.SUPPORTED
    assert result.winner == "h1"
    assert result.live_hypotheses == ("h1",)
    assert result.discriminating_need == ()


def test_multiple_live_rivals_remain_unresolved():
    result = resolve_rival_hypotheses(
        (H1, H2),
        (
            RivalEvidence(
                "e1",
                "same-source",
                supports=frozenset({"h1"}),
            ),
        ),
    )

    assert result.state is RivalResolutionState.UNRESOLVED
    assert result.winner is None
    assert result.discriminating_need == ("h1", "h2")


def test_support_is_deduplicated_by_independence_group():
    result = resolve_rival_hypotheses(
        (H1,),
        (
            RivalEvidence("e1", "same", supports=frozenset({"h1"})),
            RivalEvidence("e2", "same", supports=frozenset({"h1"})),
        ),
    )

    assert result.assessments[0].support_groups == ("same",)


def test_all_contradicted_returns_conflict_not_forced_winner():
    result = resolve_rival_hypotheses(
        (H1, H2),
        (
            RivalEvidence(
                "e1",
                "a",
                contradicts=frozenset({"h1"}),
            ),
            RivalEvidence(
                "e2",
                "b",
                contradicts=frozenset({"h2"}),
            ),
        ),
    )

    assert result.state is RivalResolutionState.CONFLICT
    assert result.winner is None
    assert result.discriminating_need == (
        "expand_or_repair_hypothesis_set",
    )


def test_inadmissible_evidence_cannot_promote_or_eliminate():
    result = resolve_rival_hypotheses(
        (H1, H2),
        (
            RivalEvidence(
                "e1",
                "a",
                supports=frozenset({"h1"}),
                contradicts=frozenset({"h2"}),
                admissible=False,
            ),
        ),
    )

    assert result.state is RivalResolutionState.UNRESOLVED
    assert all(not item.eliminated for item in result.assessments)


def test_unknown_hypothesis_reference_fails_closed():
    with pytest.raises(RivalHypothesisError):
        resolve_rival_hypotheses(
            (H1,),
            (
                RivalEvidence(
                    "e1",
                    "a",
                    supports=frozenset({"missing"}),
                ),
            ),
        )
