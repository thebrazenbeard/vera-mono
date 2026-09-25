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
