from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from .canonical import canonical_json, canonical_json_bytes, normalize_timestamp, sha256_hex, strict_json_loads
from .ids import require_uuid7, uuid7

RecordType = Literal["SourceSnapshot", "Claim", "Assessment", "Decision", "Link", "StateEvent"]
CustodyMode = Literal["REFERENCE_ONLY", "CAPTURED", "EMBEDDED", "REDACTED", "UNAVAILABLE"]
Disposition = Literal["ACCEPTED", "DISPUTED", "REJECTED", "UNVERIFIED"]
LinkType = Literal["SUPPORTS", "OPPOSES", "CONTRADICTS", "DEPENDS_ON"]
ImportOutcome = Literal["VERIFIED", "CREATED", "CONFLICT", "SKIPPED"]

SUPPORTED_SCHEMA_VERSION = "1.0"
RECORD_TYPES: set[str] = {"SourceSnapshot", "Claim", "Assessment", "Decision", "Link", "StateEvent"}


@dataclass(frozen=True, slots=True)
class RecordEnvelope:
    project_id: str
    record_id: str
    record_type: str
    schema_version: str
    actor_id: str
    created_at: str
    observed_at: str | None
    provenance_json: str
    lineage_key: str | None
    predecessor_record_id: str | None
    payload_json: str
    record_sha256: str
    canonical_json: str

    @property
    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError("Record payload must be a JSON object")
        return value

    @property
    def provenance(self) -> dict[str, Any]:
        value = json.loads(self.provenance_json)
        if not isinstance(value, dict):
            raise ValueError("Record provenance must be a JSON object")
        return value

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self.canonical_json)
        if not isinstance(value, dict):
            raise ValueError("Canonical record must be a JSON object")
        return value


def _record_body(*, project_id: str, record_id: str, record_type: str, schema_version: str,
                 actor_id: str, created_at: str | datetime, observed_at: str | datetime | None,
                 provenance: dict[str, Any], lineage_key: str | None,
                 predecessor_record_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    if record_type not in RECORD_TYPES:
        raise ValueError(f"Unsupported record type: {record_type}")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema version: {schema_version}")
    return {
        "actor_id": actor_id,
        "created_at": normalize_timestamp(created_at),
        "lineage_key": lineage_key,
        "observed_at": normalize_timestamp(observed_at) if observed_at is not None else None,
        "payload": payload,
        "predecessor_record_id": predecessor_record_id,
        "project_id": require_uuid7(project_id),
        "provenance": provenance,
        "record_id": require_uuid7(record_id),
        "record_type": record_type,
        "schema_version": schema_version,
    }


def build_record(*, project_id: str, record_type: RecordType, actor_id: str,
                 payload: dict[str, Any], provenance: dict[str, Any], record_id: str | None = None,
                 schema_version: str = SUPPORTED_SCHEMA_VERSION,
                 created_at: str | datetime | None = None, observed_at: str | datetime | None = None,
                 lineage_key: str | None = None, predecessor_record_id: str | None = None) -> RecordEnvelope:
    assigned_id = record_id or uuid7()
    body = _record_body(project_id=project_id, record_id=assigned_id, record_type=record_type,
                        schema_version=schema_version, actor_id=actor_id,
                        created_at=created_at or datetime.now(UTC), observed_at=observed_at,
                        provenance=provenance, lineage_key=lineage_key,
                        predecessor_record_id=predecessor_record_id, payload=payload)
    digest = sha256_hex(canonical_json_bytes(body))
    complete = {**body, "record_sha256": digest}
    canonical = canonical_json(complete)
    return RecordEnvelope(
        project_id=body["project_id"], record_id=body["record_id"], record_type=record_type,
        schema_version=schema_version, actor_id=actor_id, created_at=body["created_at"],
        observed_at=body["observed_at"], provenance_json=canonical_json(body["provenance"]),
        lineage_key=lineage_key, predecessor_record_id=predecessor_record_id,
        payload_json=canonical_json(body["payload"]), record_sha256=digest, canonical_json=canonical,
    )


def parse_record(value: str | bytes | dict[str, Any]) -> RecordEnvelope:
    if isinstance(value, (bytes, str)):
        raw = strict_json_loads(value)
    else:
        raw = value
    if not isinstance(raw, dict):
        raise ValueError("Record must be a JSON object")
    required = {"project_id", "record_id", "record_type", "schema_version", "actor_id",
                "created_at", "observed_at", "provenance", "lineage_key",
                "predecessor_record_id", "payload", "record_sha256"}
    if set(raw) != required:
        raise ValueError(f"Record keys mismatch; missing={sorted(required-set(raw))}, extra={sorted(set(raw)-required)}")
    expected_hash = raw["record_sha256"]
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("record_sha256 must be a 64-character hexadecimal string")
    try:
        int(expected_hash, 16)
    except ValueError as exc:
        raise ValueError("record_sha256 must be hexadecimal") from exc
    body = {key: raw[key] for key in raw if key != "record_sha256"}
    rebuilt = _record_body(project_id=body["project_id"], record_id=body["record_id"],
                           record_type=body["record_type"], schema_version=body["schema_version"],
                           actor_id=body["actor_id"], created_at=body["created_at"],
                           observed_at=body["observed_at"], provenance=body["provenance"],
                           lineage_key=body["lineage_key"], predecessor_record_id=body["predecessor_record_id"],
                           payload=body["payload"])
    actual_hash = sha256_hex(canonical_json_bytes(rebuilt))
    if actual_hash != expected_hash:
        raise ValueError("Record hash does not match canonical immutable envelope")
    canonical = canonical_json({**rebuilt, "record_sha256": expected_hash})
    if isinstance(value, (str, bytes)):
        original = value.decode("utf-8") if isinstance(value, bytes) else value
        if canonical != original.strip():
            raise ValueError("Record JSON is not in canonical form")
    return RecordEnvelope(
        project_id=rebuilt["project_id"], record_id=rebuilt["record_id"],
        record_type=rebuilt["record_type"], schema_version=rebuilt["schema_version"],
        actor_id=rebuilt["actor_id"], created_at=rebuilt["created_at"],
        observed_at=rebuilt["observed_at"], provenance_json=canonical_json(rebuilt["provenance"]),
        lineage_key=rebuilt["lineage_key"], predecessor_record_id=rebuilt["predecessor_record_id"],
        payload_json=canonical_json(rebuilt["payload"]), record_sha256=expected_hash,
        canonical_json=canonical,
    )
