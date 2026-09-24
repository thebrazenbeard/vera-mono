from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any, Protocol, Sequence, runtime_checkable

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)


class RouteVerificationError(ValueError):
    pass


ROUTE_VERIFY_PREFIX = "ROUTE_VERIFY"
ROUTE_VERIFICATION_STATUSES = frozenset({"PASS", "FAIL", "UNAVAILABLE"})


@dataclass(frozen=True, slots=True)
class RouteVerificationRequirement:
    route_id: str
    expected_target: str

    @classmethod
    def parse(cls, value: str) -> "RouteVerificationRequirement":
        if type(value) is not str or not value:
            raise RouteVerificationError(
                "route verification requirement must be non-empty string"
            )
        parts = value.split("|")
        if (
            len(parts) != 3
            or parts[0] != ROUTE_VERIFY_PREFIX
            or any(not part for part in parts[1:])
        ):
            raise RouteVerificationError(
                "route verification requirement must use "
                "'ROUTE_VERIFY|<route-id>|<expected-target>'"
            )
        return cls(route_id=parts[1], expected_target=parts[2])


def route_verification_requirements(
    evidence_requirements: Sequence[str],
) -> tuple[RouteVerificationRequirement, ...]:
    found: list[RouteVerificationRequirement] = []
    for raw in evidence_requirements:
        if not isinstance(raw, str) or not raw.startswith(
            ROUTE_VERIFY_PREFIX + "|"
        ):
            continue
        found.append(RouteVerificationRequirement.parse(raw))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class RouteObservation:
    route_id: str
    selected_target: str | None
    route_digest: str | None
    evidence_ref: str | None
    available: bool

    def validate(self) -> None:
        if type(self.route_id) is not str or not self.route_id:
            raise RouteVerificationError(
                "route_id must be a non-empty exact string"
            )
        for label, value in (
            ("selected_target", self.selected_target),
            ("route_digest", self.route_digest),
            ("evidence_ref", self.evidence_ref),
        ):
            if value is not None and (
                type(value) is not str or not value
            ):
                raise RouteVerificationError(
                    f"{label} must be None or non-empty exact string"
                )
        if self.route_digest is not None:
            if len(self.route_digest) != 64:
                raise RouteVerificationError(
                    "route_digest must be exact SHA-256 digest"
                )
            try:
                int(self.route_digest, 16)
            except ValueError as exc:
                raise RouteVerificationError(
                    "route_digest must be hexadecimal"
                ) from exc
        if type(self.available) is not bool:
            raise RouteVerificationError("available must be boolean")
        if not self.available and any(
            value is not None
            for value in (
                self.selected_target,
                self.route_digest,
                self.evidence_ref,
            )
        ):
            raise RouteVerificationError(
                "unavailable route cannot carry observed route fields"
            )


@runtime_checkable
class RouteVerificationTransport(Protocol):
    route_id: str

    def observe(self, expected_target: str) -> RouteObservation:
        ...


@dataclass(frozen=True, slots=True)
class RouteVerificationReceipt:
    sequence: int
    task_id: str
    packet_digest: str
    route_id: str
    expected_target: str
    selected_target: str | None
    route_digest: str | None
    evidence_ref: str | None
    status: str
    predecessor_digest: str
    receipt_digest: str


