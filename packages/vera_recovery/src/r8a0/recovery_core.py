"""Externally attested checkpoint, exit observation, and fresh-process recovery."""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .canonical import canonical_dumps, canonical_sha256, strict_loads
from .lifecycle import LifecycleRegistry
from .signatures import public_key_id, verify_signature
from .temporal import OrientationGate, OrientationState, TimeEvidence, parse_time


class RecoveryError(ValueError):
    pass


MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_LIFECYCLE_AGE = timedelta(hours=1)
CHECKPOINT_FIELDS = {
    "project_id",
    "identity_id",
    "runtime_id",
    "runtime_instance_nonce",
    "memory_head_digest",
    "self_model_head_digest",
    "authority_state_digest",
    "active_commitments",
    "unfinished_work",
    "created_at",
    "predecessor_checkpoint_digest",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _atomic(path: str | Path, value: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temp = Path(name)
    try:
        temp.write_text(canonical_dumps(dict(value)), encoding="utf-8")
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()
    if strict_loads(destination.read_bytes()) != dict(value):
        raise RecoveryError("persisted receipt readback mismatch")


def _signed(
    body: Mapping[str, Any],
    issuer: str,
    key_id: str,
    signer: Callable[[Any], str],
) -> dict[str, Any]:
    material = dict(body) | {"issuer": issuer, "key_id": key_id}
    return material | {"signature": signer(material)}


def _verify(
    record: Mapping[str, Any],
    keys: Mapping[str, Mapping[str, Any]],
    schema: str,
    body_fields: set[str],
) -> dict[str, Any]:
    if set(record) != body_fields | {"issuer", "key_id", "signature"}:
        raise RecoveryError("signed evidence fields are missing or unknown")
    material = {key: record[key] for key in body_fields | {"issuer", "key_id"}}
    public_key = keys.get(str(record["issuer"]))
    if (
        public_key is None
        or public_key_id(public_key) != record["key_id"]
        or not verify_signature(material, str(record["signature"]), public_key)
    ):
        raise RecoveryError("signed evidence verification failed")
    if material.get("schema") != schema:
        raise RecoveryError("unsupported signed evidence schema")
    return material


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryError(f"{name} must be a nonempty string")
    return value


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        raise RecoveryError(f"{name} must be a list of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RecoveryError(f"{name} entries must be nonempty strings")
    return tuple(value)


@dataclass(frozen=True)
class CheckpointState:
    project_id: str
    identity_id: str
    runtime_id: str
    runtime_instance_nonce: str
    memory_head_digest: str
    self_model_head_digest: str
    authority_state_digest: str
    active_commitments: tuple[str, ...]
    unfinished_work: tuple[str, ...]
    created_at: str
    predecessor_checkpoint_digest: str

    def validate(self) -> None:
        for name in (
            "project_id",
            "identity_id",
            "runtime_id",
            "runtime_instance_nonce",
            "created_at",
        ):
            _nonempty_string(getattr(self, name), name)
        parse_time(self.created_at)
        _string_tuple(self.active_commitments, "active_commitments")
        _string_tuple(self.unfinished_work, "unfinished_work")
        for digest in (
            self.memory_head_digest,
            self.self_model_head_digest,
            self.authority_state_digest,
            self.predecessor_checkpoint_digest,
        ):
            if not _sha(digest):
                raise RecoveryError("checkpoint roots must be lowercase SHA-256 values")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "project_id": self.project_id,
            "identity_id": self.identity_id,
            "runtime_id": self.runtime_id,
            "runtime_instance_nonce": self.runtime_instance_nonce,
            "memory_head_digest": self.memory_head_digest,
            "self_model_head_digest": self.self_model_head_digest,
            "authority_state_digest": self.authority_state_digest,
            "active_commitments": list(self.active_commitments),
            "unfinished_work": list(self.unfinished_work),
            "created_at": self.created_at,
            "predecessor_checkpoint_digest": self.predecessor_checkpoint_digest,
        }


def checkpoint_state_from_mapping(value: Mapping[str, Any]) -> CheckpointState:
    if not isinstance(value, Mapping) or set(value) != CHECKPOINT_FIELDS:
        raise RecoveryError("checkpoint state fields are missing or unknown")
    state = CheckpointState(
        project_id=_nonempty_string(value["project_id"], "project_id"),
        identity_id=_nonempty_string(value["identity_id"], "identity_id"),
        runtime_id=_nonempty_string(value["runtime_id"], "runtime_id"),
        runtime_instance_nonce=_nonempty_string(
            value["runtime_instance_nonce"], "runtime_instance_nonce"
        ),
        memory_head_digest=value["memory_head_digest"],
        self_model_head_digest=value["self_model_head_digest"],
        authority_state_digest=value["authority_state_digest"],
        active_commitments=_string_tuple(
            value["active_commitments"], "active_commitments"
        ),
        unfinished_work=_string_tuple(value["unfinished_work"], "unfinished_work"),
        created_at=_nonempty_string(value["created_at"], "created_at"),
        predecessor_checkpoint_digest=value["predecessor_checkpoint_digest"],
    )
    state.validate()
    return state


ROOT_KINDS = (
    "predecessor_checkpoint",
    "memory_head",
    "self_model_head",
    "authority_state",
)


def verify_state_attestations(
    attestations: Mapping[str, Mapping[str, Any]],
    *,
    trusted_state_keys: Mapping[str, Mapping[str, Any]],
    state: CheckpointState,
) -> str:
    state.validate()
    if set(attestations) != set(ROOT_KINDS):
        raise RecoveryError("state-root attestations are incomplete")
    expected = {
        "predecessor_checkpoint": state.predecessor_checkpoint_digest,
        "memory_head": state.memory_head_digest,
        "self_model_head": state.self_model_head_digest,
        "authority_state": state.authority_state_digest,
    }
    normalized: list[dict[str, Any]] = []
    fields = {
        "schema",
        "kind",
        "project_id",
        "identity_id",
        "digest",
        "generation",
        "observed_at",
    }
    for kind in ROOT_KINDS:
        attestation = attestations[kind]
        material = _verify(
            attestation,
            trusted_state_keys,
            "VERA_R8A0_STATE_ROOT_ATTESTATION_V1",
            fields,
        )
        if (
            material["kind"] != kind
            or material["project_id"] != state.project_id
            or material["identity_id"] != state.identity_id
            or material["digest"] != expected[kind]
        ):
            raise RecoveryError("state-root attestation scope or digest mismatch")
        if (
            not _sha(str(material["digest"]))
            or not isinstance(material["generation"], int)
            or material["generation"] < 0
        ):
            raise RecoveryError("invalid state-root attestation")
        parse_time(str(material["observed_at"]))
        normalized.append(dict(attestation))
    return canonical_sha256(normalized)

