"""Read-only integrity audit for the *current* Vera governed memory ledger.

Recovered design requirement: the historical v0.2.3 archive had full-store
audit coverage. This implementation verifies the current CAS/receipt schema
without importing old data or admitting historical authority.

This is local consistency evidence, NOT external authentication. A writer
with unrestricted database access can rewrite records, receipts, and heads.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex

from .ledger import MemoryLedgerError, _strict_record_payload


class CurrentMemoryAuditError(MemoryLedgerError):
    """An existing current-schema ledger cannot be verified read-only."""


EVIDENCE_CLASS = "VERA_CURRENT_LEDGER_READONLY_INTEGRITY_V1_NOT_AUTHENTICATED"
GENESIS_HEAD = sha256_hex(b"vera-memory-genesis-v1")
RECEIPT_SCHEMA = "VERA_MONO_MEMORY_ADMISSION_RECEIPT_V1"
RECEIPT_CEILING = "LOCAL_DURABLE_RECORD_NOT_SELF_AUTHENTICATING_POLICY_OR_CURRENT_TRUTH"

RECORD_FIELDS = frozenset((
    "record_id", "text", "memory_class", "source_actor", "authority_ref",
    "privacy_ref", "provenance_refs", "operation_id", "project_id",
    "governed_identity_id", "supersedes", "request_digest",
))
RECEIPT_FIELDS = frozenset((
    "schema", "operation_id", "record_id", "request_digest",
    "record_digest", "memory_class", "project_id", "governed_identity_id",
    "authority_ref", "privacy_ref", "provenance_refs", "store_head",
    "generation", "claim_ceiling",
))


def _require(value: object, reason: str) -> None:
    if not value:
        raise CurrentMemoryAuditError(reason)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CurrentMemoryAuditError("receipt canonical JSON integrity failed")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise CurrentMemoryAuditError("receipt canonical JSON integrity failed")


def _receipt(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_pairs,
                             parse_constant=_nonfinite)
        _require(type(payload) is dict and set(payload) == RECEIPT_FIELDS,
                 "receipt schema integrity failed")
        _require(canonical_json(payload) == raw, "receipt canonical JSON integrity failed")
        return payload
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError) as exc:
        raise CurrentMemoryAuditError("receipt canonical JSON integrity failed") from exc


def audit_current_memory_ledger(
    path: str | Path,
    *, project_id: str,
    identity_id: str,
    max_records: int = 100_000,
    max_database_bytes: int = 128 * 1024 * 1024,
) -> dict[str, object]:
    """Audit existing SQLite records, operations, supersession and CAS chain.

    Uses an SQLite read-only URI and read transaction; never calls MemoryLedger's
    initializer, executes a migration, returns memory content, or writes data.
    Does not compare to an independently trusted previously witnessed head.
    """
    if (type(project_id) is not str or not project_id or
        type(identity_id) is not str or not identity_id):
        raise CurrentMemoryAuditError("expected project and identity are required")
    if (type(max_records) is not int or not 1 <= max_records <= 1_000_000 or
        type(max_database_bytes) is not int or
        not 1 <= max_database_bytes <= 2 * 1024 * 1024 * 1024):
        raise CurrentMemoryAuditError("bounded audit limits required")
    target = Path(path).absolute()
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise CurrentMemoryAuditError("audit refuses symlink path")
    if not target.is_file():
        raise CurrentMemoryAuditError("existing current ledger file required")
    if not 0 < target.stat().st_size <= max_database_bytes:
        raise CurrentMemoryAuditError("current ledger file size limit exceeded")

    # Do not allow a corrupt or old file to be auto-initialized as new memory.
    try:
        with sqlite3.connect(target.as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            meta = dict(db.execute("SELECT key,value FROM meta"))
            _require("generation" in meta and "head" in meta,
                     "current ledger header integrity failed")
            try:
                generation = int(meta["generation"])
            except (ValueError, TypeError) as exc:
                raise CurrentMemoryAuditError("current ledger header integrity failed") from exc
            _require(generation >= 0 and str(generation) == meta["generation"],
                     "current ledger header integrity failed")
            _require(type(meta["head"]) is str and len(meta["head"]) == 64,
                     "current ledger head integrity failed")
            rows = db.execute(
                "SELECT record_id,payload_json,status,superseded_by,"
                "record_digest,supersedes_id FROM records "
                "ORDER BY record_id LIMIT ?", (max_records + 1,),
            ).fetchall()
            operations = db.execute(
                "SELECT operation_id,request_digest,record_id,receipt_json "
                "FROM operations ORDER BY operation_id LIMIT ?", (max_records + 1,),
            ).fetchall()

            _require(len(rows) <= max_records and len(operations) <= max_records,
                     "current ledger audit row limit exceeded")
            _require(len(rows) == len(operations) == generation,
                     "current ledger count and operation history mismatch")

            records: dict[str, tuple[dict[str, Any], sqlite3.Row]] = {}
            successors: dict[str, str] = {}
            for row in rows:
                try:
                    payload = _strict_record_payload(
                        row["payload_json"], record_id=row["record_id"],
                        digest=row["record_digest"])
                except (MemoryLedgerError, ValueError, TypeError) as exc:
                    raise CurrentMemoryAuditError("stored memory record integrity failed") from exc
                _require(set(payload) == RECORD_FIELDS,
                         "stored memory record schema integrity failed")
                _require(payload["project_id"] == project_id and
                         payload["governed_identity_id"] == identity_id,
                         "current ledger identity or project binding mismatch")
                _require(payload["operation_id"] and
                         type(payload["operation_id"]) is str,
                         "stored memory record operation identity mismatch")
                _require(type(payload["provenance_refs"]) is list and
                         all(type(ref) is str and ref for ref in payload["provenance_refs"]),
                         "stored memory record provenance integrity failed")
                expected_request = sha256_hex(canonical_json_bytes({
                    key: value for key, value in payload.items() if key != "request_digest"
                }))
                _require(payload["request_digest"] == expected_request,
                         "stored memory record request digest mismatch")
                predecessor = payload["supersedes"]
                _require(row["supersedes_id"] == predecessor,
                         "stored memory supersession relation mismatch")
                if predecessor is not None:
                    _require(type(predecessor) is str and predecessor != payload["record_id"],
                             "stored memory supersession relation mismatch")
                    _require(predecessor not in successors,
                             "multiple successors for current memory record")
                    successors[predecessor] = payload["record_id"]
                records[payload["record_id"]] = payload, row

            for record_id, (_payload, row) in records.items():
                successor = successors.get(record_id)
                _require((row["status"] == ("SUPERSEDED" if successor else "CURRENT") and
                          row["superseded_by"] == successor),
                         "stored memory supersession status mismatch")
            _require(all(parent in records for parent in successors),
                     "stored memory supersession predecessor missing")

            ordered: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
            for op in operations:
                receipt = _receipt(op["receipt_json"])
                record = records.get(op["record_id"])
                _require(record is not None, "current ledger operation references missing record")
                payload, row = record
                _require(op["operation_id"] == payload["operation_id"] ==
                         receipt["operation_id"] and
                         op["request_digest"] == payload["request_digest"] ==
                         receipt["request_digest"] and
                         receipt["record_id"] == payload["record_id"] and
                         receipt["record_digest"] == row["record_digest"],
                         "current ledger receipt and record binding mismatch")
                for field in ("project_id", "governed_identity_id",
                              "authority_ref", "privacy_ref", "provenance_refs",
                              "memory_class"):
                    _require(receipt[field] == payload[field],
                             "current ledger receipt field binding mismatch")
                _require(receipt["schema"] == RECEIPT_SCHEMA and
                         receipt["claim_ceiling"] == RECEIPT_CEILING and
                         type(receipt["generation"]) is int,
                         "current ledger receipt schema mismatch")
                _require(receipt["generation"] not in ordered,
                         "current ledger duplicate admission generation")
                ordered[receipt["generation"]] = receipt, payload

            head = GENESIS_HEAD
            seen: set[str] = set()
            for index in range(1, generation + 1):
                _require(index in ordered, "current ledger admission generation gap")
                receipt, payload = ordered[index]
                parent = payload["supersedes"]
                _require(parent is None or parent in seen,
                         "current ledger successor precedes predecessor")
                head = sha256_hex(canonical_json_bytes({
                    "previous_head": head, "generation": index,
                    "record_id": payload["record_id"],
                    "record_digest": receipt["record_digest"],
                    "supersedes": parent,
                }))
                _require(receipt["store_head"] == head,
                         "current ledger receipt head chain mismatch")
                seen.add(payload["record_id"])
            _require(meta["head"] == head, "current ledger final head mismatch")
            return {
                "ok": True,
                "evidence_class": EVIDENCE_CLASS,
                "record_count": len(rows),
                "operation_count": len(operations),
                "superseded_count": len(successors),
                "generation": generation,
                "head": head,
                "claim_ceiling": "LOCAL_STRUCTURAL_CONSISTENCY_NOT_EXTERNAL_ATTESTATION",
            }
    except sqlite3.DatabaseError as exc:
        raise CurrentMemoryAuditError("unsupported or corrupt current ledger database") from exc
