"""Fail-closed, source-only HC coalition -> Mini-Vera context candidate projection.

This is not a second coalition scheduler. The HC runtime forms coalitions;
this module consumes an explicitly exported, untrusted *description* of one.
It emits PUBLIC / WORKING_PROJECT records that a separately authorized host
may review, bind to a current revision, and sign for the existing Mini-Vera
composer. It cannot sign, install, execute, remember or confer authority.

Reference contract: hc-brain main 4caabd3334f0d24e4d52123d9541928489a36536,
runtime/cognitive_core/cognitive_loop.py and reference_kernel/hc_kernel.py.
No sibling-repository code is imported at runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence


class HCProjectionRejected(ValueError):
    """The caller-supplied HC snapshot fails a source-only projection gate."""


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_HEX64 = re.compile(r"[a-f0-9]{64}\Z")
_EPISTEMIC = frozenset({"OBSERVATION", "DERIVED", "INFERRED", "PREDICTION"})
_MEMBERS = {
    "PUBLIC_MEMORY": frozenset({"current memory storage"}),
    "GOAL": frozenset({"volitions-conations"}),
    "UNCERTAINTY": frozenset({"semantics", "integration-arbitration"}),
}
_KINDS = ("UNCERTAINTY", "GOAL", "PUBLIC_MEMORY")
_CANDIDATE_FIELDS = {
    "record_id", "kind", "claim_key", "text", "source_sha256", "source_refs",
    "projection_status", "epistemic_class", "privacy", "salience",
    "expires_after_cycle", "authority_ref", "requested_effect",
}
_COALITION_FIELDS = {
    "coalition_id", "purpose", "active_members", "created_cycle",
    "expires_after_cycle", "status",
}


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _identifier(value: Any, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise HCProjectionRejected(f"invalid {name}")
    return value


def _cycle(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 10**9:
        raise HCProjectionRejected(f"invalid {name}")
    return value


def _text(value: Any, name: str, limit: int) -> str:
    if (type(value) is not str or not value.strip()
            or len(value.encode("utf-8")) > limit
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise HCProjectionRejected(f"invalid {name}")
    return value


def _sha(value: Any, name: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise HCProjectionRejected(f"invalid {name}")
    return value


def _coalition(value: Mapping[str, Any], current_cycle: int,
               ablated: frozenset[str]) -> tuple[str, frozenset[str]]:
    if type(value) is not dict or set(value) != _COALITION_FIELDS:
        raise HCProjectionRejected("HC coalition schema mismatch")
    identity = _identifier(value["coalition_id"], "coalition ID")
    _text(value["purpose"], "coalition purpose", 128)
    created = _cycle(value["created_cycle"], "coalition created cycle")
    expires = _cycle(value["expires_after_cycle"], "coalition expiry")
    if created > current_cycle or current_cycle >= expires or value["status"] != "ACTIVE":
        raise HCProjectionRejected("coalition not active at declared cycle")
    members = value["active_members"]
    if type(members) not in (tuple, list) or not members or len(members) > 24:
        raise HCProjectionRejected("invalid coalition membership")
    if any(type(member) is not str or not 1 <= len(member) <= 64 for member in members):
        raise HCProjectionRejected("invalid coalition member")
    if len(set(members)) != len(members):
        raise HCProjectionRejected("duplicate coalition member")
    if not ablated.issubset(set(members)):
        raise HCProjectionRejected("cannot ablate absent coalition member")
    return identity, frozenset(set(members) - ablated)


def _candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _CANDIDATE_FIELDS:
        raise HCProjectionRejected("HC context proposal schema mismatch")
    record_id = _identifier(value["record_id"], "proposal record ID")
    claim_key = _identifier(value["claim_key"], "proposal claim key")
    kind = value["kind"]
    if kind not in _MEMBERS or type(kind) is not str:
        # Identity comes only from the composer; tool policy only from the host.
        raise HCProjectionRejected("identity/tool policy/action cannot be supplied by HC text")
    raw_text = _text(value["text"], "proposal text", 256)
    digest = _sha(value["source_sha256"], "proposal source digest")
    if digest != _digest(raw_text.encode("utf-8")):
        raise HCProjectionRejected("proposal text does not match its source digest")
    refs = value["source_refs"]
    if type(refs) not in (list, tuple) or not refs or len(refs) > 8:
        raise HCProjectionRejected("proposal requires bounded provenance references")
    for ref in refs:
        _identifier(ref, "provenance reference")
    if len(set(refs)) != len(refs):
        raise HCProjectionRejected("duplicate provenance reference")
    if value["projection_status"] not in {"CURRENT", "MISSING", "AMBIGUOUS"}:
        raise HCProjectionRejected("invalid HC projection status")
    epistemic = value["epistemic_class"]
    if type(epistemic) is not str or epistemic not in _EPISTEMIC:
        raise HCProjectionRejected("invalid epistemic class")
    if value["privacy"] not in {"PUBLIC", "PRIVATE"}:
        raise HCProjectionRejected("invalid privacy scope")
    salience = value["salience"]
    if (type(salience) not in (int, float) or not math.isfinite(salience)
            or not 0.0 <= salience <= 1.0):
        raise HCProjectionRejected("invalid salience; it is priority, not truth")
    expiry = _cycle(value["expires_after_cycle"], "proposal expiry")
    if value["authority_ref"] is not None or value["requested_effect"] != "NONE":
        raise HCProjectionRejected("HC proposal cannot carry authority or an effect")
    return {**value, "record_id": record_id, "kind": kind, "claim_key": claim_key,
            "text": raw_text, "source_sha256": digest, "source_refs": tuple(refs),
            "salience": float(salience), "expires_after_cycle": expiry}


def project_public_context(
    coalition: dict[str, Any], proposals: Sequence[dict[str, Any]], *,
    current_cycle: int, ablate_members: Sequence[str] = (),
    max_records: int = 6,
) -> dict[str, Any]:
    """Project HC proposal data for *later* authenticated Mini-Vera state creation.

    No identity/tool-policy record can originate from this projection. Optional
    salience changes ordering only among already-admissible public records.
    Source hashes, epochs and coalition membership are caller-supplied, NOT
    independently attested; downstream composition must still requalify them.
    """
    cycle = _cycle(current_cycle, "current cycle")
    if type(ablate_members) not in (tuple, list) or len(ablate_members) > 24:
        raise HCProjectionRejected("invalid ablation list")
    if any(type(x) is not str or not 1 <= len(x) <= 64 for x in ablate_members):
        raise HCProjectionRejected("invalid ablation member")
    if len(set(ablate_members)) != len(ablate_members):
        raise HCProjectionRejected("duplicate ablation member")
    if type(max_records) is not int or not 1 <= max_records <= 8:
        raise HCProjectionRejected("Mini-Vera composer supports 1..8 context records")
    if type(proposals) not in (tuple, list) or len(proposals) > 32:
        raise HCProjectionRejected("invalid or excessive proposal inventory")
    coalition_id, members = _coalition(coalition, cycle, frozenset(ablate_members))
    checked = [_candidate(item) for item in proposals]
    ids = [item["record_id"] for item in checked]
    if len(set(ids)) != len(ids):
        raise HCProjectionRejected("duplicate HC proposal record IDs")

    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for item in checked:
        reasons = []
        if item["privacy"] != "PUBLIC":
            reasons.append("NONPUBLIC")
        if item["projection_status"] != "CURRENT":
            reasons.append("NOT_CURRENT")
        if cycle >= item["expires_after_cycle"]:
            reasons.append("STALE")
        if not _MEMBERS[item["kind"]].issubset(members):
            reasons.append("COALITION_MEMBERS_ABSENT")
        if reasons:
            rejected.append({"record_id": item["record_id"], "reason": "+".join(reasons)})
        else:
            eligible.append(item)

    # A salience difference cannot arbitrate contradictory facts. If a logical
    # claim has incompatible current source bytes, exclude the entire group.
    claims: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in eligible:
        claims[(item["kind"], item["claim_key"])].add(item["source_sha256"])
    contested = {key for key, hashes in claims.items() if len(hashes) > 1}
    viable = []
    for item in eligible:
        if (item["kind"], item["claim_key"]) in contested:
            rejected.append({"record_id": item["record_id"], "reason": "CONTESTED"})
        else:
            viable.append(item)

    # Bounded priority selection, not cognitive scheduling. Sources remain
    # untrusted even when selected; priority cannot change evidence class.
    viable.sort(key=lambda item: (_KINDS.index(item["kind"]), -item["salience"], item["record_id"]))
    selected, seen_claims = [], set()
    for item in viable:
        key = (item["kind"], item["claim_key"])
        if key in seen_claims:
            rejected.append({"record_id": item["record_id"], "reason": "DUPLICATE_CLAIM"})
            continue
        if len(selected) >= max_records:
            rejected.append({"record_id": item["record_id"], "reason": "RECORD_BUDGET"})
            continue
        projection = _canonical({
            "kind": item["kind"], "epistemic": item["epistemic_class"],
            "source_ref": item["source_refs"][0], "claim": item["claim_key"],
            "text_as_data": item["text"],
        }).decode("utf-8")
        if len(projection.encode("utf-8")) > 384:
            rejected.append({"record_id": item["record_id"], "reason": "COMPOSER_RECORD_BUDGET"})
            continue
        selected.append({
            "record_id": item["record_id"], "record_class": "WORKING_PROJECT",
            "privacy": "PUBLIC", "instruction_trust": "DATA_NOT_INSTRUCTION",
            "authority_effect": "NONE", "source_sha256": _digest(projection.encode("utf-8")),
            "text": projection,
        })
        seen_claims.add(key)
    rejected.sort(key=lambda item: (item["record_id"], item["reason"]))
    result = {
        "schema": "MINI_VERA_HC_CONTEXT_CANDIDATE_V0",
        "coalition_id": coalition_id,
        "declared_cycle": cycle,
        "ablated_members": sorted(ablate_members),
        "selected_records": selected,
        "rejections": rejected,
        "invariants": {
            "identity_profile_source": "PR194_SOURCE_PINNED_COMPOSER_ONLY",
            "tool_policy_source": "INDEPENDENT_HOST_ONLY",
            "effect_authority": "NONE",
            "memory_write": "NONE",
            "source_currentness": "CALLER_DECLARED_UNATTESTED",
            "behavioral_qualification": "NOT_TESTED",
            "model_calls": 0,
        },
    }
    result["projection_sha256"] = _digest(_canonical(result))
    return result
