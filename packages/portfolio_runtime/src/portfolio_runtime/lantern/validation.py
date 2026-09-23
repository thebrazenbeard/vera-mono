from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from .canonical import canonical_json_bytes, normalize_timestamp, sha256_hex
from .contracts import RecordEnvelope
from .ids import require_uuid7
from ._store_types import ValidationError

RecordLookup = Callable[[str], RecordEnvelope | None]
SourceBlobLookup = Callable[[str], bytes | None]
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CUSTODY = {"REFERENCE_ONLY", "CAPTURED", "EMBEDDED", "REDACTED", "UNAVAILABLE"}
_DISPOSITIONS = {"ACCEPTED", "DISPUTED", "REJECTED", "UNVERIFIED"}
_LINK_MATRIX: dict[str, tuple[set[str], set[str]]] = {
    "SUPPORTS": ({"SourceSnapshot"}, {"Claim"}),
    "OPPOSES": ({"SourceSnapshot"}, {"Claim"}),
    "CONTRADICTS": ({"Claim"}, {"Claim"}),
    "DEPENDS_ON": ({"Assessment", "Decision"}, {"SourceSnapshot", "Claim"}),
}
_MANIFEST_KEYS = {
    "schema", "project_id", "project_name", "schema_version", "interchange_version",
    "created_at", "created_by", "custody_policy", "export_policy", "path_rules",
}


def _exact_keys(value: Mapping[str, Any], required: set[str], label: str) -> None:
    if set(value) != required:
        raise ValidationError(
            f"{label} keys mismatch; missing={sorted(required-set(value))}, extra={sorted(set(value)-required)}"
        )


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{label} must be a non-empty string")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be a list of strings")
    return value


def validate_project_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise ValidationError("ProjectManifest must be an object")
    _exact_keys(manifest, _MANIFEST_KEYS, "ProjectManifest")
    if manifest["schema"] != "LANTERN_PROJECT_MANIFEST_V1":
        raise ValidationError("Unsupported ProjectManifest schema")
    require_uuid7(_nonempty(manifest["project_id"], "project_id"))
    _nonempty(manifest["project_name"], "project_name")
    if manifest["schema_version"] != "1.0" or manifest["interchange_version"] != "1.0":
        raise ValidationError("Unsupported ProjectManifest version")
    if normalize_timestamp(_nonempty(manifest["created_at"], "created_at")) != manifest["created_at"]:
        raise ValidationError("ProjectManifest created_at must be canonical UTC")
    _nonempty(manifest["created_by"], "created_by")
    if manifest["custody_policy"] != "LOCAL_FIRST":
        raise ValidationError("Unsupported custody policy")
    if manifest["export_policy"] != "EXPLICIT_ONLY":
        raise ValidationError("Unsupported export policy")
    if manifest["path_rules"] != "PROJECT_ROOT_RELATIVE_POSIX":
        raise ValidationError("Unsupported path rules")
    return dict(manifest)


def manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(validate_project_manifest(manifest)) + b"\n"


def _record(lookup: RecordLookup, record_id: str, label: str) -> RecordEnvelope:
    try:
        require_uuid7(record_id)
    except ValueError as exc:
        raise ValidationError(f"{label} must be a UUIDv7 record ID") from exc
    resolved = lookup(record_id)
    if resolved is None:
        raise ValidationError(f"Unknown {label}: {record_id}")
    return resolved