class RouteVerificationStore:
    """Append-only task-bound current-route observations."""

    GENESIS_HEAD = sha256_hex(b"vera-mono-route-verification-genesis-v1")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    sequence INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    route_id TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    predecessor_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            if db.execute(
                "SELECT 1 FROM meta WHERE key='sequence'"
            ).fetchone() is None:
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('sequence','0')"
                )
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('head',?)",
                    (self.GENESIS_HEAD,),
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, str]:
        sequence = int(
            db.execute(
                "SELECT value FROM meta WHERE key='sequence'"
            ).fetchone()[0]
        )
        head = str(
            db.execute(
                "SELECT value FROM meta WHERE key='head'"
            ).fetchone()[0]
        )
        return sequence, head

    @staticmethod
    def _status(
        requirement: RouteVerificationRequirement,
        observation: RouteObservation,
    ) -> str:
        observation.validate()
        if observation.route_id != requirement.route_id:
            raise RouteVerificationError(
                "route observation identity mismatch"
            )
        if not observation.available:
            return "UNAVAILABLE"
        if (
            observation.selected_target != requirement.expected_target
            or observation.route_digest is None
            or observation.evidence_ref is None
        ):
            return "FAIL"
        return "PASS"

    def append(
        self,
        *,
        task_id: str,
        packet_digest: str,
        requirement: RouteVerificationRequirement,
        observation: RouteObservation,
    ) -> RouteVerificationReceipt:
        if type(task_id) is not str or not task_id:
            raise RouteVerificationError("task_id must be non-empty")
        if type(packet_digest) is not str or len(packet_digest) != 64:
            raise RouteVerificationError(
                "packet_digest must be exact SHA-256"
            )
        status = self._status(requirement, observation)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            payload = {
                "schema": "VERA_MONO_ROUTE_VERIFICATION_V1",
                "sequence": next_sequence,
                "task_id": task_id,
                "packet_digest": packet_digest,
                "route_id": requirement.route_id,
                "expected_target": requirement.expected_target,
                "selected_target": observation.selected_target,
                "route_digest": observation.route_digest,
                "evidence_ref": observation.evidence_ref,
                "status": status,
                "predecessor_digest": predecessor,
            }
            digest = sha256_hex(canonical_json_bytes(payload))
            db.execute(
                """
                INSERT INTO observations(
                    sequence,task_id,route_id,receipt_digest,
                    predecessor_digest,payload_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    task_id,
                    requirement.route_id,
                    digest,
                    predecessor,
                    canonical_json(payload),
                ),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='sequence'",
                (str(next_sequence),),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='head'",
                (digest,),
            )
            db.commit()
        return self.latest(task_id, requirement.route_id)

    def latest(
        self,
        task_id: str,
        route_id: str,
    ) -> RouteVerificationReceipt:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM observations
                WHERE task_id=? AND route_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (task_id, route_id),
            ).fetchone()
        if row is None:
            raise KeyError((task_id, route_id))
        return self._row(row)

    def receipts(
        self,
        task_id: str | None = None,
    ) -> tuple[RouteVerificationReceipt, ...]:
        with self._connect() as db:
            if task_id is None:
                rows = db.execute(
                    "SELECT * FROM observations ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM observations
                    WHERE task_id=?
                    ORDER BY sequence
                    """,
                    (task_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM observations ORDER BY sequence"
            ).fetchall()
            sequence, head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        for row in rows:
            receipt = self._row(row)
            if receipt.sequence != expected_sequence:
                raise RouteVerificationError(
                    "route verification sequence gap"
                )
            if receipt.predecessor_digest != predecessor:
                raise RouteVerificationError(
                    "route verification predecessor mismatch"
                )
            observed = sha256_hex(
                canonical_json_bytes(self._payload(receipt))
            )
            if observed != receipt.receipt_digest:
                raise RouteVerificationError(
                    "route verification receipt digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1
        if sequence != expected_sequence - 1:
            raise RouteVerificationError(
                "route verification meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise RouteVerificationError(
                "route verification meta head mismatch"
            )
        return head

    def context(self) -> dict[str, Any]:
        receipts = self.receipts()
        return {
            "schema": "VERA_MONO_ROUTE_VERIFICATION_CONTEXT_V1",
            "sequence": len(receipts),
            "head_digest": self.verify_chain(),
            "task_ids": sorted({receipt.task_id for receipt in receipts}),
            "latest": [
                {
                    "task_id": item.task_id,
                    "route_id": item.route_id,
                    "expected_target": item.expected_target,
                    "selected_target": item.selected_target,
                    "route_digest": item.route_digest,
                    "status": item.status,
                    "receipt_digest": item.receipt_digest,
                }
                for item in receipts
            ],
        }

    @staticmethod
    def _payload(
        receipt: RouteVerificationReceipt,
    ) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_ROUTE_VERIFICATION_V1",
            "sequence": receipt.sequence,
            "task_id": receipt.task_id,
            "packet_digest": receipt.packet_digest,
            "route_id": receipt.route_id,
            "expected_target": receipt.expected_target,
            "selected_target": receipt.selected_target,
            "route_digest": receipt.route_digest,
            "evidence_ref": receipt.evidence_ref,
            "status": receipt.status,
            "predecessor_digest": receipt.predecessor_digest,
        }

    @classmethod
    def _row(cls, row: sqlite3.Row) -> RouteVerificationReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise RouteVerificationError(
                "route verification payload is invalid JSON"
            ) from exc
        required = {
            "schema",
            "sequence",
            "task_id",
            "packet_digest",
            "route_id",
            "expected_target",
            "selected_target",
            "route_digest",
            "evidence_ref",
            "status",
            "predecessor_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise RouteVerificationError(
                "route verification payload field set mismatch"
            )
        if payload["schema"] != "VERA_MONO_ROUTE_VERIFICATION_V1":
            raise RouteVerificationError(
                "unsupported route verification schema"
            )
        if payload["status"] not in ROUTE_VERIFICATION_STATUSES:
            raise RouteVerificationError(
                "unsupported persisted route verification status"
            )
        if (
            int(payload["sequence"]) != int(row["sequence"])
            or payload["task_id"] != row["task_id"]
            or payload["route_id"] != row["route_id"]
            or payload["predecessor_digest"] != row["predecessor_digest"]
        ):
            raise RouteVerificationError(
                "route verification row/payload mismatch"
            )
        receipt = RouteVerificationReceipt(
            sequence=int(payload["sequence"]),
            task_id=payload["task_id"],
            packet_digest=payload["packet_digest"],
            route_id=payload["route_id"],
            expected_target=payload["expected_target"],
            selected_target=payload["selected_target"],
            route_digest=payload["route_digest"],
            evidence_ref=payload["evidence_ref"],
            status=payload["status"],
            predecessor_digest=payload["predecessor_digest"],
            receipt_digest=str(row["receipt_digest"]),
        )
        if (
            sha256_hex(canonical_json_bytes(cls._payload(receipt)))
            != receipt.receipt_digest
        ):
            raise RouteVerificationError(
                "route verification receipt digest mismatch"
            )
        return receipt


class JsonFileRouteVerificationTransport:
    """Read-only exact target selector for one JSON route file."""

    def __init__(
        self,
        *,
        route_id: str,
        path: str | Path,
        target_field: str = "target",
    ):
        if type(route_id) is not str or not route_id:
            raise ValueError("route_id must be non-empty exact string")
        if type(target_field) is not str or not target_field:
            raise ValueError("target_field must be non-empty exact string")
        self.route_id = route_id
        self.path = Path(path).expanduser().resolve()
        self.target_field = target_field

    def observe(self, expected_target: str) -> RouteObservation:
        del expected_target
        if not self.path.is_file():
            return RouteObservation(
                route_id=self.route_id,
                selected_target=None,
                route_digest=None,
                evidence_ref=None,
                available=False,
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RouteVerificationError(
                "route file is not readable canonical JSON evidence"
            ) from exc
        if not isinstance(payload, dict):
            raise RouteVerificationError(
                "route file top level must be a JSON object"
            )
        selected = payload.get(self.target_field)
        if type(selected) is not str or not selected:
            raise RouteVerificationError(
                "route target field must be a non-empty exact string"
            )
        return RouteObservation(
            route_id=self.route_id,
            selected_target=selected,
            route_digest=sha256_hex(canonical_json_bytes(payload)),
            evidence_ref=str(self.path),
            available=True,
        )
