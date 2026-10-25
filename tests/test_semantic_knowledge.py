import vera_identity
import sqlite3
from unittest.mock import patch

import pytest


def test_semantic_knowledge_store_is_available():
    assert hasattr(vera_identity, "SemanticKnowledgeStore")


def test_semantic_knowledge_store_exposes_admission_boundary():
    assert hasattr(vera_identity.SemanticKnowledgeStore, "admit")


def test_semantic_node_admission_returns_a_receipt():
    store = vera_identity.SemanticKnowledgeStore()
    node = {
        "schema_version": "0.1",
        "object_type": "node",
        "id": "NODE-11111111-1111-4111-8111-111111111111",
        "primary_label": "adaptive learning",
        "aliases": ["continual adaptation"],
        "node_kind": "concept",
        "notes": None,
    }
    assert store.check_admissible(node) is None
    try:
        store.get(node["id"])
    except KeyError:
        pass
    else:
        raise AssertionError("semantic preflight silently wrote the node")
    assert store.admit(node) is not None


def test_semantic_store_persists_and_rejects_id_rebinding(tmp_path):
    from vera_identity.semantic_knowledge import SemanticKnowledgeConflict
    path = tmp_path / "semantic.db"
    node = {
        "schema_version": "0.1",
        "object_type": "node",
        "id": "NODE-22222222-2222-4222-8222-222222222222",
        "primary_label": "provenance",
        "aliases": [],
        "node_kind": "concept",
        "notes": None,
    }
    first = vera_identity.SemanticKnowledgeStore(path).admit(node)
    assert first.status == "ACCEPTED"
    reopened = vera_identity.SemanticKnowledgeStore(path)
    assert reopened.get(node["id"]) == node
    assert reopened.admit(node).status == "DUPLICATE"
    changed = dict(node, primary_label="rewritten provenance")
    try:
        reopened.check_admissible(changed)
    except SemanticKnowledgeConflict:
        pass
    else:
        raise AssertionError("read-only preflight permitted semantic id rebinding")
    try:
        reopened.admit(changed)
    except SemanticKnowledgeConflict:
        pass
    else:
        raise AssertionError("semantic object id was rebound")
    assert first.authority_effect == "NONE"
    assert first.truth_effect == "NONE"


def test_file_backed_semantic_store_closes_all_sqlite_connections(tmp_path):
    """Windows must be able to remove the semantic DB after a closed-loop run."""
    import vera_identity.semantic_knowledge as module

    real_connect = sqlite3.connect
    opened = []

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    with patch.object(module.sqlite3, "connect", side_effect=tracked_connect):
        path = tmp_path / "semantic.db"
        store = module.SemanticKnowledgeStore(path)
        node = {
            "schema_version": "0.1",
            "object_type": "node",
            "id": "NODE-33333333-3333-4333-8333-333333333333",
            "primary_label": "safe cleanup",
            "aliases": [],
            "node_kind": "concept",
            "notes": None,
        }
        store.check_admissible(node)
        store.admit(node)
        assert store.get(node["id"]) == node
        assert len(store.list_type("node")) == 1

    assert len(opened) >= 5
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
