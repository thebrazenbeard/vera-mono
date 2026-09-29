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


class BehaviorEffectVerificationError(ValueError):
    pass


BEHAVIOR_EFFECT_VERIFY_PREFIX = "BEHAVIOR_EFFECT_VERIFY"
BEHAVIOR_EFFECT_KINDS = frozenset({"BEHAVIOR", "EFFECT"})
BEHAVIOR_EFFECT_STATUSES = frozenset({"PASS", "FAIL", "UNAVAILABLE"})


def _require_digest(value: str, label: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise BehaviorEffectVerificationError(
            f"{label} must be an exact SHA-256 digest"
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise BehaviorEffectVerificationError(
            f"{label} must be hexadecimal"
        ) from exc
    return value.lower()


@dataclass(frozen=True, slots=True)
class BehaviorEffectRequirement:
    consumer_id: str
    probe_id: str
    evidence_kind: str
    expected_stimulus_digest: str
    expected_outcome_digest: str

    @classmethod
    def parse(cls, value: str) -> "BehaviorEffectRequirement":
        if type(value) is not str or not value:
            raise BehaviorEffectVerificationError(
                "behavior/effect requirement must be non-empty string"
            )
        parts = value.split("|")
        if (
            len(parts) != 6
            or parts[0] != BEHAVIOR_EFFECT_VERIFY_PREFIX
            or any(not part for part in parts[1:])
        ):
            raise BehaviorEffectVerificationError(
                "behavior/effect requirement must use "
                "'BEHAVIOR_EFFECT_VERIFY|<consumer-id>|<probe-id>|"
                "<BEHAVIOR-or-EFFECT>|<stimulus-sha256>|<outcome-sha256>'"
            )
        kind = parts[3]
        if kind not in BEHAVIOR_EFFECT_KINDS:
            raise BehaviorEffectVerificationError(
                f"unsupported behavior/effect kind: {kind!r}"
            )
        return cls(
            consumer_id=parts[1],
            probe_id=parts[2],
            evidence_kind=kind,
            expected_stimulus_digest=_require_digest(
                parts[4],
                "expected_stimulus_digest",
            ),
            expected_outcome_digest=_require_digest(
                parts[5],
                "expected_outcome_digest",
            ),
        )


def behavior_effect_requirements(
    evidence_requirements: Sequence[str],
) -> tuple[BehaviorEffectRequirement, ...]:
    found: list[BehaviorEffectRequirement] = []
    for raw in evidence_requirements:
        if not isinstance(raw, str) or not raw.startswith(
            BEHAVIOR_EFFECT_VERIFY_PREFIX + "|"
        ):
            continue
        found.append(BehaviorEffectRequirement.parse(raw))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class BehaviorEffectObservation:
    consumer_id: str
    probe_id: str
    evidence_kind: str
    process_instance_id: str | None
    runtime_state_digest: str | None
    stimulus_digest: str | None
    observed_outcome_digest: str | None
    external_effect_id: str | None
    external_effect_receipt_digest: str | None
    external_evidence_digest: str | None
    evidence_ref: str | None
    available: bool

    def validate(self) -> None:
        for label, value in (
            ("consumer_id", self.consumer_id),
            ("probe_id", self.probe_id),
            ("evidence_kind", self.evidence_kind),
        ):
            if type(value) is not str or not value:
                raise BehaviorEffectVerificationError(
                    f"{label} must be a non-empty exact string"
                )
        if self.evidence_kind not in BEHAVIOR_EFFECT_KINDS:
            raise BehaviorEffectVerificationError(
                f"unsupported behavior/effect kind: {self.evidence_kind!r}"
            )
        if type(self.available) is not bool:
            raise BehaviorEffectVerificationError(
                "available must be boolean"
            )
        observed = (
            self.process_instance_id,
            self.runtime_state_digest,
            self.stimulus_digest,
            self.observed_outcome_digest,
            self.external_effect_id,
            self.external_effect_receipt_digest,
            self.external_evidence_digest,
            self.evidence_ref,
        )
        if not self.available:
            if any(value is not None for value in observed):
                raise BehaviorEffectVerificationError(
                    "unavailable behavior/effect observation cannot carry "
                    "observed evidence fields"
                )
            return

        for label, value in (
            ("process_instance_id", self.process_instance_id),
            ("evidence_ref", self.evidence_ref),
        ):
            if type(value) is not str or not value:
                raise BehaviorEffectVerificationError(
                    f"{label} must be a non-empty exact string when available"
                )
        for label, value in (
            ("runtime_state_digest", self.runtime_state_digest),
            ("stimulus_digest", self.stimulus_digest),
            ("observed_outcome_digest", self.observed_outcome_digest),
            ("external_evidence_digest", self.external_evidence_digest),
        ):
            if value is None:
                raise BehaviorEffectVerificationError(
                    f"{label} is required when behavior/effect evidence is available"
                )
            _require_digest(value, label)

        if self.evidence_kind == "BEHAVIOR":
            if (
                self.external_effect_id is not None
                or self.external_effect_receipt_digest is not None
            ):
                raise BehaviorEffectVerificationError(
                    "BEHAVIOR observation must not claim external effect receipt"
                )
        else:
            if (
                type(self.external_effect_id) is not str
                or not self.external_effect_id
            ):
                raise BehaviorEffectVerificationError(
                    "EFFECT observation requires external_effect_id"
                )
            if self.external_effect_receipt_digest is None:
                raise BehaviorEffectVerificationError(
                    "EFFECT observation requires external_effect_receipt_digest"
                )
            _require_digest(
                self.external_effect_receipt_digest,
                "external_effect_receipt_digest",
            )


@runtime_checkable
class BehaviorEffectVerificationTransport(Protocol):
    consumer_id: str

    def observe(
        self,
        probe_id: str,
        evidence_kind: str,
        expected_stimulus_digest: str,
        expected_outcome_digest: str,
    ) -> BehaviorEffectObservation:
        ...


@dataclass(frozen=True, slots=True)
class BehaviorEffectVerificationReceipt:
    sequence: int
    task_id: str
    packet_digest: str
    consumer_id: str
    probe_id: str
    evidence_kind: str
    expected_stimulus_digest: str
    expected_outcome_digest: str
    runtime_consumption_receipt_digest: str
    consumed_process_instance_id: str
    consumed_runtime_state_digest: str
    observed_process_instance_id: str | None
    observed_runtime_state_digest: str | None
    observed_stimulus_digest: str | None
    observed_outcome_digest: str | None
    external_effect_id: str | None
    external_effect_receipt_digest: str | None
    external_evidence_digest: str | None
    evidence_ref: str | None
    status: str
    predecessor_digest: str
    receipt_digest: str


class BehaviorEffectVerificationStore:
    """Append-only evidence that a specific live consumed runtime exhibited a probe."""

    GENESIS_HEAD = sha256_hex(
        b"vera-mono-behavior-effect-verification-genesis-v1"
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
                    probe_id TEXT NOT NULL,
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
        requirement: BehaviorEffectRequirement,
        observation: BehaviorEffectObservation,
        *,
        consumed_process_instance_id: str,
        consumed_runtime_state_digest: str,
    ) -> str:
        observation.validate()
        if (
            observation.consumer_id != requirement.consumer_id
            or observation.probe_id != requirement.probe_id
            or observation.evidence_kind != requirement.evidence_kind
        ):
            raise BehaviorEffectVerificationError(
                "behavior/effect observation identity mismatch"
            )
        if not observation.available:
            return "UNAVAILABLE"
        if (
            observation.process_instance_id != consumed_process_instance_id
            or observation.runtime_state_digest
            != consumed_runtime_state_digest
            or observation.stimulus_digest
            != requirement.expected_stimulus_digest
            or observation.observed_outcome_digest
            != requirement.expected_outcome_digest
            or observation.external_evidence_digest is None
            or observation.evidence_ref is None
        ):
            return "FAIL"
        if requirement.evidence_kind == "EFFECT" and (
            observation.external_effect_id is None
            or observation.external_effect_receipt_digest is None
        ):
            return "FAIL"
        return "PASS"

    def append(
        self,
        *,
        task_id: str,
        packet_digest: str,
        requirement: BehaviorEffectRequirement,
        runtime_consumption_receipt_digest: str,
        consumed_process_instance_id: str,
        consumed_runtime_state_digest: str,
        observation: BehaviorEffectObservation,
    ) -> BehaviorEffectVerificationReceipt:
        if type(task_id) is not str or not task_id:
            raise BehaviorEffectVerificationError(
                "task_id must be non-empty"
            )
        _require_digest(packet_digest, "packet_digest")
        _require_digest(
            runtime_consumption_receipt_digest,
            "runtime_consumption_receipt_digest",
        )
        if (
            type(consumed_process_instance_id) is not str
            or not consumed_process_instance_id
        ):
            raise BehaviorEffectVerificationError(
                "consumed_process_instance_id must be non-empty"
            )
        _require_digest(
            consumed_runtime_state_digest,
            "consumed_runtime_state_digest",
        )
        status = self._status(
            requirement,
            observation,
            consumed_process_instance_id=consumed_process_instance_id,
            consumed_runtime_state_digest=consumed_runtime_state_digest,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            payload = {
                "schema": "VERA_MONO_BEHAVIOR_EFFECT_VERIFICATION_V1",
                "sequence": next_sequence,
                "task_id": task_id,
                "packet_digest": packet_digest,
                "consumer_id": requirement.consumer_id,
                "probe_id": requirement.probe_id,
                "evidence_kind": requirement.evidence_kind,
                "expected_stimulus_digest": (
                    requirement.expected_stimulus_digest
                ),
                "expected_outcome_digest": (
                    requirement.expected_outcome_digest
                ),
                "runtime_consumption_receipt_digest": (
                    runtime_consumption_receipt_digest
                ),
                "consumed_process_instance_id": (
                    consumed_process_instance_id
                ),
                "consumed_runtime_state_digest": (
                    consumed_runtime_state_digest
                ),
                "observed_process_instance_id": (
                    observation.process_instance_id
                ),
                "observed_runtime_state_digest": (
                    observation.runtime_state_digest
                ),
                "observed_stimulus_digest": observation.stimulus_digest,
                "observed_outcome_digest": (
                    observation.observed_outcome_digest
                ),
                "external_effect_id": observation.external_effect_id,
                "external_effect_receipt_digest": (
                    observation.external_effect_receipt_digest
                ),
                "external_evidence_digest": (
                    observation.external_evidence_digest
                ),
                "evidence_ref": observation.evidence_ref,
                "status": status,
                "predecessor_digest": predecessor,
            }
            digest = sha256_hex(canonical_json_bytes(payload))
            db.execute(
                """
                INSERT INTO observations(
                    sequence,task_id,consumer_id,probe_id,
                    receipt_digest,predecessor_digest,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    task_id,
                    requirement.consumer_id,
                    requirement.probe_id,
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
        return self.latest(
            task_id,
            requirement.consumer_id,
            requirement.probe_id,
        )

    def latest(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorEffectVerificationReceipt:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM observations
                WHERE task_id=? AND consumer_id=? AND probe_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (task_id, consumer_id, probe_id),
            ).fetchone()
        if row is None:
            raise KeyError((task_id, consumer_id, probe_id))
        return self._row(row)

    def receipts(
        self,
        task_id: str | None = None,
    ) -> tuple[BehaviorEffectVerificationReceipt, ...]:
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
                raise BehaviorEffectVerificationError(
                    "behavior/effect verification sequence gap"
                )
            if receipt.predecessor_digest != predecessor:
                raise BehaviorEffectVerificationError(
                    "behavior/effect verification predecessor mismatch"
                )
            observed = sha256_hex(
                canonical_json_bytes(self._payload(receipt))
            )
            if observed != receipt.receipt_digest:
                raise BehaviorEffectVerificationError(
                    "behavior/effect verification receipt digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1
        if sequence != expected_sequence - 1:
            raise BehaviorEffectVerificationError(
                "behavior/effect verification meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise BehaviorEffectVerificationError(
                "behavior/effect verification meta head mismatch"
            )
        return head

    def context(self) -> dict[str, Any]:
        receipts = self.receipts()
        return {
            "schema": "VERA_MONO_BEHAVIOR_EFFECT_CONTEXT_V1",
            "sequence": len(receipts),
            "head_digest": self.verify_chain(),
            "task_ids": sorted({receipt.task_id for receipt in receipts}),
            "latest": [
                {
                    "task_id": item.task_id,
                    "consumer_id": item.consumer_id,
                    "probe_id": item.probe_id,
                    "evidence_kind": item.evidence_kind,
                    "status": item.status,
                    "runtime_consumption_receipt_digest": (
                        item.runtime_consumption_receipt_digest
                    ),
                    "observed_process_instance_id": (
                        item.observed_process_instance_id
                    ),
                    "observed_runtime_state_digest": (
                        item.observed_runtime_state_digest
                    ),
                    "external_effect_id": item.external_effect_id,
                    "external_evidence_digest": (
                        item.external_evidence_digest
                    ),
                    "receipt_digest": item.receipt_digest,
                }
                for item in receipts
            ],
        }

    @staticmethod
    def _payload(
        receipt: BehaviorEffectVerificationReceipt,
    ) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_BEHAVIOR_EFFECT_VERIFICATION_V1",
            "sequence": receipt.sequence,
            "task_id": receipt.task_id,
            "packet_digest": receipt.packet_digest,
            "consumer_id": receipt.consumer_id,
            "probe_id": receipt.probe_id,
            "evidence_kind": receipt.evidence_kind,
            "expected_stimulus_digest": receipt.expected_stimulus_digest,
            "expected_outcome_digest": receipt.expected_outcome_digest,
            "runtime_consumption_receipt_digest": (
                receipt.runtime_consumption_receipt_digest
            ),
            "consumed_process_instance_id": (
                receipt.consumed_process_instance_id
            ),
            "consumed_runtime_state_digest": (
                receipt.consumed_runtime_state_digest
            ),
            "observed_process_instance_id": (
                receipt.observed_process_instance_id
            ),
            "observed_runtime_state_digest": (
                receipt.observed_runtime_state_digest
            ),
            "observed_stimulus_digest": receipt.observed_stimulus_digest,
            "observed_outcome_digest": receipt.observed_outcome_digest,
            "external_effect_id": receipt.external_effect_id,
            "external_effect_receipt_digest": (
                receipt.external_effect_receipt_digest
            ),
            "external_evidence_digest": receipt.external_evidence_digest,
            "evidence_ref": receipt.evidence_ref,
            "status": receipt.status,
            "predecessor_digest": receipt.predecessor_digest,
        }

    @classmethod
    def _row(
        cls,
        row: sqlite3.Row,
    ) -> BehaviorEffectVerificationReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise BehaviorEffectVerificationError(
                "behavior/effect verification payload is invalid JSON"
            ) from exc
        required = {
            "schema",
            "sequence",
            "task_id",
            "packet_digest",
            "consumer_id",
            "probe_id",
            "evidence_kind",
            "expected_stimulus_digest",
            "expected_outcome_digest",
            "runtime_consumption_receipt_digest",
            "consumed_process_instance_id",
            "consumed_runtime_state_digest",
            "observed_process_instance_id",
            "observed_runtime_state_digest",
            "observed_stimulus_digest",
            "observed_outcome_digest",
            "external_effect_id",
            "external_effect_receipt_digest",
            "external_evidence_digest",
            "evidence_ref",
            "status",
            "predecessor_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise BehaviorEffectVerificationError(
                "behavior/effect verification payload field set mismatch"
            )
        if (
            payload["schema"]
            != "VERA_MONO_BEHAVIOR_EFFECT_VERIFICATION_V1"
        ):
            raise BehaviorEffectVerificationError(
                "unsupported behavior/effect verification schema"
            )
        if payload["status"] not in BEHAVIOR_EFFECT_STATUSES:
            raise BehaviorEffectVerificationError(
                "unsupported behavior/effect verification status"
            )
        if payload["evidence_kind"] not in BEHAVIOR_EFFECT_KINDS:
            raise BehaviorEffectVerificationError(
                "unsupported behavior/effect evidence kind"
            )
        if (
            int(payload["sequence"]) != int(row["sequence"])
            or payload["task_id"] != row["task_id"]
            or payload["consumer_id"] != row["consumer_id"]
            or payload["probe_id"] != row["probe_id"]
            or payload["predecessor_digest"] != row["predecessor_digest"]
        ):
            raise BehaviorEffectVerificationError(
                "behavior/effect verification row/payload mismatch"
            )
        receipt = BehaviorEffectVerificationReceipt(
            sequence=int(payload["sequence"]),
            task_id=payload["task_id"],
            packet_digest=payload["packet_digest"],
            consumer_id=payload["consumer_id"],
            probe_id=payload["probe_id"],
            evidence_kind=payload["evidence_kind"],
            expected_stimulus_digest=payload["expected_stimulus_digest"],
            expected_outcome_digest=payload["expected_outcome_digest"],
            runtime_consumption_receipt_digest=(
                payload["runtime_consumption_receipt_digest"]
            ),
            consumed_process_instance_id=(
                payload["consumed_process_instance_id"]
            ),
            consumed_runtime_state_digest=(
                payload["consumed_runtime_state_digest"]
            ),
            observed_process_instance_id=(
                payload["observed_process_instance_id"]
            ),
            observed_runtime_state_digest=(
                payload["observed_runtime_state_digest"]
            ),
            observed_stimulus_digest=payload["observed_stimulus_digest"],
            observed_outcome_digest=payload["observed_outcome_digest"],
            external_effect_id=payload["external_effect_id"],
            external_effect_receipt_digest=(
                payload["external_effect_receipt_digest"]
            ),
            external_evidence_digest=payload["external_evidence_digest"],
            evidence_ref=payload["evidence_ref"],
            status=payload["status"],
            predecessor_digest=payload["predecessor_digest"],
            receipt_digest=str(row["receipt_digest"]),
        )
        if (
            sha256_hex(canonical_json_bytes(cls._payload(receipt)))
            != receipt.receipt_digest
        ):
            raise BehaviorEffectVerificationError(
                "behavior/effect verification receipt digest mismatch"
            )
        return receipt


class JsonFileBehaviorEffectVerificationTransport:
    """Read-only observer for exact host/external behavior evidence in JSON."""

    def __init__(
        self,
        *,
        consumer_id: str,
        path: str | Path,
    ):
        if type(consumer_id) is not str or not consumer_id:
            raise ValueError("consumer_id must be non-empty")
        self.consumer_id = consumer_id
        self.path = Path(path)

    def observe(
        self,
        probe_id: str,
        evidence_kind: str,
        expected_stimulus_digest: str,
        expected_outcome_digest: str,
    ) -> BehaviorEffectObservation:
        del expected_stimulus_digest, expected_outcome_digest
        if not self.path.is_file():
            return BehaviorEffectObservation(
                consumer_id=self.consumer_id,
                probe_id=probe_id,
                evidence_kind=evidence_kind,
                process_instance_id=None,
                runtime_state_digest=None,
                stimulus_digest=None,
                observed_outcome_digest=None,
                external_effect_id=None,
                external_effect_receipt_digest=None,
                external_evidence_digest=None,
                evidence_ref=None,
                available=False,
            )
        raw = self.path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BehaviorEffectVerificationError(
                "behavior/effect evidence file is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise BehaviorEffectVerificationError(
                "behavior/effect evidence file must contain a JSON object"
            )
        if payload.get("consumer_id", self.consumer_id) != self.consumer_id:
            raise BehaviorEffectVerificationError(
                "behavior/effect evidence consumer_id mismatch"
            )
        if payload.get("probe_id") != probe_id:
            raise BehaviorEffectVerificationError(
                "behavior/effect evidence probe_id mismatch"
            )
        if payload.get("evidence_kind") != evidence_kind:
            raise BehaviorEffectVerificationError(
                "behavior/effect evidence kind mismatch"
            )
        observation = BehaviorEffectObservation(
            consumer_id=self.consumer_id,
            probe_id=probe_id,
            evidence_kind=evidence_kind,
            process_instance_id=payload.get("process_instance_id"),
            runtime_state_digest=payload.get("runtime_state_digest"),
            stimulus_digest=payload.get("stimulus_digest"),
            observed_outcome_digest=payload.get("outcome_digest"),
            external_effect_id=payload.get("external_effect_id"),
            external_effect_receipt_digest=payload.get(
                "external_effect_receipt_digest"
            ),
            external_evidence_digest=sha256_hex(raw),
            evidence_ref=str(self.path.resolve()),
            available=True,
        )
        observation.validate()
        return observation
