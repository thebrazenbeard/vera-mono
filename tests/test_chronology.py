import pytest

from vera_core.chronology import (
    canonical_utc_timestamp,
    elapsed_seconds,
    parse_aware_timestamp,
)


def test_chronology_canonicalizes_aware_time_without_owning_event_state():
    assert canonical_utc_timestamp("2026-09-25T18:00:00-04:00") == (
        "2026-09-25T22:00:00Z"
    )
    assert elapsed_seconds(
        "2026-09-25T18:00:00-04:00",
        "2026-09-25T22:00:05Z",
    ) == 5.0

    with pytest.raises(ValueError, match="timezone-aware"):
        parse_aware_timestamp("2026-09-25T18:00:00")


@pytest.mark.parametrize("value", [
    "2026-09-25T22:00:00.1234567Z",
    "2026-09-25T22:00:00,1234567Z",
    "2026-09-25T22:00:00+00:00:01.1234567",
    "2026-09-25T22:00:00+00:00:00.000001",
    "2026-09-25T22:00:00-00:00:00.000001",
    "20260925T220000+000000.1",
])
def test_chronology_rejects_silently_unrepresentable_time(value):
    with pytest.raises(ValueError, match="precision|offset"):
        canonical_utc_timestamp(value)
    with pytest.raises(ValueError, match="precision|offset"):
        elapsed_seconds(value, "2026-09-25T22:00:00Z")


@pytest.mark.parametrize("value,expected", [
    ("2026-09-25T22:00:00.123456Z", "2026-09-25T22:00:00.123456Z"),
    ("2026-09-25T22:00:00,123456Z", "2026-09-25T22:00:00.123456Z"),
    ("2026-09-25T22:00:00+00:00:01.000001", "2026-09-25T21:59:58.999999Z"),
    ("2026-09-25T22:00:00+00:00:00.000000", "2026-09-25T22:00:00Z"),
    ("20260925.220000Z", "2026-09-25T22:00:00Z"),
])
def test_chronology_retains_supported_exact_values(value, expected):
    assert canonical_utc_timestamp(value) == expected


def test_chronology_retains_signed_microsecond_delta():
    assert elapsed_seconds(
        "2026-09-25T22:00:00.123457Z",
        "2026-09-25T22:00:00.123456Z",
    ) == -0.000001
