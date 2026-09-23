from __future__ import annotations

from .model import CheckResult, Completeness, OriginStatus, ProvenanceReceipt


def _check(code: str, passed: bool, detail: str) -> CheckResult:
    return CheckResult(code=code, passed=passed, detail=detail)


def validate_receipt_claims(receipt: ProvenanceReceipt) -> tuple[CheckResult, ...]:
    """Validate claim strength without upgrading a partial receipt.

    This deliberately does not interpret SourceAttempt.status yet because the
    current Roots design has not frozen a normative status vocabulary. It
    enforces only completeness obligations already stated by the design:
    disclose searched scope, bind evidence, clear unresolved retrieval
    obligations/gaps, and run deterministic verification before claiming
    complete-relative-to-accessible-sources.
    """
    if receipt.completeness is not Completeness.COMPLETE_RELATIVE_TO_ACCESSIBLE_SOURCES:
        return (
            _check(
                "receipt.claim_strength",
                True,
                "non-complete receipt is not strengthened by completeness validation",
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
