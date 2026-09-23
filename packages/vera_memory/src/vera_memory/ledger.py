from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex


class MemoryLedgerError(ValueError):
    pass


class StaleMemoryHead(MemoryLedgerError):
    pass


class MemoryClass(StrEnum):
    AUTOBIOGRAPHICAL = "AUTOBIOGRAPHICAL"
    WORKING_PROJECT = "WORKING_PROJECT"
    HISTORICAL_AUDIT = "HISTORICAL_AUDIT"


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    record_id: str
    text: str
    memory_class: MemoryClass
    source_actor: str
    authority_ref: str
    privacy_ref: str
    provenance_refs: tuple[str, ...]
    operation_id: str
    project_id: str
    governed_identity_id: str
    supersedes: str | None = None

    def validate(self) -> None:
        for value, label in (
            (self.record_id, "record_id"),
            (self.text, "text"),
            (self.source_actor, "source_actor"),
            (self.authority_ref, "authority_ref"),
            (self.privacy_ref, "privacy_ref"),
            (self.operation_id, "operation_id"),
            (self.project_id, "project_id"),
            (self.governed_identity_id, "governed_identity_id"),
        ):
            if type(value) is not str or not value:
                raise MemoryLedgerError(f"{label} must be a non-empty exact string")
        if type(self.memory_class) is not MemoryClass:
            raise MemoryLedgerError("memory_class must be an exact MemoryClass")
        if type(self.provenance_refs) is not tuple or any(
            type(ref) is not str or not ref for ref in self.provenance_refs
        ):
            raise MemoryLedgerError("provenance_refs must be exact non-empty strings")
        if len(self.provenance_refs) != len(set(self.provenance_refs)):
            raise MemoryLedgerError("provenance_refs must be unique")
        if self.supersedes is not None and (type(self.supersedes) is not str or not self.supersedes):
            raise MemoryLedgerError("supersedes must be null or a non-empty exact string")

    def payload(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        value["memory_class"] = self.memory_class.value
        value["provenance_refs"] = list(self.provenance_refs)
        return value

    @property
    def request_digest(self) -> str:
        return sha256_hex(canonical_json_bytes(self.payload()))


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    record_id: str
    text: str
    memory_class: MemoryClass
    source_actor: str
    authority_ref: str
    privacy_ref: str
    provenance_refs: tuple[str, ...]
    operation_id: str
    project_id: str
    governed_identity_id: str
    supersedes: str | None
    status: str
    superseded_by: str | None
    record_digest: str


class MemoryLedger:
    """Transactional local memory ledger with CAS heads and explicit provenance.

    This owns local admission/state mechanics only. Authority and privacy refs are
    bindings supplied by higher policy layers; their truth is not self-certified
    merely because the ledger stores them.
    """

    def __init__(self, path: str | Path, *, project_id: str, identity_id: str):
        self.path = Path(path)
        if type(project_id) is not str or not project_id:
            raise MemoryLedgerError("project_id is required")
        if type(identity_id) is not str or not identity_id:
            raise MemoryLedgerError("identity_id is required")
        self.project_id = project_id
        self.identity_id = identity_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('CURRENT','SUPERSEDED')),
                    superseded_by TEXT,
                    record_digest TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES records(record_id)
                );
                """
            )
            if db.execute("SELECT 1 FROM meta WHERE key='generation'").fetchone() is None:
                db.execute("INSERT INTO meta(key,value) VALUES('generation','0')")
                db.execute("INSERT INTO meta(key,value) VALUES('head',?)", (sha256_hex(b"vera-memory-genesis-v1"),))

    def _meta(self, db: sqlite3.Connection) -> tuple[int, str]:
        generation = int(db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0])
        head = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
        return generation, head

    @property
    def current_head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    @staticmethod
    def _record_payload(request: AdmissionRequest) -> dict[str, Any]:
        return {
            "record_id": request.record_id,
            "text": request.text,
            "memory_class": request.memory_class.value,
            "source_actor": request.source_actor,
            "authority_ref": request.authority_ref,
            "privacy_ref": request.privacy_ref,
            "provenance_refs": list(request.provenance_refs),
            "operation_id": request.operation_id,
            "project_id": request.project_id,
            "governed_identity_id": request.governed_identity_id,
            "supersedes": request.supersedes,
            "request_digest": request.request_digest,
        }

    def admit(self, request: AdmissionRequest, *, expected_head: str) -> dict[str, Any]:
        request.validate()
        if request.project_id != self.project_id or request.governed_identity_id != self.identity_id:
            raise MemoryLedgerError("memory request project or identity mismatch")
        if type(expected_head) is not str or not expected_head:
            raise MemoryLedgerError("expected_head is required")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                "SELECT request_digest,receipt_json FROM operations WHERE operation_id=?",
                (request.operation_id,),
            ).fetchone()
            if replay is not None:
                if replay["request_digest"] != request.request_digest:
                    raise MemoryLedgerError("operation_id replay carries a different request")
                return json.loads(replay["receipt_json"])

            generation, current_head = self._meta(db)
            if current_head != expected_head:
                raise StaleMemoryHead("stale expected memory head")

            if db.execute("SELECT 1 FROM records WHERE record_id=?", (request.record_id,)).fetchone():
                raise MemoryLedgerError("record_id already exists")

            if request.supersedes is not None:
                predecessor = db.execute(
                    "SELECT status FROM records WHERE record_id=?",
                    (request.supersedes,),
                ).fetchone()
                if predecessor is None or predecessor["status"] != "CURRENT":
                    raise MemoryLedgerError("superseded predecessor is missing or non-current")
                db.execute(
                    "UPDATE records SET status='SUPERSEDED', superseded_by=? WHERE record_id=?",
                    (request.record_id, request.supersedes),
                )

            payload = self._record_payload(request)
            record_digest = sha256_hex(canonical_json_bytes(payload))
            db.execute(
                "INSERT INTO records(record_id,payload_json,status,superseded_by,record_digest) VALUES(?,?, 'CURRENT', NULL, ?)",
                (request.record_id, canonical_json(payload), record_digest),
            )

            new_generation = generation + 1
            head_material = {
                "previous_head": current_head,
                "generation": new_generation,
                "record_id": request.record_id,
                "record_digest": record_digest,
                "supersedes": request.supersedes,
            }
            new_head = sha256_hex(canonical_json_bytes(head_material))
            receipt = {
                "schema": "VERA_MONO_MEMORY_ADMISSION_RECEIPT_V1",
                "operation_id": request.operation_id,
                "record_id": request.record_id,
                "request_digest": request.request_digest,
                "record_digest": record_digest,
                "memory_class": request.memory_class.value,
                "project_id": request.project_id,
                "governed_identity_id": request.governed_identity_id,
                "authority_ref": request.authority_ref,
                "privacy_ref": request.privacy_ref,
                "provenance_refs": list(request.provenance_refs),
                "store_head": new_head,
                "generation": new_generation,
                "claim_ceiling": "LOCAL_DURABLE_RECORD_NOT_SELF_AUTHENTICATING_POLICY_OR_CURRENT_TRUTH",
            }
            db.execute(
                "INSERT INTO operations(operation_id,request_digest,record_id,receipt_json) VALUES(?,?,?,?)",
                (request.operation_id, request.request_digest, request.record_id, canonical_json(receipt)),
            )
            db.execute("UPDATE meta SET value=? WHERE key='generation'", (str(new_generation),))
            db.execute("UPDATE meta SET value=? WHERE key='head'", (new_head,))
            db.commit()
            return receipt

    def read(self, record_id: str, *, expected_head: str | None = None) -> MemoryRecord:
        with self._connect() as db:
            _, head = self._meta(db)
            if expected_head is not None and expected_head != head:
                raise StaleMemoryHead("memory head mismatch")
            row = db.execute(
                "SELECT payload_json,status,superseded_by,record_digest FROM records WHERE record_id=?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise KeyError(record_id)
            payload = json.loads(row["payload_json"])
            return MemoryRecord(
                record_id=payload["record_id"],
                text=payload["text"],
                memory_class=MemoryClass(payload["memory_class"]),
                source_actor=payload["source_actor"],
                authority_ref=payload["authority_ref"],
                privacy_ref=payload["privacy_ref"],
                provenance_refs=tuple(payload["provenance_refs"]),
                operation_id=payload["operation_id"],
                project_id=payload["project_id"],
                governed_identity_id=payload["governed_identity_id"],
                supersedes=payload["supersedes"],
                status=row["status"],
                superseded_by=row["superseded_by"],
                record_digest=row["record_digest"],
            )
