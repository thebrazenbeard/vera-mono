"""Read-only structural audit for the local Vera memory ledger.

Recovery-oriented audit inspired by historical archive capability, not a
migration of old memory contents, evidence of provenance, or admission authority.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex
from .ledger import MemoryLedgerError, _strict_record_payload


GENESIS_HEAD = sha256_hex(b"vera-memory-genesis-v1")
CLAIM_CEILING = "INTERNAL_STRUCTURE_ONLY_NOT_PROVENANCE_OR_AUTHORITY"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise MemoryLedgerError("duplicate key in stored operation receipt")
        result[key] = value
    return result


def _receipt(raw: str) -> dict[str, Any]:
    def reject_nonfinite(value: str) -> None:
        raise MemoryLedgerError("non-finite operation receipt value")

    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object,
                             parse_constant=reject_nonfinite)
        if type(payload) is not dict or canonical_json(payload) != raw:
            raise MemoryLedgerError("noncanonical operation receipt")
    except (TypeError, ValueError, OverflowError) as exc:
        raise MemoryLedgerError("corrupt operation receipt") from exc
    return payload


def audit_memory_ledger(path: str | Path, *, project_id: str,
                        identity_id: str) -> dict[str, Any]:
    """Inspect all current records/receipts without modifying an existing DB.

    A PASS means internal structural consistency only. Someone with write
    access to the SQLite file can forge a self-consistent ledger, so this
    check never authenticates evidence, grants rights, or proves currentness.
    """
    if any(type(v) is not str or not v for v in (project_id, identity_id)):
        raise MemoryLedgerError("project and identity must be exact nonempty strings")
    source = Path(path).absolute()
    if not source.is_file():
        raise MemoryLedgerError("ledger path is missing or not a regular file")
    try:
        db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            meta = dict(db.execute("SELECT key,value FROM meta").fetchall())
            try:
                generation = int(meta["generation"])
                expected_head = meta["head"]
            except (KeyError, ValueError, TypeError) as exc:
                raise MemoryLedgerError("invalid ledger metadata") from exc
            if generation < 0 or type(expected_head) is not str:
                raise MemoryLedgerError("invalid generation or head")
            rows = db.execute(
                "SELECT record_id,payload_json,status,superseded_by,"
                "record_digest,supersedes_id FROM records"
            ).fetchall()
            operations = db.execute(
                "SELECT operation_id,request_digest,record_id,receipt_json "
                "FROM operations ORDER BY rowid"
            ).fetchall()
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise MemoryLedgerError("cannot read complete ledger snapshot") from exc

    records = {}
    successors = {}
    for row in rows:
        rid = row["record_id"]
        if rid in records:
            raise MemoryLedgerError("duplicate record")
        payload = _strict_record_payload(row["payload_json"], record_id=rid,
                                         digest=row["record_digest"])
        if payload["project_id"] != project_id or payload["governed_identity_id"] != identity_id:
            raise MemoryLedgerError("project or identity mismatch")
        parent = payload.get("supersedes")
        if row["supersedes_id"] != parent:
            raise MemoryLedgerError("stored lineage relation mismatch")
        if parent is not None:
            if parent in successors:
                raise MemoryLedgerError("multiple successors for one predecessor")
            successors[parent] = rid
        records[rid] = (payload, row)
    for rid, (payload, row) in records.items():
        parent = payload.get("supersedes")
        if parent is not None and parent not in records:
            raise MemoryLedgerError("missing superseded predecessor")
        successor = successors.get(rid)
        status = "SUPERSEDED" if successor else "CURRENT"
        if row["status"] != status or row["superseded_by"] != successor:
            raise MemoryLedgerError("record status contradicts successor relation")

    if len(operations) != len(records) or len(operations) != generation:
        raise MemoryLedgerError("operation/record/generation count mismatch")
    head = GENESIS_HEAD
    admitted = set()
    for n, op in enumerate(operations, start=1):
        rid = op["record_id"]
        if rid not in records or rid in admitted:
            raise MemoryLedgerError("operation missing or repeated record")
        payload, row = records[rid]
        receipt = _receipt(op["receipt_json"])
        for key, expected in (
            ("schema", "VERA_MONO_MEMORY_ADMISSION_RECEIPT_V1"),
            ("operation_id", op["operation_id"]),
            ("record_id", rid),
            ("request_digest", op["request_digest"]),
            ("record_digest", row["record_digest"]),
            ("project_id", project_id),
            ("governed_identity_id", identity_id),
            ("memory_class", payload["memory_class"]),
            ("authority_ref", payload["authority_ref"]),
            ("privacy_ref", payload["privacy_ref"]),
            ("provenance_refs", payload["provenance_refs"]),
            ("claim_ceiling", "LOCAL_DURABLE_RECORD_NOT_SELF_AUTHENTICATING_POLICY_OR_CURRENT_TRUTH"),
            ("generation", n),
        ):
            if type(receipt.get(key)) is not type(expected) or receipt.get(key) != expected:
                raise MemoryLedgerError("operation receipt field mismatch: " + key)
        if op["operation_id"] != payload["operation_id"] or (
                op["request_digest"] != payload["request_digest"]):
            raise MemoryLedgerError("operation binding differs from hashed record")
        if payload.get("supersedes") is not None and payload["supersedes"] not in admitted:
            raise MemoryLedgerError("successor precedes predecessor")
        material = {"previous_head": head, "generation": n, "record_id": rid,
                    "record_digest": row["record_digest"],
                    "supersedes": payload.get("supersedes")}
        head = sha256_hex(canonical_json_bytes(material))
        if receipt.get("store_head") != head:
            raise MemoryLedgerError("operation receipt head mismatch")
        admitted.add(rid)
    if head != expected_head:
        raise MemoryLedgerError("ledger head mismatch")
    return {"schema": "VERA_MONO_MEMORY_STRUCTURE_AUDIT_V1",
            "status": "CONSISTENT_LOCAL_STRUCTURE_ONLY", "records": len(records),
            "operations": len(operations), "generation": generation,
            "head": head, "claim_ceiling": CLAIM_CEILING,
            "authorization_effect": "NONE"}
