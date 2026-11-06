"""Dormant, synthetic-only Presence V2 candidate interface.

The fixed manifest describes inspected *source*, not a host installation. It
cannot install, import, activate, inspect, or run an external repository.
"""

from __future__ import annotations

import re


SCHEMA = "vera.presence.v2"

# Frozen review inputs, NOT dynamic latest-head assertions or host probes.
# This is deliberately not extensible through model or caller parameters.
_SOURCE_CANDIDATES = (
    (
        "pre_active_observation",
        "thebrazenbeard/pre-active",
        "e306c251a4da44125ee58c311a35120084da8e4b",
    ),
    (
        "conations_appraisal",
        "thebrazenbeard/conations",
        "73295039e7a1710c5bb73666e665cef80c40aa5d",
    ),
)

_OBSERVATION_KEYS = frozenset({"origin", "kind", "subject", "event_id"})
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_KINDS = frozenset({"PENDING_WORK", "NO_PENDING_WORK"})


def presence_capabilities_v2():
    """Return new, JSON-compatible copies of a host-controlled source inventory.

    This inert candidate has no installed/active/runtime qualification evidence.
    A caller cannot add capabilities or supply host status through this API.
    """
    return {
        "schema": SCHEMA,
        "host_binding": "NOT_INSTALLED",
        "effect_authority": "NONE",
        "capabilities": [
            {
                "capability_id": capability_id,
                "source_repository": repo,
                "source_git_commit": commit,
                "source_status": "SOURCE_INSPECTED",
                "installed": "UNKNOWN",
                "active": "UNKNOWN",
                "runtime_probed": "UNKNOWN",
                "behavior_qualified": "UNKNOWN",
                "available_to_route": False,
                "effect_authority": "NONE",
            }
            for capability_id, repo, commit in _SOURCE_CANDIDATES
        ],
    }


def presence_propose_v2(observation, *, opt_in=False):
    """Map one synthetic fixture to a non-effectful review proposal.

    This is NOT an MCP tool registration, host observation, Conations appraisal,
    autonomous intent, consent, runtime routing, or persistence mechanism.
    """
    if type(opt_in) is not bool:
        raise TypeError("opt_in must be an exact boolean")
    if not opt_in:
        raise PermissionError("Presence V2 proposal requires explicit local opt-in")
    if type(observation) is not dict:
        raise TypeError("observation must be an exact plain object")
    if any(type(key) is not str for key in observation):
        raise TypeError("observation keys must be exact strings")
    if observation.keys() != _OBSERVATION_KEYS:
        raise ValueError("observation must contain only the fixed synthetic fields")
    if type(observation["origin"]) is not str or type(observation["subject"]) is not str:
        raise TypeError("origin and subject must be exact strings")
    if observation["origin"] != "SYNTHETIC_TEST_FIXTURE":
        raise ValueError("only synthetic fixtures are supported")
    if observation["subject"] != "Vera":
        raise ValueError("only the fixed Vera subject is supported")
    if type(observation["kind"]) is not str or observation["kind"] not in _KINDS:
        raise ValueError("unrecognized synthetic observation kind")
    event_id = observation["event_id"]
    if type(event_id) is not str or _EVENT_ID.fullmatch(event_id) is None:
        raise ValueError("event_id must be a short opaque fixture identifier")

    pending = observation["kind"] == "PENDING_WORK"
    return {
        "schema": SCHEMA,
        "status": "PROPOSED_ONLY" if pending else "NO_PROPOSAL",
        "event_id": event_id,
        "subject": "Vera",
        "candidate": "REQUEST_HOST_REVIEW_OF_WORK_FRONTIER" if pending else None,
        "appraisal": "SYNTHETIC_ONLY_NOT_CONATIONS_STATE",
        "effect": "NONE",
        "authority": "NONE",
        "consent": "NOT_GIVEN_OR_INFERRED",
        "persistence": "NONE",
        "runtime_binding": "NONE",
    }
