from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import inference_boundary_repaired as ib

_CANONICAL_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "architecture" / "cohesion" / "VERA_SEXUAL_DRIVE_COMPONENT_V1.json"
# Raw checkout bytes are transport-sensitive; Git-object provenance is bound externally.
_PINNED_CANONICAL_STRUCTURED_SHA256 = "eec2f6bc50cc87681ab26c8c809e06111bda5ad9aebf4d85f2752227bfd95c05"

def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("sexual-drive component contract is not canonical JSON data") from exc


def _contract_digest(contract: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(contract)).hexdigest()


def _detach_plain_contract(contract: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    if not isinstance(contract, dict):
        raise ValueError("sexual-drive component contract must be an object")
    payload = _canonical_json_bytes(contract)
    try:
        snapshot = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("sexual-drive component contract snapshot is invalid JSON") from exc
    if type(snapshot) is not dict:
        raise ValueError("sexual-drive component contract snapshot must be a plain object")
    return snapshot, payload


def _load_trusted_contract() -> dict[str, Any]:
    raw = _CANONICAL_CONTRACT_PATH.read_bytes()
    try:
        trusted = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("canonical sexual-drive component artifact is invalid JSON") from exc
    if type(trusted) is not dict:
        raise ValueError("canonical sexual-drive component artifact must be an object")
    if _contract_digest(trusted) != _PINNED_CANONICAL_STRUCTURED_SHA256:
        raise ValueError("canonical sexual-drive component structured digest mismatch")
    return trusted


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    snapshot, payload = _detach_plain_contract(contract)
    trusted = _load_trusted_contract()
    trusted_payload = _canonical_json_bytes(trusted)
    if payload != trusted_payload:
        raise ValueError("sexual-drive component contract does not match exact canonical binding")
    return snapshot


def _component_fields(contract: dict[str, Any]) -> dict[str, Any]:
    source = contract["source_binding"]
    projection = contract["state_component_projection"]
    return {
        "component_id": contract["component_id"],
        "domain_id": contract["domain_id"],
        "source_locator": f"github:{source['repository']}",
        "source_revision": source["commit"],
        "component_generation": projection["component_generation"],
        "content_digest": source["semantic_owner_sha256"],
        "currentness_basis": projection["currentness_basis"],
        "supersession_state": projection["supersession_state"],
        "conflict_state": projection["conflict_state"],
        "privacy_classification": contract["privacy_classification"],
        "allowed_egress_scopes": frozenset(contract["allowed_egress_scopes"]),
        "disclosure_source": projection["disclosure_source"],
        "disclosure_generation": projection["disclosure_generation"],
        "requirement_class": contract["requirement_class"],
        "payload_ref": projection["payload_ref"],
    }


def build_component_ref(contract: dict[str, Any], *, observed_at: str) -> ib.StateComponentRef:
    contract = validate_contract(contract)
    component = ib.StateComponentRef(observed_at=observed_at, **_component_fields(contract))
    if target_configuration_status(component) != "TARGET_CONFIGURATION_COMPLETE":
        raise ValueError("constructed sexual-drive component does not match exact qualified tuple")
    return component


def _has_strict_component_types(component: Any) -> bool:
    if type(component) is not ib.StateComponentRef:
        return False
    text_fields = (
        "component_id", "domain_id", "source_locator", "source_revision",
        "component_generation", "content_digest", "observed_at",
        "currentness_basis", "supersession_state", "conflict_state",
        "privacy_classification", "disclosure_source",
        "disclosure_generation", "requirement_class", "payload_ref",
    )
    if any(type(getattr(component, field)) is not str for field in text_fields):
        return False
    scopes = component.allowed_egress_scopes
    if type(scopes) is not frozenset or not scopes:
        return False
    if any(type(item) is not str or not item for item in scopes):
        return False
    return component.payload is None


def target_configuration_status(component: ib.StateComponentRef | None) -> str:
    if component is None:
        return "TARGET_CONFIGURATION_INCOMPLETE"
    if not _has_strict_component_types(component):
        return "SEXUAL_DRIVE_COMPONENT_UNQUALIFIED"
    expected = _component_fields(_load_trusted_contract())
    for field, value in expected.items():
        if getattr(component, field) != value:
            return "SEXUAL_DRIVE_COMPONENT_UNQUALIFIED"
    return "TARGET_CONFIGURATION_COMPLETE"


def producer_currentness_evidence(
    *,
    observed_head: str | None,
    observed_at: str,
) -> dict[str, Any]:
    if type(observed_at) is not str or not observed_at:
        raise ValueError("observed_at must be a non-empty string")
    if observed_head is not None:
        if type(observed_head) is not str or len(observed_head) != 40:
            raise ValueError("observed_head must be a 40-character Git commit id or None")
        try:
            int(observed_head, 16)
        except ValueError as exc:
            raise ValueError("observed_head must be hexadecimal") from exc
        observed_head = observed_head.lower()

    trusted = _load_trusted_contract()
    source = trusted["source_binding"]
    policy = trusted["producer_currentness_policy"]
    frozen_input_commit = source["commit"]

    frozen_input_matches_observed_head = observed_head == frozen_input_commit
    if observed_head is None:
        status = "UNKNOWN"
        ancestry_basis = "NO_OBSERVED_HEAD"
    elif frozen_input_matches_observed_head:
        status = "UNKNOWN"
        ancestry_basis = "EXACT_FROZEN_INPUT_MATCH_NOT_PROVIDER_CURRENTNESS"
    else:
        status = "UNKNOWN"
        ancestry_basis = "EXTERNAL_PRODUCER_CURRENTNESS_VERIFICATION_REQUIRED"

    return {
        "provider": policy["provider"],
        "frozen_input_commit": frozen_input_commit,
        "frozen_input_status": policy["frozen_input_status"],
        "frozen_input_matches_observed_head": frozen_input_matches_observed_head,
        "observed_head": observed_head,
        "observed_at": observed_at,
        "status": status,
        "ancestry_basis": ancestry_basis,
        "provider_currentness_authority": policy["provider_currentness_authority"],
        "consumer_cannot_redefine_provider_currentness": policy[
            "consumer_cannot_redefine_provider_currentness"
        ],
    }


__all__ = [
    "build_component_ref",
    "producer_currentness_evidence",
    "target_configuration_status",
    "validate_contract",
]
