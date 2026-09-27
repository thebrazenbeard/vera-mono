from vera_assurance.causal_ambiguity import (
    AmbiguityRoute,
    CausalHypothesis,
    assess_causal_ambiguity,
    route_causal_ambiguity,
)


def test_causal_ambiguity_blocks_close_competitors_and_routes_missing_evidence():
    close = assess_causal_ambiguity(
        (
            CausalHypothesis(
                hypothesis_id="h1",
                proposition="cause one",
                support=0.82,
                evidence_refs=("e:1",),
            ),
            CausalHypothesis(
                hypothesis_id="h2",
                proposition="cause two",
                support=0.76,
                evidence_refs=("e:2",),
            ),
        ),
        missing_evidence=("trace:42",),
    )

    assert close.ambiguous is True
    assert close.decision_margin == 0.06
    assert close.authorization_effect == "NONE"
    assert route_causal_ambiguity(
        close,
        human_review_when_missing_evidence=True,
    ) is AmbiguityRoute.HUMAN_REVIEW

    separated = assess_causal_ambiguity(
        (
            CausalHypothesis("h1", "cause one", 0.91, ("e:1",)),
            CausalHypothesis("h2", "cause two", 0.50, ("e:2",)),
        )
    )
    assert separated.ambiguous is False
    assert separated.top.hypothesis_id == "h1"
    assert route_causal_ambiguity(separated) is AmbiguityRoute.PROCEED_TO_CORRECTION
