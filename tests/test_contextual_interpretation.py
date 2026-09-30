from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json

import pytest


MODULE = "vera_identity.contextual_interpretation"


def _ci():
    return importlib.import_module(MODULE)


def _reading(**changes):
    ci = _ci()
    values = {
        "interpretation_id": "INT-001",
        "object_id": "NODE-001",
        "meaning": "contextual meaning",
        "source_ref": "source:one",
        "required_context": frozenset({"domain:test"}),
        "excluded_context": frozenset({"mode:legacy"}),
    }
    values.update(changes)
    return ci.ContextualInterpretation(**values)


def test_contextual_interpretation_module_exists():
    assert importlib.util.find_spec(MODULE) is not None


@pytest.mark.skipif(importlib.util.find_spec(MODULE) is None, reason="module not implemented")
def test_interpretation_validates_exact_nonempty_strings_and_context_overlap():
    ci = _ci()
    for field in ("interpretation_id", "object_id", "meaning", "source_ref"):
        with pytest.raises(ci.ContextualInterpretationError):
            _reading(**{field: "   "})
    with pytest.raises(ci.ContextualInterpretationError):
        _reading(required_context=frozenset({"same"}), excluded_context=frozenset({"same"}))
    with pytest.raises(ci.ContextualInterpretationError):
        _reading(required_context=frozenset({"ok", "   "}))


@pytest.mark.skipif(importlib.util.find_spec(MODULE) is None, reason="module not implemented")
def test_interpretation_specificity_counts_required_and_excluded_atoms():
    reading = _reading(
        required_context=frozenset({"a", "b"}),
        excluded_context=frozenset({"c"}),
    )
    assert reading.specificity == 3


