"""Canonical chronology helpers without event-state ownership.

Adapted from Temporal. This module parses timezone-aware timestamps,
canonicalizes them to UTC, and computes signed elapsed time. It does not own
event identity, lifecycle state, memory admission, or effect authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re


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
        # datetime stores microseconds; longer decimal fractions would be lost.
        if re.search(r"[.,][0-9]{7,}", candidate):
            raise ValueError("timestamp precision exceeds microseconds")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc
        # Some Python versions collapse a nonzero subsecond-only UTC offset
        # to zero. Do not silently accept a different instant.
        zero_offset_fraction = re.search(
            r"[+-]00(?::?00){0,2}[.,]([0-9]+)$", candidate
        )
        if (parsed.utcoffset() == timezone.utc.utcoffset(None)
                and zero_offset_fraction is not None
                and any(digit != "0" for digit in zero_offset_fraction.group(1))):
            raise ValueError("timestamp offset lost subsecond precision")

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
