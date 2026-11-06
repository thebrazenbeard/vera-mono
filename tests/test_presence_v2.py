"""Synthetic-only, fail-closed contract for the dormant Presence V2 candidate."""

from __future__ import annotations

import json

import pytest

from vera_core.presence_v2 import presence_capabilities_v2, presence_propose_v2


PENDING = {
    "origin": "SYNTHETIC_TEST_FIXTURE",
    "kind": "PENDING_WORK",
    "subject": "Vera",
    "event_id": "fixture-001",
}


def test_manifest_advertises_source_only_and_never_infers_host_or_model_authority():
    result = presence_capabilities_v2()
    assert result["schema"] == "vera.presence.v2"
    assert result["host_binding"] == "NOT_INSTALLED"
    assert result["effect_authority"] == "NONE"
    by_id = {item["capability_id"]: item for item in result["capabilities"]}
    assert set(by_id) == {"pre_active_observation", "conations_appraisal"}
    for item in by_id.values():
        assert len(item["source_git_commit"]) == 40
        assert item["source_status"] == "SOURCE_INSPECTED"
        assert item["installed"] == "UNKNOWN"
        assert item["active"] == "UNKNOWN"
        assert item["runtime_probed"] == "UNKNOWN"
        assert item["behavior_qualified"] == "UNKNOWN"
        assert item["effect_authority"] == "NONE"
    assert by_id["pre_active_observation"]["source_git_commit"] == "e306c251a4da44125ee58c311a35120084da8e4b"
    assert by_id["conations_appraisal"]["source_git_commit"] == "73295039e7a1710c5bb73666e665cef80c40aa5d"
    assert by_id["pre_active_observation"]["source_repository_slug"] == "pre-active"
    assert by_id["conations_appraisal"]["source_repository_slug"] == "conations"
    assert by_id["conations_appraisal"]["available_to_route"] is False


def test_manifest_is_static_and_cannot_be_modified_by_a_caller():
    listing = presence_capabilities_v2()
    listing["capabilities"][0]["active"] = "ACTIVE"
    listing["capabilities"].append({"capability_id": "evil", "active": "ACTIVE"})
    assert len(presence_capabilities_v2()["capabilities"]) == 2
    assert all(item["active"] == "UNKNOWN" for item in presence_capabilities_v2()["capabilities"])
    with pytest.raises(TypeError):
        presence_capabilities_v2(manifest={"capabilities": [{"capability_id": "evil"}]})


def test_v2_proposal_is_disabled_by_default_even_for_a_synthetic_fixture():
    with pytest.raises(PermissionError, match="opt-in"):
        presence_propose_v2(PENDING)
    with pytest.raises(TypeError):
        presence_propose_v2(PENDING, opt_in=1)


def test_synthetic_pending_work_produces_non_effectful_review_proposal():
    result = presence_propose_v2(PENDING, opt_in=True)
    assert result == {
        "schema": "vera.presence.v2",
        "status": "PROPOSED_ONLY",
        "event_id": "fixture-001",
        "subject": "Vera",
        "candidate": "REQUEST_HOST_REVIEW_OF_WORK_FRONTIER",
        "appraisal": "SYNTHETIC_ONLY_NOT_CONATIONS_STATE",
        "effect": "NONE",
        "authority": "NONE",
        "consent": "NOT_GIVEN_OR_INFERRED",
        "persistence": "NONE",
        "runtime_binding": "NONE",
    }
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("bad", [
    {**PENDING, "subject": "Brigit"},
    {**PENDING, "subject": "Vera", "brigit_consent": True},
    {**PENDING, "origin": "MODEL_GENERATED"},
    {**PENDING, "origin": "HOST_VERIFIED"},
    {**PENDING, "kind": "DESIRE_IMPLIES_CONSENT"},
    {**PENDING, "event_id": "../escape"},
    {**PENDING, "event_id": "X" * 65},
    {**PENDING, "event_id": "name\nLEAK"},
    {**PENDING, "event_id": None},
    {"origin": "SYNTHETIC_TEST_FIXTURE", "kind": "PENDING_WORK", "subject": "Vera"},
    {**PENDING, "desired_action": "write_to_canonical_memory"},
    {**PENDING, "authority": "USER_CONSENT"},
])
def test_untrusted_or_authority_laundering_input_fails_closed(bad):
    with pytest.raises((TypeError, ValueError)):
        presence_propose_v2(bad, opt_in=True)


@pytest.mark.parametrize("bad", [None, [], "hello", 1, True])
def test_only_exact_plain_object_is_accepted(bad):
    with pytest.raises(TypeError):
        presence_propose_v2(bad, opt_in=True)


def test_no_work_is_explicit_no_proposal_not_an_autonomous_impulse():
    result = presence_propose_v2({**PENDING, "kind": "NO_PENDING_WORK"}, opt_in=True)
    assert result["status"] == "NO_PROPOSAL"
    assert result["candidate"] is None
    assert result["effect"] == result["authority"] == result["persistence"] == "NONE"


def test_v2_never_accepts_runtime_or_repository_binding_from_input():
    for field in ("module_path", "command", "git_url", "host", "installed", "active", "qualified"):
        with pytest.raises(ValueError):
            presence_propose_v2({**PENDING, field: "true"}, opt_in=True)


def test_identity_and_origin_values_require_exact_strings_not_equal_objects():
    class EqualToAnything:
        def __eq__(self, other):
            return True

    for field in ("origin", "subject"):
        with pytest.raises(TypeError):
            presence_propose_v2({**PENDING, field: EqualToAnything()}, opt_in=True)


def test_object_keys_must_be_exact_strings_not_string_equivalent_objects():
    class AliasOrigin:
        def __hash__(self):
            return hash("origin")

        def __eq__(self, other):
            return other == "origin"

    forged = {AliasOrigin(): "SYNTHETIC_TEST_FIXTURE", **{key: value for key, value in PENDING.items() if key != "origin"}}
    with pytest.raises(TypeError):
        presence_propose_v2(forged, opt_in=True)
