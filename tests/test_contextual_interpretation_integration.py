from __future__ import annotations

import json
from pathlib import Path

import pytest

import vera_identity


def _semantic_node(object_id: str = "NODE-99999999-9999-4999-8999-999999999999"):
    return {
        "schema_version": "0.1",
        "object_type": "node",
        "id": object_id,
        "primary_label": "contextual referent",
        "aliases": [],
        "node_kind": "concept",
        "notes": None,
    }


def _reading(interpretation_id: str, object_id: str, meaning: str):
    return vera_identity.ContextualInterpretation(
        interpretation_id=interpretation_id,
        object_id=object_id,
        meaning=meaning,
        source_ref=f"source:{interpretation_id}",
        required_context=frozenset({"domain:test"}),
        excluded_context=frozenset(),
    )


def test_contextual_public_api_is_exported_from_vera_identity():
    for name in (
        "ContextualInterpretation",
        "InterpretationRelation",
        "InterpretationRelationKind",
        "ContextualInterpretationResult",
        "ContextualAdmissionReceipt",
        "ContextualInterpretationStore",
        "ContextualInterpretationConflict",
        "ContextualInterpretationError",
        "ContextualSemanticView",
        "query_semantic_interpretations",
    ):
        assert hasattr(vera_identity, name), name


def test_semantic_integration_preserves_multiple_readings_without_mutation(tmp_path):
    semantic = vera_identity.SemanticKnowledgeStore(tmp_path / "semantic.db")
    contextual = vera_identity.ContextualInterpretationStore(tmp_path / "contextual.db")
    node = _semantic_node()
    semantic.admit(node)
    contextual.admit_interpretation(_reading("INT-A", node["id"], "meaning A"))
    contextual.admit_interpretation(_reading("INT-B", node["id"], "meaning B"))

    before = contextual.list_interpretations(node["id"])
    view = vera_identity.query_semantic_interpretations(
        semantic,
        contextual,
        node["id"],
        {"domain:test"},
    )
    after = contextual.list_interpretations(node["id"])

    assert view.semantic_object == node
    assert [
        result.interpretation.interpretation_id for result in view.interpretations
    ] == ["INT-A", "INT-B"]
    assert before == after
    assert semantic.get(node["id"]) == node
    assert not hasattr(view, "truth_effect")
    assert not hasattr(view, "authority_effect")


def test_semantic_integration_fails_closed_on_unknown_referent():
    semantic = vera_identity.SemanticKnowledgeStore()
    contextual = vera_identity.ContextualInterpretationStore()
    contextual.admit_interpretation(
        _reading("INT-A", "NODE-MISSING", "orphan reading")
    )
    with pytest.raises(KeyError):
        vera_identity.query_semantic_interpretations(
            semantic,
            contextual,
            "NODE-MISSING",
            {"domain:test"},
        )


def test_semiotics_donor_provenance_binds_exact_source_and_claim_ceiling():
    path = (
        Path(__file__).parents[1]
        / "provenance"
        / "donors"
        / "semiotics_contextual_interpretation_v1.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["schema"] == "VERA_MONO_DONOR_ADAPTATION_V1"
    assert value["donor_repository"] == "thebrazenbeard/semiotics"
    assert value["donor_head"] == "37117a2097f7f2aa35968fc9db24eacf7240826e"
    assert (
        value["adaptation"]["target"]
        == "packages/vera_identity/src/vera_identity/contextual_interpretation.py"
    )
    assert value["adaptation"]["donor_runtime_dependency"] is False
    assert "source-bound competing interpretations" in value["adaptation"]["adapted_concepts"]
    assert "donor runtime" in value["adaptation"]["excluded_scope"]
    assert value["claim_ceiling"] == (
        "VERA_NATIVE_CONTEXTUAL_INTERPRETATION_REPRESENTATION_AND_DETERMINISTIC_QUERY_ONLY; "
        "NOT_LEARNED_SEMANTICS; NOT_TRUTH_ADJUDICATION; "
        "NOT_RUNTIME_CONSUMPTION_BY_SOURCE_PRESENCE; "
        "NOT_INDEPENDENT_QUALIFICATION; NOT_AGI"
    )
