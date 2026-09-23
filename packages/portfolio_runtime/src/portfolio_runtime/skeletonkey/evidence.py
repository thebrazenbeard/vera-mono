"""Validation for the immutable Skeleton Key evidence contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


class EvidenceValidationError(ValueError):
    """Raised when a record violates an evidence-class invariant."""


class EvidenceGraphError(EvidenceValidationError):
    """Raised when record lineage is incomplete, cyclic, or class-invalid."""


_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVIDENCE_CLASSES = {"MEASURED", "DERIVED", "INFERRED"}
_VALIDITY_VALUES = {"VALID", "SUSPECT", "INVALID", "UNKNOWN"}
_COMMON_REQUIRED = {
    "record_id",
    "capture_session_id",
    "evidence_class",
    "payload_digest",
    "clock_domain_id",
    "sequence_start",
    "sequence_end",
    "validity",
}


def _require_fields(record: Mapping[str, Any], fields: set[str]) -> None:
    missing = sorted(field for field in fields if field not in record)
    if missing:
        raise EvidenceValidationError(f"missing required fields: {', '.join(missing)}")


def validate_record(record: Mapping[str, Any]) -> None:
    """Validate one record without mutating or promoting its evidence class."""

    _require_fields(record, _COMMON_REQUIRED)

    evidence_class = record["evidence_class"]
    if evidence_class not in _EVIDENCE_CLASSES:
        raise EvidenceValidationError(f"unknown evidence class: {evidence_class!r}")
    if record["validity"] not in _VALIDITY_VALUES:
        raise EvidenceValidationError(f"unknown validity: {record['validity']!r}")
    if not _DIGEST_PATTERN.fullmatch(str(record["payload_digest"])):
        raise EvidenceValidationError("payload_digest must be a lowercase sha256 digest")
    if not isinstance(record["sequence_start"], int) or not isinstance(record["sequence_end"], int):
        raise EvidenceValidationError("sequence bounds must be integers")
    if record["sequence_start"] > record["sequence_end"]:
        raise EvidenceValidationError("sequence_start cannot exceed sequence_end")

    parents = record.get("parent_record_ids")
    if evidence_class == "MEASURED":
        forbidden = {"parent_record_ids", "procedure_id", "rule_id"}.intersection(record)
        if forbidden:
            raise EvidenceValidationError(
                "MEASURED records cannot contain semantic-transform lineage: "
                + ", ".join(sorted(forbidden))
            )
        return

    if not isinstance(parents, list) or not parents or not all(isinstance(item, str) and item for item in parents):
        raise EvidenceValidationError(f"{evidence_class} records require parent_record_ids")

    if evidence_class == "DERIVED":
        _require_fields(record, {"procedure_id", "procedure_version", "parameter_digest"})
        if "rule_id" in record:
            raise EvidenceValidationError("DERIVED records cannot contain an inference rule")
        return

    _require_fields(
        record,
        {"rule_id", "rule_version", "assumptions", "alternatives", "confidence"},
    )
    if "procedure_id" in record:
        raise EvidenceValidationError("INFERRED records cannot masquerade as a deterministic derivation")
    confidence = record["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise EvidenceValidationError("confidence must be numeric and between 0 and 1")


def validate_evidence_graph(records: list[Mapping[str, Any]]) -> None:
    """Validate complete lineage without laundering inference into derivation."""

    by_id: dict[str, Mapping[str, Any]] = {}
    for record in records:
        validate_record(record)
        record_id = record["record_id"]
        if not isinstance(record_id, str) or not record_id:
            raise EvidenceGraphError("record_id must be a non-empty string")
        if record_id in by_id:
            raise EvidenceGraphError(f"duplicate record_id: {record_id}")
        by_id[record_id] = record

    for record_id, record in by_id.items():
        for parent_id in record.get("parent_record_ids", []):
            if parent_id not in by_id:
                raise EvidenceGraphError(
                    f"record {record_id} has missing parent {parent_id}"
                )
            if (
                record["evidence_class"] == "DERIVED"
                and by_id[parent_id]["evidence_class"] == "INFERRED"
            ):
                raise EvidenceGraphError(
                    f"DERIVED record {record_id} cannot depend on INFERRED {parent_id}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(record_id: str) -> None:
        if record_id in visiting:
            raise EvidenceGraphError(f"lineage cycle includes {record_id}")
        if record_id in visited:
            return
        visiting.add(record_id)
        for parent_id in by_id[record_id].get("parent_record_ids", []):
            visit(parent_id)
        visiting.remove(record_id)
        visited.add(record_id)

    for record_id in by_id:
        visit(record_id)

