from __future__ import annotations

import pytest

from vera_core.semantic_transfer import (
    SemanticCapabilityProfile,
    SemanticTransferRule,
    TransferFidelity,
    plan_semantic_transfer,
)


def _profile(profile_id: str, *capabilities: str) -> SemanticCapabilityProfile:
    return SemanticCapabilityProfile(
        profile_id=profile_id,
        capabilities=frozenset(capabilities),
    )


def test_semantic_transfer_is_exact_when_target_natively_covers_requirements():
    plan = plan_semantic_transfer(
        _profile("source", "relational", "json"),
        _profile("target", "relational", "json", "vector"),
        {"relational", "json"},
    )
    assert plan.fidelity is TransferFidelity.EXACT
    assert plan.native_capabilities == frozenset({"relational", "json"})
    assert plan.unresolved_capabilities == frozenset()
    assert plan.semantic_equivalence == "NOT_ESTABLISHED"
    assert plan.authorization_effect == "NONE"


def test_semantic_transfer_uses_best_available_rewrite_and_reports_loss():
    rules = (
        SemanticTransferRule(
            name="json-via-document",
            source_capability="json",
            target_capabilities=frozenset({"document"}),
            fidelity=TransferFidelity.CONSTRUCTIVE,
            description="Represent JSON semantics through a document capability.",
        ),
        SemanticTransferRule(
            name="graph-via-relational",
            source_capability="graph",
            target_capabilities=frozenset({"relational"}),
            fidelity=TransferFidelity.LOSSY,
            description="Project graph structure into relations with known semantic loss.",
        ),
    )
    plan = plan_semantic_transfer(
        _profile("source", "json", "graph"),
        _profile("target", "document", "relational"),
        {"json", "graph"},
        rules=rules,
    )
    assert plan.fidelity is TransferFidelity.LOSSY
    assert [item.rule_name for item in plan.rewrites] == [
        "graph-via-relational",
        "json-via-document",
    ]
    assert plan.unresolved_capabilities == frozenset()


def test_semantic_transfer_fails_closed_when_requirement_is_unrepresentable():
    plan = plan_semantic_transfer(
        _profile("source", "temporal"),
        _profile("target", "relational"),
        {"temporal"},
    )
    assert plan.fidelity is TransferFidelity.UNREPRESENTABLE
    assert plan.unresolved_capabilities == frozenset({"temporal"})
    assert plan.semantic_equivalence == "NOT_ESTABLISHED"
    assert plan.authorization_effect == "NONE"


def test_semantic_transfer_rejects_requirement_not_admitted_by_source():
    with pytest.raises(ValueError, match="SOURCE_CAPABILITY_NOT_ADMITTED:vector"):
        plan_semantic_transfer(
            _profile("source", "relational"),
            _profile("target", "vector"),
            {"vector"},
        )


def test_semantic_transfer_prefers_lower_loss_then_stable_rule_name():
    rules = (
        SemanticTransferRule(
            name="z-lossy",
            source_capability="semantic-x",
            target_capabilities=frozenset({"base"}),
            fidelity=TransferFidelity.LOSSY,
            description="Lossy fallback.",
        ),
        SemanticTransferRule(
            name="b-constructive",
            source_capability="semantic-x",
            target_capabilities=frozenset({"base"}),
            fidelity=TransferFidelity.CONSTRUCTIVE,
            description="Constructive B.",
        ),
        SemanticTransferRule(
            name="a-constructive",
            source_capability="semantic-x",
            target_capabilities=frozenset({"base"}),
            fidelity=TransferFidelity.CONSTRUCTIVE,
            description="Constructive A.",
        ),
    )
    plan = plan_semantic_transfer(
        _profile("source", "semantic-x"),
        _profile("target", "base"),
        {"semantic-x"},
        rules=rules,
    )
    assert plan.fidelity is TransferFidelity.CONSTRUCTIVE
    assert plan.rewrites[0].rule_name == "a-constructive"