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


class RuntimeConsumptionVerificationError(ValueError):
    pass


RUNTIME_CONSUME_VERIFY_PREFIX = "RUNTIME_CONSUME_VERIFY"
RUNTIME_CONSUMPTION_STATUSES = frozenset({"PASS", "FAIL", "UNAVAILABLE"})


@dataclass(frozen=True, slots=True)
class RuntimeConsumptionRequirement:
    consumer_id: str
    route_id: str
    expected_target: str

    @classmethod
    def parse(cls, value: str) -> "RuntimeConsumptionRequirement":
        if type(value) is not str or not value:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption requirement must be non-empty string"
            )
        parts = value.split("|")
        if (
            len(parts) != 4
            or parts[0] != RUNTIME_CONSUME_VERIFY_PREFIX
            or any(not part for part in parts[1:])
        ):
            raise RuntimeConsumptionVerificationError(
                "runtime consumption requirement must use "
                "'RUNTIME_CONSUME_VERIFY|<consumer-id>|<route-id>|"
                "<expected-target>'"
            )
        return cls(
            consumer_id=parts[1],
            route_id=parts[2],
            expected_target=parts[3],
        )


def runtime_consumption_requirements(
    evidence_requirements: Sequence[str],
) -> tuple[RuntimeConsumptionRequirement, ...]:
    found: list[RuntimeConsumptionRequirement] = []
    for raw in evidence_requirements:
        if not isinstance(raw, str) or not raw.startswith(
            RUNTIME_CONSUME_VERIFY_PREFIX + "|"
        ):
            continue
        found.append(RuntimeConsumptionRequirement.parse(raw))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class RuntimeConsumptionObservation:
    consumer_id: str
    route_id: str | None
    consumed_target: str | None
    route_digest: str | None
    process_instance_id: str | None
    state_digest: str | None
    evidence_ref: str | None
    available: bool

    def validate(self) -> None:
        if type(self.consumer_id) is not str or not self.consumer_id:
            raise RuntimeConsumptionVerificationError(
                "consumer_id must be a non-empty exact string"
            )
        for label, value in (
            ("route_id", self.route_id),
            ("consumed_target", self.consumed_target),
            ("process_instance_id", self.process_instance_id),
            ("evidence_ref", self.evidence_ref),
        ):
            if value is not None and (
                type(value) is not str or not value
            ):
                raise RuntimeConsumptionVerificationError(
                    f"{label} must be None or non-empty exact string"
                )
        for label, value in (
            ("route_digest", self.route_digest),
            ("state_digest", self.state_digest),
        ):
            if value is not None:
                if type(value) is not str or len(value) != 64:
                    raise RuntimeConsumptionVerificationError(
                        f"{label} must be exact SHA-256 digest"
                    )
                try:
                    int(value, 16)
                except ValueError as exc:
                    raise RuntimeConsumptionVerificationError(
                        f"{label} must be hexadecimal"
                    ) from exc
        if type(self.available) is not bool:
            raise RuntimeConsumptionVerificationError(
                "available must be boolean"
            )
        if not self.available and any(
            value is not None
            for value in (
                self.route_id,
                self.consumed_target,
                self.route_digest,
                self.process_instance_id,
                self.state_digest,
                self.evidence_ref,
            )
        ):
            raise RuntimeConsumptionVerificationError(
                "unavailable consumer cannot carry observed runtime fields"
            )


@runtime_checkable
class RuntimeConsumptionVerificationTransport(Protocol):
    consumer_id: str

    def observe(
        self,
        route_id: str,
        expected_target: str,
    ) -> RuntimeConsumptionObservation:
        ...


@dataclass(frozen=True, slots=True)
class RuntimeConsumptionVerificationReceipt:
    sequence: int
    task_id: str
    packet_digest: str
    consumer_id: str
    expected_route_id: str
    expected_target: str
    observed_route_id: str | None
    consumed_target: str | None
    route_digest: str | None
    process_instance_id: str | None
    state_digest: str | None
    evidence_ref: str | None
    status: str
    predecessor_digest: str
    receipt_digest: str