@pytest.mark.skipif(importlib.util.find_spec(MODULE) is None, reason="module not implemented")
def test_store_admission_is_durable_idempotent_and_conflict_safe(tmp_path):
    ci = _ci()
    path = tmp_path / "contextual.db"
    reading = _reading()
    first = ci.ContextualInterpretationStore(path).admit_interpretation(reading)
    assert first.status == "ACCEPTED"
    expected_payload = {
        "excluded_context": ["mode:legacy"],
        "interpretation_id": "INT-001",
        "meaning": "contextual meaning",
        "object_id": "NODE-001",
        "required_context": ["domain:test"],
        "source_ref": "source:one",
        "supersedes_id": None,
    }
    canonical = json.dumps(
        expected_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert first.digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert first.record_id == reading.interpretation_id
    assert first.record_type == "INTERPRETATION"
    assert first.truth_effect == "NONE"
    assert first.authority_effect == "NONE"
    assert first.identity_effect == "NONE"

    reopened = ci.ContextualInterpretationStore(path)
    assert reopened.get_interpretation("INT-001") == reading
    assert reopened.admit_interpretation(reading).status == "DUPLICATE"

    changed = _reading(meaning="different")
    with pytest.raises(ci.ContextualInterpretationConflict):
        reopened.admit_interpretation(changed)


@pytest.mark.skipif(importlib.util.find_spec(MODULE) is None, reason="module not implemented")
def test_unknown_interpretation_raises_key_error_and_listing_is_stable():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    with pytest.raises(KeyError):
        store.get_interpretation("missing")
    store.admit_interpretation(_reading(interpretation_id="INT-B"))
    store.admit_interpretation(_reading(interpretation_id="INT-A"))
    assert [item.interpretation_id for item in store.list_interpretations("NODE-001")] == [
        "INT-A",
        "INT-B",
    ]


def _relation(**changes):
    ci = _ci()
    values = {
        "relation_id": "REL-001",
        "left_id": "INT-A",
        "right_id": "INT-B",
        "kind": ci.InterpretationRelationKind.CONTRADICTS,
        "source_ref": "source:relation",
    }
    values.update(changes)
    return ci.InterpretationRelation(**values)


def test_query_preserves_all_compatible_readings_and_orders_by_specificity():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-B",
            required_context=frozenset({"domain:test"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-A",
            required_context=frozenset({"domain:test", "mode:current"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-C",
            required_context=frozenset({"domain:test", "missing"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-D",
            required_context=frozenset({"domain:test"}),
            excluded_context=frozenset({"mode:current"}),
        )
    )

    results = store.query("NODE-001", {"domain:test", "mode:current"})
    assert [item.interpretation.interpretation_id for item in results] == [
        "INT-A",
        "INT-B",
    ]
    assert [item.specificity for item in results] == [2, 1]
    assert all(item.truth_effect == "NONE" for item in results)
    assert all(item.authority_effect == "NONE" for item in results)


def test_query_uses_stable_id_tie_break_without_collapsing_ambiguity():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    for interpretation_id in ("INT-Z", "INT-A"):
        store.admit_interpretation(
            _reading(
                interpretation_id=interpretation_id,
                required_context=frozenset({"x"}),
                excluded_context=frozenset(),
            )
        )
    results = store.query("NODE-001", frozenset({"x"}))
    assert [item.interpretation.interpretation_id for item in results] == [
        "INT-A",
        "INT-Z",
    ]


def test_query_rejects_malformed_context():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    with pytest.raises(ci.ContextualInterpretationError):
        store.query("NODE-001", ["not", "a", "set"])
    with pytest.raises(ci.ContextualInterpretationError):
        store.query("NODE-001", {"ok", "   "})


def test_supersession_is_same_referent_append_only_and_current_by_default():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-A",
            required_context=frozenset(),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-B",
            supersedes_id="INT-A",
            required_context=frozenset(),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-C",
            supersedes_id="INT-B",
            required_context=frozenset(),
            excluded_context=frozenset(),
        )
    )

    current = store.query("NODE-001", set())
    assert [item.interpretation.interpretation_id for item in current] == ["INT-C"]
    historical = store.query("NODE-001", set(), include_superseded=True)
    assert [item.interpretation.interpretation_id for item in historical] == [
        "INT-A",
        "INT-B",
        "INT-C",
    ]
    assert [item.is_current for item in historical] == [False, False, True]

    assert [
        item.interpretation_id
        for item in store.list_interpretations("NODE-001", include_superseded=False)
    ] == ["INT-C"]


def test_invalid_supersession_fails_without_partial_persistence():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    store.admit_interpretation(_reading(interpretation_id="INT-A"))
    with pytest.raises(ci.ContextualInterpretationError):
        store.admit_interpretation(
            _reading(interpretation_id="INT-SELF", supersedes_id="INT-SELF")
        )
    with pytest.raises(ci.ContextualInterpretationError):
        store.admit_interpretation(
            _reading(interpretation_id="INT-DANGLING", supersedes_id="MISSING")
        )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-OTHER",
            object_id="NODE-OTHER",
        )
    )
    with pytest.raises(ci.ContextualInterpretationError):
        store.admit_interpretation(
            _reading(
                interpretation_id="INT-CROSS",
                object_id="NODE-001",
                supersedes_id="INT-OTHER",
            )
        )
    assert [item.interpretation_id for item in store.list_interpretations("NODE-001")] == [
        "INT-A"
    ]


def test_cycle_attempt_via_id_rebinding_fails_and_preserves_original_history():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    store.admit_interpretation(_reading(interpretation_id="INT-A"))
    store.admit_interpretation(
        _reading(interpretation_id="INT-B", supersedes_id="INT-A")
    )
    with pytest.raises(ci.ContextualInterpretationConflict):
        store.admit_interpretation(
            _reading(interpretation_id="INT-A", supersedes_id="INT-B")
        )
    assert store.get_interpretation("INT-A").supersedes_id is None


def test_relations_are_durable_idempotent_and_validate_endpoints(tmp_path):
    ci = _ci()
    path = tmp_path / "relations.db"
    store = ci.ContextualInterpretationStore(path)
    store.admit_interpretation(_reading(interpretation_id="INT-A"))
    store.admit_interpretation(_reading(interpretation_id="INT-B"))
    relation = _relation()
    first = store.admit_relation(relation)
    assert first.status == "ACCEPTED"
    assert first.record_type == "RELATION"
    assert first.truth_effect == "NONE"
    assert store.admit_relation(relation).status == "DUPLICATE"
    assert ci.ContextualInterpretationStore(path).get_relation("REL-001") == relation

    with pytest.raises(ci.ContextualInterpretationConflict):
        store.admit_relation(_relation(source_ref="different"))
    with pytest.raises(ci.ContextualInterpretationError):
        store.admit_relation(_relation(relation_id="REL-MISSING", right_id="MISSING"))
    with pytest.raises(ci.ContextualInterpretationError):
        store.admit_relation(
            _relation(relation_id="REL-SELF", left_id="INT-A", right_id="INT-A")
        )


@pytest.mark.parametrize(
    "kind_name",
    ["CONTRASTS_WITH", "CONTRADICTS", "SUPPORTS", "REFINES"],
)
def test_all_relation_kinds_round_trip(kind_name):
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    store.admit_interpretation(_reading(interpretation_id="INT-A"))
    store.admit_interpretation(_reading(interpretation_id="INT-B"))
    kind = getattr(ci.InterpretationRelationKind, kind_name)
    relation = _relation(relation_id=f"REL-{kind_name}", kind=kind)
    store.admit_relation(relation)
    assert store.get_relation(relation.relation_id).kind is kind


def test_relations_attach_as_metadata_without_expanding_or_reordering_query():
    ci = _ci()
    store = ci.ContextualInterpretationStore()
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-A",
            required_context=frozenset({"match"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-B",
            required_context=frozenset({"other"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_relation(_relation())
    results = store.query("NODE-001", {"match"})
    assert [item.interpretation.interpretation_id for item in results] == ["INT-A"]
    assert [rel.relation_id for rel in results[0].relations] == ["REL-001"]


def test_reopen_preserves_currentness_relations_and_query_order(tmp_path):
    ci = _ci()
    path = tmp_path / "reopen.db"
    store = ci.ContextualInterpretationStore(path)
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-A",
            required_context=frozenset({"x"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-B",
            supersedes_id="INT-A",
            required_context=frozenset({"x", "y"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_interpretation(
        _reading(
            interpretation_id="INT-C",
            required_context=frozenset({"x"}),
            excluded_context=frozenset(),
        )
    )
    store.admit_relation(
        _relation(relation_id="REL-AC", left_id="INT-A", right_id="INT-C")
    )
    reopened = ci.ContextualInterpretationStore(path)
    results = reopened.query("NODE-001", {"x", "y"}, include_superseded=True)
    assert [item.interpretation.interpretation_id for item in results] == [
        "INT-B",
        "INT-A",
        "INT-C",
    ]
    by_id = {item.interpretation.interpretation_id: item for item in results}
    assert by_id["INT-A"].is_current is False
    assert [rel.relation_id for rel in by_id["INT-A"].relations] == ["REL-AC"]


def test_corrupt_durable_rows_fail_closed_with_stable_error_prefix(tmp_path):
    import sqlite3

    ci = _ci()
    path = tmp_path / "corrupt.db"
    store = ci.ContextualInterpretationStore(path)
    store.admit_interpretation(_reading(interpretation_id="INT-A"))
    store.admit_interpretation(_reading(interpretation_id="INT-B"))
    store.admit_relation(_relation())

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE contextual_relations SET canonical_json=? WHERE relation_id=?",
            ('{"broken":true}', "REL-001"),
        )
        db.commit()
    with pytest.raises(
        ci.ContextualInterpretationError,
        match="CORRUPT_CONTEXTUAL_INTERPRETATION_STATE",
    ):
        ci.ContextualInterpretationStore(path).get_relation("REL-001")
