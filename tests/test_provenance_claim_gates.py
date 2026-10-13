from dataclasses import replace
from datetime import UTC, datetime

from portfolio_runtime.roots.model import (
    CheckResult, Completeness, Confidence, EpistemicStatus, EvidenceEvent,
    OccurrenceAssessment, OccurrenceRelation, OriginStatus, ProvenanceReceipt,
    RetrievalMethod, SourceAttempt, TargetSpec, TargetKind, TemporalPrecision,
    TimeBounds,
)
from portfolio_runtime.roots.verification import validate_receipt_claims


T = datetime(2026, 1, 1, tzinfo=UTC)


def receipt(*, status=EpistemicStatus.DIRECT_SOURCE, attempt=None,
            complete=True, origin=OriginStatus.EARLIEST_ACCESSIBLE_ONLY):
    source = attempt or SourceAttempt(source="chat", status="SUCCESS")
    event = EvidenceEvent(
        record_id="e1", source_surface="chat", source_locator="chat:msg:1",
        retrieval_method=RetrievalMethod.EXACT, epistemic_status=status,
        content="synthetic literal", event_time=TimeBounds(T, T, TemporalPrecision.DAY),
    )
    return ProvenanceReceipt(
        schema_version=1, trace_id="synthetic", target=TargetSpec(
            "target", TargetKind.PHRASE, "synthetic literal",
            literal_forms=("synthetic literal",), source_surfaces=("chat",),
        ), started_at=T, completed_at=T, source_attempts=(source,),
        completeness=(Completeness.COMPLETE_RELATIVE_TO_ACCESSIBLE_SOURCES
                      if complete else Completeness.PARTIAL),
        earliest_accessible_evidence=("e1",),
        first_literal_occurrence=("e1",), conceptual_ancestors=(),
        current_meaning=(), origin_status=origin, events=(event,),
        assessments=(OccurrenceAssessment(
            record_id="e1", relations=(OccurrenceRelation.FIRST_LITERAL_OCCURRENCE,),
            confidence=Confidence.HIGH,
        ),), edges=(), conflicts=(), gaps=(), unresolved_references=(),
        verification=(CheckResult("source-check", True, "synthetic"),),
    )


def failed_codes(value):
    return {check.code for check in validate_receipt_claims(value) if not check.passed}


def test_complete_provenance_requires_explicit_verified_bytes_and_exhausted_search():
    confirmed = SourceAttempt(
        source="chat", status="SUCCESS", content_verified=True, scope_exhausted=True,
    )
    assert failed_codes(receipt(attempt=confirmed)) == set()


def test_archive_name_is_not_verified_transcript_content():
    metadata = SourceAttempt(source="chat", status="METADATA_ONLY")
    assert "complete.source_content_verified" in failed_codes(
        receipt(attempt=metadata)
    )
    assert "complete.source_scope_exhausted" in failed_codes(receipt(attempt=metadata))


def test_archive_reader_denied_with_other_source_does_not_make_scope_complete():
    verified = SourceAttempt(
        source="chat", status="SUCCESS", content_verified=True, scope_exhausted=True
    )
    denied = SourceAttempt(source="archived_zip", status="ACCESS_DENIED")
    item = receipt(attempt=verified)
    item = replace(item, target=replace(
        item.target, source_surfaces=("chat", "archived_zip")),
        source_attempts=(verified, denied))
    assert "complete.source_content_verified" in failed_codes(item)
    assert "complete.source_scope_exhausted" in failed_codes(item)


def test_secondary_recall_cannot_be_first_literally_verified_occurrence():
    verified = SourceAttempt(
        source="chat", status="SUCCESS", content_verified=True, scope_exhausted=True
    )
    item = receipt(attempt=verified, status=EpistemicStatus.SUPPORTED_INFERENCE)
    assert "complete.first_literal_primary" in failed_codes(item)
    assert "complete.earliest_primary" in failed_codes(item)


def test_partial_search_cannot_claim_established_origin():
    item = receipt(complete=False, origin=OriginStatus.ESTABLISHED)
    assert "partial.origin_not_established" in failed_codes(item)


def test_partial_archive_cannot_claim_complete_even_when_some_bytes_read():
    partial = SourceAttempt(
        source="chat", status="SUCCESS", content_verified=True, scope_exhausted=False
    )
    assert "complete.source_scope_exhausted" in failed_codes(receipt(attempt=partial))


def test_claim_verification_flags_cannot_contradict_known_denied_status():
    import pytest
    with pytest.raises(ValueError, match="contradict"):
        SourceAttempt(source="chat", status="METADATA_ONLY",
                      content_verified=True, scope_exhausted=True)
    with pytest.raises(ValueError, match="contradict"):
        SourceAttempt(source="chat", status="ACCESS_DENIED",
                      content_verified=False, scope_exhausted=True)


def test_primary_evidence_from_unclaimed_surface_does_not_satisfy_scope():
    verified = SourceAttempt(
        source="chat", status="SUCCESS", content_verified=True, scope_exhausted=True
    )
    item = receipt(attempt=verified)
    item = replace(item, events=(replace(item.events[0], source_surface="unrelated"),))
    assert "complete.earliest_scope_bound" in failed_codes(item)
