"""Source-recovery TDD: scoped, read-only lexical historical evidence search."""
from __future__ import annotations

import pytest

from vera_memory import HistoricalEvidenceRecord
from vera_memory.historical_evidence import (
    HistoricalEvidenceAccessError,
    RESULT_SEMANTICS,
)
from vera_memory.historical_search import search_historical_evidence


def record(mid: str, text: str | None, *, privacy: str = "PROJECT"):
    return HistoricalEvidenceRecord(
        memory_id=mid, privacy_scope=privacy, event_time=None,
        recorded_at="2026-01-04T00:00:00Z", effective_from=None,
        source_ids=("synthetic:reference",), provenance_ceiling="HISTORICAL_ONLY",
        currentness_rule="HISTORICAL_ONLY", content={"text": text},
    )


def search(records, query="quantum", **kwargs):
    return search_historical_evidence(
        tuple(records), query=query, authorized_privacy_scopes=("PROJECT",),
        retrieved_at="2026-11-02T17:00:00Z", **kwargs)


def test_search_filters_privacy_before_relevance_and_preserves_historical_semantics():
    allowed = record("a-public", "Quantum documentation and audit")
    secret = record("x-secret", "QUANTUM private marker DO_NOT_EXPOSE",
                    privacy="PRIVATE")
    unrelated = record("z-unrelated", "Ordinary event archive")
    result = search((secret, unrelated, allowed))
    assert [r.memory_id for r in result.records] == ["a-public"]
    assert result.result_semantics == RESULT_SEMANTICS
    assert result.current_memory_effect == "NONE"
    assert result.authorization_effect == "NONE"
    assert result.authorized_privacy_scopes == ("PROJECT",)
    assert result.retrieved_at == "2026-11-02T17:00:00Z"
    assert "DO_NOT_EXPOSE" not in repr(result)


def test_missing_privacy_authorization_fails_closed():
    with pytest.raises(HistoricalEvidenceAccessError):
        search_historical_evidence(
            (record("x", "quantum"),), query="quantum",
            authorized_privacy_scopes=(), retrieved_at="2026-11-02T17:00:00Z")


def test_whole_word_matching_no_substring_or_regex_interpretation():
    result = search((
        record("a", "cat evidence"),
        record("b", "educate educational concatenation"),
        record("c", "s.c.a.t.")  # punctuation breaks words, not fuzzy matching
    ), query="CAT")
    assert [r.memory_id for r in result.records] == ["a"]
    assert search((record("a", "educate"),), query="cat").records == ()


def test_deterministic_ranking_and_explicit_limit():
    rows = (
        record("z-only-a", "history history history"),
        record("b-both", "history research"),
        record("a-both", "research, HISTORY"),
        record("x-only-b", "research"),
    )
    expected = ["a-both", "b-both", "x-only-b", "z-only-a"]
    assert [r.memory_id for r in search(rows, query="research history").records] == expected
    assert [r.memory_id for r in search(reversed(rows), query="history RESEARCH research").records] == expected
    assert [r.memory_id for r in search(rows, query="history research", max_results=2).records] == expected[:2]


def test_search_only_explicit_text_field_not_metadata_or_other_fields():
    hidden = HistoricalEvidenceRecord(
        memory_id="a-metadata", privacy_scope="PROJECT", event_time=None,
        recorded_at=None, effective_from=None, source_ids=("source:quantum",),
        provenance_ceiling="HISTORICAL_ONLY", currentness_rule="HISTORICAL_ONLY",
        content={"text": "ordinary", "private_notes": "quantum"},
    )
    nontext = record("b-null", None)
    assert search((hidden, nontext), query="quantum").records == ()


def test_bounded_strict_inputs():
    rows = (record("x", "test"),)
    for bad in ("", "  ", "!!!", "a" * 513, 14, None, True, "test\nsecret"):
        with pytest.raises((ValueError, TypeError)):
            search(rows, query=bad)
    for bad in (0, -1, 101, True, 1.5):
        with pytest.raises((ValueError, TypeError)):
            search(rows, query="test", max_results=bad)
    with pytest.raises(ValueError):
        search(rows, query=" ".join(f"w{i}" for i in range(40)))


def test_no_mutations_and_no_source_index_or_training():
    one = record("a", "history")
    original = one.content["text"]
    result = search((one,), query="history")
    assert result.records == (one,)
    assert one.content["text"] == original
    assert one.currentness_rule == "HISTORICAL_ONLY"
    assert result.result_semantics == RESULT_SEMANTICS


def test_duplicate_record_identifiers_fail_closed_before_ranking():
    with pytest.raises(ValueError, match="duplicate"):
        search((record("same", "research"), record("same", "research")), query="research")