class RuntimeConsumptionVerificationStore:
    """Append-only task-bound observations of live runtime consumption."""

    GENESIS_HEAD = sha256_hex(
        b"vera-mono-runtime-consumption-verification-genesis-v1"
    )

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
                    consumer_id TEXT NOT NULL,
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
        requirement: RuntimeConsumptionRequirement,
        observation: RuntimeConsumptionObservation,
    ) -> str:
        observation.validate()
        if observation.consumer_id != requirement.consumer_id:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption observation identity mismatch"
            )
        if not observation.available:
            return "UNAVAILABLE"
        if (
            observation.route_id != requirement.route_id
            or observation.consumed_target != requirement.expected_target
            or observation.route_digest is None
            or observation.process_instance_id is None
            or observation.state_digest is None
            or observation.evidence_ref is None
        ):
            return "FAIL"
        return "PASS"

    def append(
        self,
        *,
        task_id: str,
        packet_digest: str,
        requirement: RuntimeConsumptionRequirement,
        observation: RuntimeConsumptionObservation,
    ) -> RuntimeConsumptionVerificationReceipt:
        if type(task_id) is not str or not task_id:
            raise RuntimeConsumptionVerificationError(
                "task_id must be non-empty"
            )
        if type(packet_digest) is not str or len(packet_digest) != 64:
            raise RuntimeConsumptionVerificationError(
                "packet_digest must be exact SHA-256"
            )
        status = self._status(requirement, observation)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            payload = {
                "schema": "VERA_MONO_RUNTIME_CONSUMPTION_VERIFICATION_V1",
                "sequence": next_sequence,
                "task_id": task_id,
                "packet_digest": packet_digest,
                "consumer_id": requirement.consumer_id,
                "expected_route_id": requirement.route_id,
                "expected_target": requirement.expected_target,
                "observed_route_id": observation.route_id,
                "consumed_target": observation.consumed_target,
                "route_digest": observation.route_digest,
                "process_instance_id": observation.process_instance_id,
                "state_digest": observation.state_digest,
                "evidence_ref": observation.evidence_ref,
                "status": status,
                "predecessor_digest": predecessor,
            }
            digest = sha256_hex(canonical_json_bytes(payload))
            db.execute(
                """
                INSERT INTO observations(
                    sequence,task_id,consumer_id,receipt_digest,
                    predecessor_digest,payload_json
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    task_id,
                    requirement.consumer_id,
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
        return self.latest(task_id, requirement.consumer_id)

    def latest(
        self,
        task_id: str,
        consumer_id: str,
    ) -> RuntimeConsumptionVerificationReceipt:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM observations
                WHERE task_id=? AND consumer_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (task_id, consumer_id),
            ).fetchone()
        if row is None:
            raise KeyError((task_id, consumer_id))
        return self._row(row)

    def receipts(
        self,
        task_id: str | None = None,
    ) -> tuple[RuntimeConsumptionVerificationReceipt, ...]:
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
                raise RuntimeConsumptionVerificationError(
                    "runtime consumption verification sequence gap"
                )
            if receipt.predecessor_digest != predecessor:
                raise RuntimeConsumptionVerificationError(
                    "runtime consumption verification predecessor mismatch"
                )
            observed = sha256_hex(
                canonical_json_bytes(self._payload(receipt))
            )
            if observed != receipt.receipt_digest:
                raise RuntimeConsumptionVerificationError(
                    "runtime consumption verification receipt digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1
        if sequence != expected_sequence - 1:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption verification meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption verification meta head mismatch"
            )
        return head

    def context(self) -> dict[str, Any]:
        receipts = self.receipts()
        return {
            "schema": "VERA_MONO_RUNTIME_CONSUMPTION_CONTEXT_V1",
            "sequence": len(receipts),
            "head_digest": self.verify_chain(),
            "task_ids": sorted({receipt.task_id for receipt in receipts}),
            "latest": [
                {
                    "task_id": item.task_id,
                    "consumer_id": item.consumer_id,
                    "expected_route_id": item.expected_route_id,
                    "expected_target": item.expected_target,
                    "observed_route_id": item.observed_route_id,
                    "consumed_target": item.consumed_target,
                    "route_digest": item.route_digest,
                    "process_instance_id": item.process_instance_id,
                    "state_digest": item.state_digest,
                    "status": item.status,
                    "receipt_digest": item.receipt_digest,
                }
                for item in receipts
            ],
        }

    @staticmethod
    def _payload(
        receipt: RuntimeConsumptionVerificationReceipt,
    ) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_RUNTIME_CONSUMPTION_VERIFICATION_V1",
            "sequence": receipt.sequence,
            "task_id": receipt.task_id,
            "packet_digest": receipt.packet_digest,
            "consumer_id": receipt.consumer_id,
            "expected_route_id": receipt.expected_route_id,
            "expected_target": receipt.expected_target,
            "observed_route_id": receipt.observed_route_id,
            "consumed_target": receipt.consumed_target,
            "route_digest": receipt.route_digest,
            "process_instance_id": receipt.process_instance_id,
            "state_digest": receipt.state_digest,
            "evidence_ref": receipt.evidence_ref,
            "status": receipt.status,
            "predecessor_digest": receipt.predecessor_digest,
        }

    @classmethod
    def _row(
        cls,
        row: sqlite3.Row,
    ) -> RuntimeConsumptionVerificationReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption verification payload is invalid JSON"
            ) from exc
        required = {
            "schema",
            "sequence",
            "task_id",
            "packet_digest",
            "consumer_id",
            "expected_route_id",
            "expected_target",
            "observed_route_id",
            "consumed_target",
            "route_digest",
            "process_instance_id",
            "state_digest",
            "evidence_ref",
            "status",
            "predecessor_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption verification payload field set mismatch"
            )
        if (
            payload["schema"]
            != "VERA_MONO_RUNTIME_CONSUMPTION_VERIFICATION_V1"
        ):
            raise RuntimeConsumptionVerificationError(
                "unsupported runtime consumption verification schema"
            )
        if payload["status"] not in RUNTIME_CONSUMPTION_STATUSES:
            raise RuntimeConsumptionVerificationError(
                "unsupported runtime consumption verification status"
            )
        if (
            int(payload["sequence"]) != int(row["sequence"])
            or payload["task_id"] != row["task_id"]
            or payload["consumer_id"] != row["consumer_id"]
            or payload["predecessor_digest"] != row["predecessor_digest"]
        ):
            raise RuntimeConsumptionVerificationError(
                "runtime consumption verification row/payload mismatch"
            )
        receipt = RuntimeConsumptionVerificationReceipt(
            sequence=int(payload["sequence"]),
            task_id=payload["task_id"],
            packet_digest=payload["packet_digest"],
            consumer_id=payload["consumer_id"],
            expected_route_id=payload["expected_route_id"],
            expected_target=payload["expected_target"],
            observed_route_id=payload["observed_route_id"],
            consumed_target=payload["consumed_target"],
            route_digest=payload["route_digest"],
            process_instance_id=payload["process_instance_id"],
            state_digest=payload["state_digest"],
            evidence_ref=payload["evidence_ref"],
            status=payload["status"],
            predecessor_digest=payload["predecessor_digest"],
            receipt_digest=str(row["receipt_digest"]),
        )
        if (
            sha256_hex(canonical_json_bytes(cls._payload(receipt)))
            != receipt.receipt_digest
        ):
            raise RuntimeConsumptionVerificationError(
                "runtime consumption verification receipt digest mismatch"
            )
        return receipt


class JsonFileRuntimeConsumptionTransport:
    """Read-only runtime-consumption observer for one host-written JSON file."""

    def __init__(
        self,
        *,
        consumer_id: str,
        path: str | Path,
        route_field: str = "route_id",
        target_field: str = "target",
        route_digest_field: str = "route_digest",
        process_instance_field: str = "process_instance_id",
    ):
        for label, value in (
            ("consumer_id", consumer_id),
            ("route_field", route_field),
            ("target_field", target_field),
            ("route_digest_field", route_digest_field),
            ("process_instance_field", process_instance_field),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be non-empty exact string")
        self.consumer_id = consumer_id
        self.path = Path(path).expanduser().resolve()
        self.route_field = route_field
        self.target_field = target_field
        self.route_digest_field = route_digest_field
        self.process_instance_field = process_instance_field

    def observe(
        self,
        route_id: str,
        expected_target: str,
    ) -> RuntimeConsumptionObservation:
        del route_id, expected_target
        if not self.path.is_file():
            return RuntimeConsumptionObservation(
                consumer_id=self.consumer_id,
                route_id=None,
                consumed_target=None,
                route_digest=None,
                process_instance_id=None,
                state_digest=None,
                evidence_ref=None,
                available=False,
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption file is not readable JSON evidence"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeConsumptionVerificationError(
                "runtime consumption file top level must be JSON object"
            )
        values = {
            "route_id": payload.get(self.route_field),
            "consumed_target": payload.get(self.target_field),
            "route_digest": payload.get(self.route_digest_field),
            "process_instance_id": payload.get(self.process_instance_field),
        }
        for label, value in values.items():
            if type(value) is not str or not value:
                raise RuntimeConsumptionVerificationError(
                    f"runtime consumption {label} must be non-empty string"
                )
        observation = RuntimeConsumptionObservation(
            consumer_id=self.consumer_id,
            route_id=values["route_id"],
            consumed_target=values["consumed_target"],
            route_digest=values["route_digest"],
            process_instance_id=values["process_instance_id"],
            state_digest=sha256_hex(canonical_json_bytes(payload)),
            evidence_ref=str(self.path),
            available=True,
        )
        observation.validate()
        return observation
