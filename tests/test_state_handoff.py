import pytest

from vera_core.state_handoff import (
    StateHandoffError,
    StateRevision,
    build_state_handoff,
)


def test_state_handoff_preserves_current_revision_and_supersession_without_identity_claim():
    handoff = build_state_handoff(
        (
            StateRevision(
                event_id="e1",
                family="PROJECT_STATUS",
                key="status",
                value="old",
                revision=1,
            ),
            StateRevision(
                event_id="e2",
                family="PROJECT_STATUS",
                key="status",
                value="current",
                revision=2,
            ),
        )
    )

    assert handoff.current["status"].value == "current"
    assert handoff.current["status"].revision == 2
    assert handoff.superseded_event_ids["status"] == ("e1",)
    assert handoff.identity_continuity_effect == "NONE"
    assert handoff.authorization_effect == "NONE"

    with pytest.raises(StateHandoffError, match="revisions must be unique"):
        build_state_handoff(
            (
                StateRevision("a", "PROJECT_STATUS", "status", "x", 1),
                StateRevision("b", "PROJECT_STATUS", "status", "y", 1),
            )
        )


def test_state_handoff_rejects_mixed_families_to_avoid_key_collision():
    with pytest.raises(StateHandoffError, match="single family"):
        build_state_handoff(
            (
                StateRevision("a", "PROJECT_STATUS", "status", "project", 1),
                StateRevision("b", "USER_PREFERENCE", "status", "preference", 2),
            )
        )
