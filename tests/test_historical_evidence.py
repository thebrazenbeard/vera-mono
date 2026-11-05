import pytest

from vera_memory import MemoryLedger
from vera_memory.historical_evidence import (
    HistoricalEvidenceAccessError,
    HistoricalEvidenceRecord,
    query_historical_evidence,
)


def test_historical_evidence_query_fails_closed_and_never_promotes_current_memory():
    records = (
        HistoricalEvidenceRecord(
            memory_id="m-public",
            privacy_scope="PROJECT",
            event_time="2026-01-01T12:00:00Z",
            recorded_at="2026-01-02T12:00:00Z",
            effective_from=None,
            source_ids=("source:1",),
            provenance_ceiling="USER_DIRECT",
            currentness_rule="HISTORICAL_ONLY",
            historical_canonicity="CANONICAL_HISTORY",
        ),
        HistoricalEvidenceRecord(
            memory_id="m-private",
            privacy_scope="RELATIONAL_PRIVATE",
            event_time="2026-02-01T12:00:00Z",
            recorded_at=None,
            effective_from="2026-02-03T12:00:00Z",
            source_ids=("source:2",),
            provenance_ceiling="RETRIEVED_EVIDENCE",
            currentness_rule="HISTORICAL_ONLY",
            historical_canonicity="CANONICAL_HISTORY",
        ),
    )

    with pytest.raises(HistoricalEvidenceAccessError):
        query_historical_evidence(records, authorized_privacy_scopes=())

    result = query_historical_evidence(
        records,
        authorized_privacy_scopes=("PROJECT",),
        retrieved_at="2026-09-25T22:00:00Z",
    )

    assert [item.memory_id for item in result.records] == ["m-public"]
    assert result.result_semantics == (
        "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY"
    )
    assert result.current_memory_effect == "NONE"
    assert result.authorization_effect == "NONE"

    item = result.records[0]
    assert item.event_time == "2026-01-01T12:00:00Z"
    assert item.recorded_at == "2026-01-02T12:00:00Z"
    assert item.effective_from is None
    assert result.retrieved_at == "2026-09-25T22:00:00Z"
    assert item.chronology_semantics == (
        "EVENT_TIME_RECORD_TIME_EFFECTIVE_TIME_RETRIEVAL_TIME_SEPARATE"
    )


def test_historical_evidence_preserves_explicit_unknown_record_time_status():
    record = HistoricalEvidenceRecord(
        memory_id="m-unknown-record-time",
        privacy_scope="PROJECT",
        event_time="2026-03-01T12:00:00Z",
        recorded_at=None,
        effective_from=None,
        source_ids=("source:3",),
        provenance_ceiling="USER_DIRECT",
        currentness_rule="HISTORICAL_ONLY",
        historical_canonicity="CANONICAL_HISTORY",
    )

    result = query_historical_evidence(
        (record,),
        authorized_privacy_scopes=("PROJECT",),
        retrieved_at="2026-09-25T22:00:00Z",
    )

    item = result.records[0]
    assert item.recorded_at is None
    assert item.recorded_at_status == "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW"
    assert item.effective_from is None
    assert item.effective_from_status == "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW"


def test_historical_evidence_recursively_snapshots_nested_untrusted_content():
    original = {"account": {"roles": ["historical"], "annotations": [{"status": "unreviewed"}]}}
    record = HistoricalEvidenceRecord(
        memory_id="m-nested", privacy_scope="PRIVATE", event_time=None,
        recorded_at=None, effective_from=None, source_ids=("source:nested",),
        provenance_ceiling="UNVERIFIED", currentness_rule="HISTORICAL_ONLY",
        content=original,
    )
    original["account"]["roles"].append("current")
    original["account"]["annotations"][0]["status"] = "approved"
    result = query_historical_evidence(
        (record,), authorized_privacy_scopes=("PRIVATE",),
        retrieved_at="2026-11-05T17:00:00Z",
    )
    snapshot = result.records[0].content
    assert snapshot["account"]["roles"] == ("historical",)
    assert snapshot["account"]["annotations"][0]["status"] == "unreviewed"
    with pytest.raises(TypeError):
        snapshot["account"]["annotations"][0]["status"] = "forged"
    with pytest.raises(AttributeError):
        snapshot["account"]["roles"].append("forged")


def test_historical_evidence_rejects_cycles_and_unsupported_mutable_values():
    kwargs = dict(
        memory_id="m-malformed", privacy_scope="PRIVATE", event_time=None,
        recorded_at=None, effective_from=None, source_ids=("source:one",),
        provenance_ceiling="UNVERIFIED", currentness_rule="HISTORICAL_ONLY",
    )
    cyclic = {}
    cyclic["self"] = cyclic
    for bad in (cyclic, {"mutable_set": {"surprise"}}, {"nan": float("nan")},
                {1: "non-string-key"}, {"opaque": object()}):
        with pytest.raises((TypeError, ValueError)):
            HistoricalEvidenceRecord(**kwargs, content=bad)


def test_historical_retrieval_does_not_mutate_governed_memory_head(tmp_path):
    ledger = MemoryLedger(tmp_path / "governed.sqlite", project_id="vera-mono", identity_id="vera")
    original_head = ledger.current_head
    historical = HistoricalEvidenceRecord(
        memory_id="history:1", privacy_scope="PRIVATE", event_time="2026-01-01T00:00:00Z",
        recorded_at="2026-01-02T00:00:00Z", effective_from=None,
        source_ids=("source:historical",), provenance_ceiling="UNVERIFIED",
        currentness_rule="HISTORICAL_ONLY", content={"text": "a past claim"},
    )
    result = query_historical_evidence(
        (historical,), authorized_privacy_scopes=("PRIVATE",),
        retrieved_at="2026-11-05T17:00:00Z",
    )
    assert result.current_memory_effect == "NONE"
    assert result.authorization_effect == "NONE"
    assert ledger.current_head == original_head
    with pytest.raises(KeyError):
        ledger.read("history:1")


def test_authorized_privacy_scope_string_cannot_split_into_matching_characters():
    record = HistoricalEvidenceRecord(
        memory_id="m-private", privacy_scope="P", event_time=None,
        recorded_at=None, effective_from=None, source_ids=("source:private",),
        provenance_ceiling="HISTORICAL", currentness_rule="HISTORICAL_ONLY",
    )
    # Before this guard, tuple("PRIVATE") admitted the one-letter scope "P".
    for malformed in ("PRIVATE", ["P"], b"PRIVATE", (" ",)):
        with pytest.raises(HistoricalEvidenceAccessError):
            query_historical_evidence(
                (record,), authorized_privacy_scopes=malformed,
                retrieved_at="2026-11-05T17:00:00Z",
            )
    assert query_historical_evidence(
        (record,), authorized_privacy_scopes=("P",),
        retrieved_at="2026-11-05T17:00:00Z",
    ).records == (record,)


def test_source_ids_must_be_exact_tuple_not_split_text():
    kwargs = dict(
        memory_id="m-source", privacy_scope="PRIVATE", event_time=None,
        recorded_at=None, effective_from=None,
        provenance_ceiling="HISTORICAL", currentness_rule="HISTORICAL_ONLY",
    )
    for malformed in ("abc", ["source:a"], b"abc", (" ",)):
        with pytest.raises(ValueError, match="source_ids"):
            HistoricalEvidenceRecord(**kwargs, source_ids=malformed)
    assert HistoricalEvidenceRecord(**kwargs, source_ids=("source:a",)).source_ids == ("source:a",)
