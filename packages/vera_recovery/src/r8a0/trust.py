"""Authority-bound trust configuration for R8A0 recovery."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_sha256, strict_loads
from .signatures import public_key_id, verify_signature
from .temporal import parse_time


class TrustRegistryError(ValueError):
    pass


# Runtime provisioning owns these paths. Recovery requests cannot override them.
AUTHORITY_ROOT_CONFIG_PATH = Path("/etc/vera/r8a0-authority-root.json")
TRUST_REGISTRY_CONFIG_PATH = Path("/etc/vera/r8a0-trust-registry.json")
LIFECYCLE_REGISTRY_KEY_PATH = Path("/etc/vera/r8a0-lifecycle-registry.key")

TRUST_KINDS = ("temporal", "lifecycle", "supervisor", "state")
ROOT_FIELDS = {"schema", "root_id", "issuer", "public_key"}
LIFECYCLE_REGISTRY_FIELDS = {
    "registry_id",
    "path",
    "integrity_key_id",
    "integrity_key_digest",
}
REGISTRY_FIELDS = {
    "schema",
    "registry_id",
    "generation",
    "project_id",
    "identity_id",
    "authority_root_id",
    "authority_source_id",
    "authority_source_digest",
    "issued_at",
    "key_sets",
    "key_set_digests",
    "lifecycle_registry",
    "issuer",
    "key_id",
    "signature",
}


def _sha256(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TrustRegistryError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrustRegistryError(f"{name} must be a nonempty string")
    return value


def _read_stable_bytes(path: Path, name: str) -> bytes:
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise TrustRegistryError(f"{name} is missing or unsafe")
    first = path.read_bytes()
    second = path.read_bytes()
    if first != second:
        raise TrustRegistryError(f"{name} changed during readback")
    return first


def _read_stable_json(path: Path, name: str) -> Mapping[str, Any]:
    record = strict_loads(_read_stable_bytes(path, name))
    if not isinstance(record, Mapping):
        raise TrustRegistryError(f"{name} must be an object")
    return record


def _load_authority_root() -> tuple[str, str, dict[str, Any], str]:
    raw = _read_stable_json(AUTHORITY_ROOT_CONFIG_PATH, "authority root configuration")
    if set(raw) != ROOT_FIELDS:
        raise TrustRegistryError("authority root configuration fields are missing or unknown")
    record = dict(raw)
    if record.get("schema") != "VERA_R8A0_AUTHORITY_ROOT_V1":
        raise TrustRegistryError("unsupported authority root configuration")
    root_id = _nonempty(record.get("root_id"), "authority root ID")
    issuer = _nonempty(record.get("issuer"), "authority root issuer")
    raw_key = record.get("public_key")
    if not isinstance(raw_key, Mapping):
        raise TrustRegistryError("authority root public key must be an object")
    key = dict(raw_key)
    try:
        public_key_id(key)
    except ValueError as exc:
        raise TrustRegistryError("invalid authority root public key") from exc
    return root_id, issuer, key, canonical_sha256(record)


def _validate_key_set(value: Any, kind: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or not value:
        raise TrustRegistryError(f"{kind} key set must be a nonempty object")
    result: dict[str, dict[str, Any]] = {}
    for issuer, raw_key in value.items():
        issuer_name = _nonempty(issuer, f"{kind} issuer")
        if not isinstance(raw_key, Mapping):
            raise TrustRegistryError(f"{kind} public key must be an object")
        key = dict(raw_key)
        try:
            public_key_id(key)
        except ValueError as exc:
            raise TrustRegistryError(f"invalid {kind} public key") from exc
        result[issuer_name] = key
    return result


def _validate_lifecycle_registry(value: Any) -> tuple[str, Path, str, str]:
    if not isinstance(value, Mapping) or set(value) != LIFECYCLE_REGISTRY_FIELDS:
        raise TrustRegistryError("lifecycle registry coordinates are missing or unknown")
    registry_id = _nonempty(value.get("registry_id"), "lifecycle registry ID")
    raw_path = _nonempty(value.get("path"), "lifecycle registry path")
    path = Path(raw_path)
    if not path.is_absolute() or ".." in path.parts:
        raise TrustRegistryError("lifecycle registry path must be absolute and normalized")
    if path.exists() and path.is_symlink():
        raise TrustRegistryError("lifecycle registry path must not be a symlink")
    key_id = _nonempty(value.get("integrity_key_id"), "lifecycle integrity key ID")
    key_digest = _sha256(
        value.get("integrity_key_digest"), "lifecycle integrity key digest"
    )
    return registry_id, path, key_id, key_digest


@dataclass(frozen=True)
class TrustAnchorRegistry:
    registry_id: str
    registry_digest: str
    generation: int
    project_id: str
    identity_id: str
    authority_root_id: str
    authority_root_digest: str
    authority_source_id: str
    authority_source_digest: str
    issued_at: str
    key_sets: Mapping[str, Mapping[str, Mapping[str, Any]]]
    key_set_digests: Mapping[str, str]
    lifecycle_registry_id: str
    lifecycle_registry_path: Path
    lifecycle_integrity_key_id: str
    lifecycle_integrity_key_digest: str

    def keys(self, kind: str) -> Mapping[str, Mapping[str, Any]]:
        if kind not in TRUST_KINDS:
            raise TrustRegistryError("unknown trust key-set kind")
        return self.key_sets[kind]

    def verify_lifecycle_integrity_key(self, key: bytes) -> None:
        if not isinstance(key, bytes) or len(key) < 16:
            raise TrustRegistryError("lifecycle registry integrity key is invalid")
        if hashlib.sha256(key).hexdigest() != self.lifecycle_integrity_key_digest:
            raise TrustRegistryError("lifecycle registry integrity key digest mismatch")

    def binding(self) -> dict[str, Any]:
        return {
            "trust_registry_id": self.registry_id,
            "trust_registry_digest": self.registry_digest,
            "trust_registry_generation": self.generation,
            "trust_project_id": self.project_id,
            "trust_identity_id": self.identity_id,
            "trust_authority_root_id": self.authority_root_id,
            "trust_authority_root_digest": self.authority_root_digest,
            "trust_authority_source_id": self.authority_source_id,
            "trust_authority_source_digest": self.authority_source_digest,
            "trust_key_set_digests": dict(self.key_set_digests),
            "lifecycle_registry_id": self.lifecycle_registry_id,
            "lifecycle_registry_path_digest": canonical_sha256(
                str(self.lifecycle_registry_path)
            ),
            "lifecycle_integrity_key_id": self.lifecycle_integrity_key_id,
            "lifecycle_integrity_key_digest": self.lifecycle_integrity_key_digest,
        }


def load_trust_registry(
    *,
    expected_registry_id: str,
    expected_registry_digest: str,
    expected_key_set_digests: Mapping[str, str],
    expected_project_id: str,
    expected_identity_id: str,
) -> TrustAnchorRegistry:
    expected_id = _nonempty(expected_registry_id, "expected trust registry ID")
    expected_digest = _sha256(
        expected_registry_digest, "expected trust registry digest"
    )
    expected_project = _nonempty(expected_project_id, "expected project ID")
    expected_identity = _nonempty(expected_identity_id, "expected identity ID")
    if not isinstance(expected_key_set_digests, Mapping) or set(
        expected_key_set_digests
    ) != set(TRUST_KINDS):
        raise TrustRegistryError("expected trust key-set digests are incomplete")
    expected_sets = {
        kind: _sha256(
            expected_key_set_digests[kind], f"expected {kind} key-set digest"
        )
        for kind in TRUST_KINDS
    }

    root_id, root_issuer, root_key, root_digest = _load_authority_root()
    raw_record = _read_stable_json(
        TRUST_REGISTRY_CONFIG_PATH, "authority trust registry"
    )
    if set(raw_record) != REGISTRY_FIELDS:
        raise TrustRegistryError("authority trust registry fields are missing or unknown")
    complete_record = dict(raw_record)
    record = dict(raw_record)
    signature = record.pop("signature")
    if (
        record.get("schema") != "VERA_R8A0_TRUST_ANCHOR_REGISTRY_V2"
        or record.get("authority_root_id") != root_id
        or record.get("issuer") != root_issuer
        or record.get("key_id") != public_key_id(root_key)
        or not verify_signature(record, str(signature), root_key)
    ):
        raise TrustRegistryError("authority trust registry signature is invalid")

    registry_id = _nonempty(record.get("registry_id"), "trust registry ID")
    generation = record.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise TrustRegistryError("trust registry generation must be a positive integer")
    project_id = _nonempty(record.get("project_id"), "trust registry project ID")
    identity_id = _nonempty(record.get("identity_id"), "trust registry identity ID")
    if project_id != expected_project or identity_id != expected_identity:
        raise TrustRegistryError("trust registry project or identity scope mismatch")
    authority_source_id = _nonempty(
        record.get("authority_source_id"), "authority source ID"
    )
    authority_source_digest = _sha256(
        record.get("authority_source_digest"), "authority source digest"
    )
    issued_at = _nonempty(record.get("issued_at"), "trust registry issue time")
    parse_time(issued_at)

    raw_sets = record.get("key_sets")
    raw_digests = record.get("key_set_digests")
    if not isinstance(raw_sets, Mapping) or set(raw_sets) != set(TRUST_KINDS):
        raise TrustRegistryError("trust key sets are incomplete")
    if not isinstance(raw_digests, Mapping) or set(raw_digests) != set(TRUST_KINDS):
        raise TrustRegistryError("trust key-set digests are incomplete")
    key_sets = {
        kind: _validate_key_set(raw_sets[kind], kind) for kind in TRUST_KINDS
    }
    key_set_digests = {
        kind: _sha256(raw_digests[kind], f"{kind} key-set digest")
        for kind in TRUST_KINDS
    }
    for kind in TRUST_KINDS:
        if canonical_sha256(key_sets[kind]) != key_set_digests[kind]:
            raise TrustRegistryError(f"{kind} key-set digest mismatch")

    lifecycle_id, lifecycle_path, lifecycle_key_id, lifecycle_key_digest = (
        _validate_lifecycle_registry(record.get("lifecycle_registry"))
    )

    registry_digest = canonical_sha256(complete_record)
    if registry_id != expected_id or registry_digest != expected_digest:
        raise TrustRegistryError("trust registry identity or digest mismatch")
    if key_set_digests != expected_sets:
        raise TrustRegistryError("trust key-set digest reference mismatch")

    return TrustAnchorRegistry(
        registry_id=registry_id,
        registry_digest=registry_digest,
        generation=generation,
        project_id=project_id,
        identity_id=identity_id,
        authority_root_id=root_id,
        authority_root_digest=root_digest,
        authority_source_id=authority_source_id,
        authority_source_digest=authority_source_digest,
        issued_at=issued_at,
        key_sets=key_sets,
        key_set_digests=key_set_digests,
        lifecycle_registry_id=lifecycle_id,
        lifecycle_registry_path=lifecycle_path,
        lifecycle_integrity_key_id=lifecycle_key_id,
        lifecycle_integrity_key_digest=lifecycle_key_digest,
    )


def load_lifecycle_registry_key(registry: TrustAnchorRegistry) -> bytes:
    key = _read_stable_bytes(
        LIFECYCLE_REGISTRY_KEY_PATH, "lifecycle registry integrity key"
    )
    registry.verify_lifecycle_integrity_key(key)
    return key
