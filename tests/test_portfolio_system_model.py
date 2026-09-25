import pytest

from vera_core.portfolio_system_model import (
    PortfolioFactDisposition,
    PortfolioSystemFact,
    PortfolioSystemModel,
)


def test_discovered_system_model_is_deterministic_and_cannot_mint_authority():
    first = PortfolioSystemFact(
        fact_id="repo:tests",
        kind="test_surface",
        key="tests/",
        value=True,
        disposition=PortfolioFactDisposition.OBSERVED_SOURCE,
        provenance="github:tree",
    )
    second = PortfolioSystemFact(
        fact_id="repo:ci",
        kind="ci_surface",
        key=".github/workflows/tests.yml",
        value="present",
        disposition=PortfolioFactDisposition.EXECUTABLE_CONFIGURATION,
        provenance="github:blob:abc",
    )

    left = PortfolioSystemModel()
    left.add_discovered_fact(first)
    left.add_discovered_fact(second)

    right = PortfolioSystemModel()
    right.add_discovered_fact(second)
    right.add_discovered_fact(first)

    assert left.digest == right.digest
    assert left.to_dict()["digest"] == left.digest

    with pytest.raises(ValueError, match="discovery cannot manufacture authorization"):
        left.add_discovered_fact(
            PortfolioSystemFact(
                fact_id="repo:deploy-authority",
                kind="capability",
                key="deploy",
                value=True,
                disposition=PortfolioFactDisposition.AUTHORIZED_CAPABILITY,
                provenance="README.md",
            )
        )
