from __future__ import annotations

from .model import CheckResult, Completeness, OriginStatus, ProvenanceReceipt


def _check(code: str, passed: bool, detail: str) -> CheckResult:
    return CheckResult(code=code, passed=passed, detail=detail)


def validate_receipt_claims(receipt: ProvenanceReceipt) -> tuple[CheckResult, ...]:
    """Validate claim strength without upgrading a partial receipt.

    SourceAttempt.status is descriptive because the donor did not freeze a
    status vocabulary. Only explicit source-adapter assertions of verified
    content and exhausted *declared* scope can satisfy the stronger completeness
    gate. A filename, metadata listing, prior summary or inaccessible ZIP may
    still be a lead; none establishes an inspected primary record.
    """
    if receipt.completeness is not Completeness.COMPLETE_RELATIVE_TO_ACCESSIBLE_SOURCES:
        return (
            _check(
                "receipt.claim_strength",
                True,
                "non-complete receipt is not strengthened by completeness validation",
            ),
            _check(
                "partial.origin_not_established",
                receipt.origin_status is not OriginStatus.ESTABLISHED,
                "partial or unresolved evidence cannot establish an origin",
            ),
        )

    requested_sources = {
        source.strip()
        for source in receipt.target.source_surfaces
        if source.strip()
    }
    attempted_sources = {
        attempt.source.strip()
        for attempt in receipt.source_attempts
        if attempt.source.strip()
    }
    event_ids = {event.record_id for event in receipt.events}
    earliest_ids = set(receipt.earliest_accessible_evidence)
    primary_ids = {
        event.record_id for event in receipt.events
        if event.epistemic_status.value == "DIRECT_SOURCE"
    }
    in_scope_primary_ids = {
        event.record_id for event in receipt.events
        if event.epistemic_status.value == "DIRECT_SOURCE"
        and event.source_surface.strip() in requested_sources
    }
    attempted_in_scope = tuple(
        attempt for attempt in receipt.source_attempts
        if attempt.source.strip() in requested_sources
    )

    checks = (
        _check(
            "complete.source_attempts_present",
            bool(receipt.source_attempts),
            "complete receipt must disclose at least one source attempt",
        ),
        _check(
            "complete.source_scope_declared",
            bool(requested_sources),
            "complete receipt must declare the source surfaces that define its scope",
        ),
        _check(
            "complete.source_scope_covered",
            bool(requested_sources)
            and requested_sources.issubset(attempted_sources),
            "all explicitly requested source surfaces must appear in source attempts",
        ),
        _check(
            "complete.source_content_verified",
            bool(attempted_in_scope)
            and all(attempt.content_verified for attempt in attempted_in_scope),
            "all source attempts in the claimed scope need explicit verified content",
        ),
        _check(
            "complete.source_scope_exhausted",
            bool(attempted_in_scope)
            and all(attempt.scope_exhausted for attempt in attempted_in_scope),
            "all source attempts in the claimed scope need exhausted pagination/search",
        ),
        _check(
            "complete.evidence_present",
            bool(receipt.events),
            "complete receipt must contain accessible evidence; use NO_EVIDENCE otherwise",
        ),
        _check(
            "complete.earliest_evidence_bound",
            bool(earliest_ids) and earliest_ids.issubset(event_ids),
            "earliest accessible evidence must name records in the receipt evidence set",
        ),
        _check(
            "complete.earliest_primary",
            bool(earliest_ids) and earliest_ids.issubset(primary_ids),
            "earliest accessible evidence cannot be only metadata or secondhand recall",
        ),
        _check(
            "complete.earliest_scope_bound",
            bool(earliest_ids) and earliest_ids.issubset(in_scope_primary_ids),
            "primary earliest records must belong to the declared source scope",
        ),
        _check(
            "complete.first_literal_primary",
            set(receipt.first_literal_occurrence).issubset(primary_ids),
            "first verified literal occurrence must reference primary source content",
        ),
        _check(
            "complete.unresolved_references_clear",
            not receipt.unresolved_references,
            "unresolved back-references require a partial/unresolved completeness claim",
        ),
        _check(
            "complete.gaps_clear",
            not receipt.gaps,
            "unresolved lineage gaps require a partial/unresolved completeness claim",
        ),
        _check(
            "complete.established_origin_conflict_free",
            receipt.origin_status is not OriginStatus.ESTABLISHED
            or not receipt.conflicts,
            "origin_status ESTABLISHED cannot coexist with explicit unresolved conflicts",
        ),
        _check(
            "complete.verification_passed",
            bool(receipt.verification)
            and all(check.passed for check in receipt.verification),
            "complete receipt requires executed deterministic checks with no failures",
        ),
    )
    return checks
