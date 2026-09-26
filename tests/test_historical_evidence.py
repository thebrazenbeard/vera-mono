import pytest

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
