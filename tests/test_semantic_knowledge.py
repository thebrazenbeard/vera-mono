import vera_identity


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
        reopened.admit(changed)
    except SemanticKnowledgeConflict:
        pass
    else:
        raise AssertionError("semantic object id was rebound")
    assert first.authority_effect == "NONE"
    assert first.truth_effect == "NONE"
