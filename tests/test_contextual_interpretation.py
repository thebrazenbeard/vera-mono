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
