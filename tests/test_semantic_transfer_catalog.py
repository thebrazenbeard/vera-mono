from __future__ import annotations

from vera_core.semantic_transfer import (
    SemanticCapabilityProfile,
    SemanticTransferCatalog,
    SemanticTransferRule,
    TransferFidelity,
    plan_catalog_semantic_transfer,
)


def test_catalog_bound_transfer_receipt_carries_exact_catalog_digest():
    source = SemanticCapabilityProfile(
        profile_id="source",
        capabilities=frozenset({"graph"}),
    )
    target = SemanticCapabilityProfile(
        profile_id="target",
        capabilities=frozenset({"relational"}),
    )
    rule = SemanticTransferRule(
        name="graph-via-relational",
        source_capability="graph",
        target_capabilities=frozenset({"relational"}),
        fidelity=TransferFidelity.LOSSY,
        description="Project graph structure into relations with known semantic loss.",
    )
    catalog = SemanticTransferCatalog(
        catalog_id="vera-semantic-v1",
        profiles=(source, target),
        rules=(rule,),
    )

    plan = plan_catalog_semantic_transfer(
        catalog,
        "source",
        "target",
        {"graph"},
    )

    assert plan.catalog_id == "vera-semantic-v1"
    assert plan.catalog_digest == catalog.digest
    assert len(plan.catalog_digest) == 64
    assert plan.as_dict()["catalog_digest"] == catalog.digest
    assert plan.authorization_effect == "NONE"