def validate_record_semantics(
    record: RecordEnvelope,
    lookup: RecordLookup,
    *,
    source_content: bytes | None = None,
    source_blob_lookup: SourceBlobLookup | None = None,
) -> None:
    payload = record.payload
    provenance = record.provenance
    _nonempty(record.actor_id, "actor_id")

    if record.predecessor_record_id is not None and record.record_type != "StateEvent":
        predecessor = _record(lookup, record.predecessor_record_id, "predecessor_record_id")
        if predecessor.record_type != record.record_type or predecessor.lineage_key != record.lineage_key:
            raise ValidationError("Predecessor record type or lineage key does not match")

    if record.record_type == "SourceSnapshot":
        _exact_keys(payload, {"source_key", "locator", "retrieval_route", "media_type", "custody_mode", "retention_status", "content_sha256"}, "SourceSnapshot payload")
        _exact_keys(provenance, {"source_locator", "retrieval_route"}, "SourceSnapshot provenance")
        source_key = _nonempty(payload["source_key"], "source_key")
        if record.lineage_key != source_key:
            raise ValidationError("SourceSnapshot lineage_key must equal source_key")
        if record.observed_at is None:
            raise ValidationError("SourceSnapshot requires observed_at")
        locator = _nonempty(payload["locator"], "locator")
        route = _nonempty(payload["retrieval_route"], "retrieval_route")
        if provenance != {"source_locator": locator, "retrieval_route": route}:
            raise ValidationError("SourceSnapshot provenance does not match payload")
        _nonempty(payload["media_type"], "media_type")
        custody = payload["custody_mode"]
        if custody not in _CUSTODY:
            raise ValidationError("Invalid custody mode")
        _nonempty(payload["retention_status"], "retention_status")
        digest = payload["content_sha256"]
        if custody in {"CAPTURED", "EMBEDDED"}:
            if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
                raise ValidationError(f"{custody} custody requires content_sha256")
            if source_content is not None:
                if sha256_hex(source_content) != digest:
                    raise ValidationError("Source content digest does not match SourceSnapshot")
            elif source_blob_lookup is not None:
                retained = source_blob_lookup(digest)
                if retained is None:
                    raise ValidationError("Retained source blob is missing")
                if sha256_hex(retained) != digest:
                    raise ValidationError("Retained source blob digest does not match SourceSnapshot")
            else:
                raise ValidationError(f"{custody} custody requires retained source bytes")
        else:
            if digest is not None:
                raise ValidationError(f"{custody} custody cannot retain source bytes")
            if source_content is not None:
                raise ValidationError(f"{custody} custody cannot accept content")
        return

    if record.record_type == "Claim":
        _exact_keys(payload, {"claim_key", "text", "epistemic_class", "attributable_to"}, "Claim payload")
        _exact_keys(provenance, {"attributable_to"}, "Claim provenance")
        claim_key = _nonempty(payload["claim_key"], "claim_key")
        if record.lineage_key != claim_key:
            raise ValidationError("Claim lineage_key must equal claim_key")
        _nonempty(payload["text"], "text")
        _nonempty(payload["epistemic_class"], "epistemic_class")
        attributable = _nonempty(payload["attributable_to"], "attributable_to")
        if provenance != {"attributable_to": attributable}:
            raise ValidationError("Claim provenance does not match payload")
        return

    if record.record_type == "Assessment":
        _exact_keys(payload, {"claim_id", "assessor_id", "scope_id", "disposition", "rationale"}, "Assessment payload")
        _exact_keys(provenance, {"assessor_id", "scope_id"}, "Assessment provenance")
        claim_id = _nonempty(payload["claim_id"], "claim_id")
        assessor = _nonempty(payload["assessor_id"], "assessor_id")
        scope = _nonempty(payload["scope_id"], "scope_id")
        if record.lineage_key != f"{claim_id}|{assessor}|{scope}":
            raise ValidationError("Assessment lineage_key is not derived from claim, assessor, and scope")
        if payload["disposition"] not in _DISPOSITIONS:
            raise ValidationError("Invalid assessment disposition")
        _nonempty(payload["rationale"], "rationale")
        if provenance != {"assessor_id": assessor, "scope_id": scope}:
            raise ValidationError("Assessment provenance does not match payload")
        if _record(lookup, claim_id, "claim_id").record_type != "Claim":
            raise ValidationError("Assessment claim_id must reference a Claim")
        return

    if record.record_type == "Decision":
        _exact_keys(payload, {"decision_key", "authority", "conclusion", "evidence", "assumptions", "alternatives"}, "Decision payload")
        _exact_keys(provenance, {"authority"}, "Decision provenance")
        decision_key = _nonempty(payload["decision_key"], "decision_key")
        if record.lineage_key != decision_key:
            raise ValidationError("Decision lineage_key must equal decision_key")
        authority = _nonempty(payload["authority"], "authority")
        if provenance != {"authority": authority}:
            raise ValidationError("Decision provenance does not match payload")
        _nonempty(payload["conclusion"], "conclusion")
        for key in ("evidence", "assumptions", "alternatives"):
            _string_list(payload[key], key)
        for evidence_id in payload["evidence"]:
            _record(lookup, evidence_id, "Decision evidence record")
        return

    if record.record_type == "Link":
        _exact_keys(payload, {"link_type", "source_record_id", "target_record_id"}, "Link payload")
        _exact_keys(provenance, {"relationship_author"}, "Link provenance")
        if record.lineage_key is not None or record.predecessor_record_id is not None:
            raise ValidationError("Link cannot have lineage or predecessor")
        link_type = payload["link_type"]
        if link_type not in _LINK_MATRIX:
            raise ValidationError("Invalid v1 link type")
        source_id = _nonempty(payload["source_record_id"], "source_record_id")
        target_id = _nonempty(payload["target_record_id"], "target_record_id")
        source = _record(lookup, source_id, "link source")
        target = _record(lookup, target_id, "link target")
        allowed_sources, allowed_targets = _LINK_MATRIX[link_type]
        if source.record_type not in allowed_sources or target.record_type not in allowed_targets:
            raise ValidationError(f"Invalid endpoint matrix for {link_type}: {source.record_type} -> {target.record_type}")
        if link_type == "CONTRADICTS":
            if source_id == target_id:
                raise ValidationError("A Claim cannot contradict itself")
            if [source_id, target_id] != sorted((source_id, target_id)):
                raise ValidationError("CONTRADICTS endpoints must use ascending canonical record-ID order")
        _nonempty(provenance["relationship_author"], "relationship_author")
        return

    if record.record_type == "StateEvent":
        _exact_keys(payload, {"subject_record_id", "event_type", "event_key", "details"}, "StateEvent payload")
        _exact_keys(provenance, {"generated_by", "authority"}, "StateEvent provenance")
        subject_id = _nonempty(payload["subject_record_id"], "subject_record_id")
        if record.lineage_key != f"state:{subject_id}":
            raise ValidationError("StateEvent lineage_key must identify its subject")
        if _record(lookup, subject_id, "StateEvent subject").record_type == "StateEvent":
            raise ValidationError("StateEvent subject cannot be another StateEvent")
        _nonempty(payload["event_type"], "event_type")
        _nonempty(payload["event_key"], "event_key")
        if not isinstance(payload["details"], dict):
            raise ValidationError("StateEvent details must be an object")
        if record.predecessor_record_id is not None:
            predecessor = _record(lookup, record.predecessor_record_id, "StateEvent predecessor")
            if predecessor.record_type != "StateEvent" or predecessor.payload.get("subject_record_id") != subject_id:
                raise ValidationError("StateEvent predecessor must belong to the same subject stream")
        return

    raise ValidationError(f"Unsupported record type: {record.record_type}")
