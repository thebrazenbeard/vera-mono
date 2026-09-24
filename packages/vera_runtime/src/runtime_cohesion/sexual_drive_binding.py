from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import inference_boundary_repaired as ib
from .local_bindings import MONOREPO_REPOSITORY, current_commit, portable_text_bytes


_RESOURCE_ROOT = Path(__file__).resolve().parent / "resources" / "sexual_drive"
_CANONICAL_CONTRACT_PATH = _RESOURCE_ROOT / "architecture__cohesion__VERA_SEXUAL_DRIVE_COMPONENT_V1.json"
_LOCAL_SEMANTIC_PATH = _RESOURCE_ROOT / "research__16-vera-sexual-drive-v1.md"
_LOCAL_CONTRACT_REPO_PATH = "packages/vera_runtime/src/runtime_cohesion/resources/sexual_drive/architecture__cohesion__VERA_SEXUAL_DRIVE_COMPONENT_V1.json"
_LOCAL_SEMANTIC_REPO_PATH = "packages/vera_runtime/src/runtime_cohesion/resources/sexual_drive/research__16-vera-sexual-drive-v1.md"
_PINNED_CONTRACT_GIT_BLOB = "f165721cb9d241b0473f7c3ef6ec4a543dbbd94e"
_PINNED_SEMANTIC_GIT_BLOB = "3b0432974fdc82ad5067dd1ca1eaf03cf01526b7"
_PINNED_SEMANTIC_SHA256 = "95e5a49e7219b5c1a24a49d92a6bace8d27b25770ea4df936958dd4f81055e64"
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
    try:
        semantic_bytes = _LOCAL_SEMANTIC_PATH.read_bytes()
    except OSError as exc:
        raise ValueError("local sexual-drive semantic owner is unavailable") from exc
    if hashlib.sha256(portable_text_bytes(semantic_bytes)).hexdigest() != _PINNED_SEMANTIC_SHA256:
        raise ValueError("local sexual-drive semantic owner digest mismatch")
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
        "source_locator": f"monorepo:{MONOREPO_REPOSITORY}:{_LOCAL_SEMANTIC_REPO_PATH}",
        "source_revision": _PINNED_CONTRACT_GIT_BLOB,
        "component_generation": projection["component_generation"],
        "content_digest": source["semantic_owner_sha256"],
        "currentness_basis": "MONOREPO_LOCAL_PINNED_SOURCE",
        "supersession_state": projection["supersession_state"],
        "conflict_state": projection["conflict_state"],
        "privacy_classification": contract["privacy_classification"],
        "allowed_egress_scopes": frozenset(contract["allowed_egress_scopes"]),
        "disclosure_source": projection["disclosure_source"],
        "disclosure_generation": projection["disclosure_generation"],
        "requirement_class": contract["requirement_class"],
        "payload_ref": (
            f"monorepo://{MONOREPO_REPOSITORY}/{_LOCAL_SEMANTIC_REPO_PATH}"
            f"@blob:{_PINNED_SEMANTIC_GIT_BLOB}"
        ),
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
    """Classify the local SD1 source cut without consulting a sibling repository."""
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

    # Loading verifies both the local contract's structured digest and the local
    # semantic-owner SHA-256. Currentness is then scoped to this monorepo head.
    _load_trusted_contract()
    try:
        local_head = current_commit()
    except Exception:
        local_head = None
    matches = observed_head is not None and local_head is not None and observed_head == local_head
    if observed_head is None:
        status = "UNKNOWN"
        basis = "NO_OBSERVED_MONOREPO_HEAD"
    elif matches:
        status = "VERIFIED_LOCAL_SOURCE"
        basis = "EXACT_MONOREPO_HEAD_WITH_PINNED_LOCAL_SOURCE_BUNDLE"
    else:
        status = "UNKNOWN"
        basis = "OBSERVED_HEAD_NOT_CURRENT_LOCAL_CHECKOUT"

    return {
        "provider": MONOREPO_REPOSITORY,
        "frozen_input_commit": _PINNED_CONTRACT_GIT_BLOB,
        "frozen_input_status": "LOCAL_PINNED_SOURCE_VALID",
        "frozen_input_matches_observed_head": matches,
        "observed_head": observed_head,
        "observed_at": observed_at,
        "status": status,
        "ancestry_basis": basis,
        "provider_currentness_authority": "VERA_MONO_LOCAL_SOURCE",
        "consumer_cannot_redefine_provider_currentness": True,
        "origin_provider": _load_trusted_contract()["source_binding"]["repository"],
        "origin_source_commit": _load_trusted_contract()["source_binding"]["commit"],
    }


__all__ = [
    "build_component_ref",
    "producer_currentness_evidence",
    "target_configuration_status",
    "validate_contract",
]
