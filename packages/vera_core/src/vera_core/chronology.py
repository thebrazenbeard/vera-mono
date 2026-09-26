"""Canonical chronology helpers without event-state ownership.

Adapted from Temporal. This module parses timezone-aware timestamps,
canonicalizes them to UTC, and computes signed elapsed time. It does not own
event identity, lifecycle state, memory admission, or effect authority.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_aware_timestamp(value: str | datetime) -> datetime:
    """Parse an aware timestamp while rejecting timezone-naive values."""

    if isinstance(value, datetime):
        parsed = value
    else:
        if type(value) is not str or not value.strip():
            raise ValueError("timestamp must be a non-empty string")
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def canonical_utc_timestamp(value: str | datetime) -> str:
    """Return an aware timestamp in canonical UTC ISO-8601 Z form."""

    utc = parse_aware_timestamp(value).astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def elapsed_seconds(
    start: str | datetime,
    end: str | datetime,
) -> float:
    """Return signed elapsed seconds without reordering endpoints."""

    start_utc = parse_aware_timestamp(start).astimezone(timezone.utc)
    end_utc = parse_aware_timestamp(end).astimezone(timezone.utc)
    return (end_utc - start_utc).total_seconds()
