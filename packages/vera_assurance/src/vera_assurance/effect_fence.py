from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex


class EffectFenceError(ValueError):
    pass


class EffectState(StrEnum):
    RESERVED = "RESERVED"
    EXECUTING = "EXECUTING"
    COMMITTED = "COMMITTED"
    ATTEMPTED_UNKNOWN = "ATTEMPTED_UNKNOWN"
    RECONCILED_COMMITTED = "RECONCILED_COMMITTED"
    RECONCILED_NO_EFFECT = "RECONCILED_NO_EFFECT"
    CANCELLED_PRE_DISPATCH = "CANCELLED_PRE_DISPATCH"


@dataclass(frozen=True, slots=True)
class EffectReceipt:
    effect_id: str
    request_digest: str
    state: EffectState
    mechanical_permit_digest: str
    authority_evidence_digest: str
    currentness_evidence_digest: str
    result_digest: str | None = None
    reconciliation_evidence_digest: str | None = None


class EffectFence:
    """Durable single-use effect fence.

    This supplies mechanical single-use/CAS protection only. Authority and
    currentness evidence are independent inputs and are never minted by this
    class. Once dispatch is claimed, an ambiguous outcome cannot be converted
    into retry authority by an operator reset.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS effects (
                    effect_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    mechanical_permit_digest TEXT NOT NULL,
                    authority_evidence_digest TEXT NOT NULL,
                    currentness_evidence_digest TEXT NOT NULL,
                    result_digest TEXT,
                    reconciliation_evidence_digest TEXT
                )
                """
            )
            columns = {
                str(row[1])
                for row in db.execute("PRAGMA table_info(effects)").fetchall()
            }
            if "reconciliation_evidence_digest" not in columns:
                db.execute(
                    "ALTER TABLE effects ADD COLUMN reconciliation_evidence_digest TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _require_digest(value: str, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise EffectFenceError(f"{label} must be an exact SHA-256 hex digest")
        try:
            int(value, 16)
        except ValueError as exc:
            raise EffectFenceError(f"{label} must be hexadecimal") from exc
        return value.lower()

    @staticmethod
    def _require_id(value: str, label: str) -> str:
        if type(value) is not str or not value:
            raise EffectFenceError(f"{label} must be a non-empty exact string")
        return value

    def reserve(
        self,
        *,
        effect_id: str,
        request_digest: str,
        mechanical_permit_digest: str,
        authority_evidence_digest: str,
        currentness_evidence_digest: str,
    ) -> EffectReceipt:
        effect_id = self._require_id(effect_id, "effect_id")
        request_digest = self._require_digest(request_digest, "request_digest")
        permit = self._require_digest(mechanical_permit_digest, "mechanical_permit_digest")
        authority = self._require_digest(authority_evidence_digest, "authority_evidence_digest")
        currentness = self._require_digest(currentness_evidence_digest, "currentness_evidence_digest")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
            if row is not None:
                receipt = self._row(row)
                if (
                    receipt.request_digest == request_digest
                    and receipt.mechanical_permit_digest == permit
                    and receipt.authority_evidence_digest == authority
                    and receipt.currentness_evidence_digest == currentness
                ):
                    return receipt
                raise EffectFenceError("effect_id already binds a different request or evidence cut")
            db.execute(
                """
                INSERT INTO effects(
                    effect_id,request_digest,state,mechanical_permit_digest,
                    authority_evidence_digest,currentness_evidence_digest,result_digest
                ) VALUES(?,?,?,?,?,?,NULL)
                """,
                (effect_id, request_digest, EffectState.RESERVED.value, permit, authority, currentness),
            )
            db.commit()
            return EffectReceipt(
                effect_id, request_digest, EffectState.RESERVED, permit, authority, currentness
            )

    def claim_dispatch(
        self,
        *,
        effect_id: str,
        request_digest: str,
        mechanical_permit_digest: str,
        authority_evidence_digest: str,
        currentness_evidence_digest: str,
    ) -> EffectReceipt:
        requested = self.reserve(
            effect_id=effect_id,
            request_digest=request_digest,
            mechanical_permit_digest=mechanical_permit_digest,
            authority_evidence_digest=authority_evidence_digest,
            currentness_evidence_digest=currentness_evidence_digest,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
            receipt = self._row(row)
            if receipt.state is not EffectState.RESERVED:
                raise EffectFenceError(
                    f"effect is single-use and cannot be dispatched from {receipt.state.value}"
                )
            db.execute(
                "UPDATE effects SET state=? WHERE effect_id=? AND state=?",
                (EffectState.EXECUTING.value, effect_id, EffectState.RESERVED.value),
            )
            if db.total_changes != 1:
                raise EffectFenceError("effect dispatch claim lost atomic race")
            db.commit()
            return EffectReceipt(
                requested.effect_id,
                requested.request_digest,
                EffectState.EXECUTING,
                requested.mechanical_permit_digest,
                requested.authority_evidence_digest,
                requested.currentness_evidence_digest,
            )

    def settle(
        self,
        effect_id: str,
        *,
        result_digest: str | None,
        completion_known: bool,
    ) -> EffectReceipt:
        self._require_id(effect_id, "effect_id")
        if result_digest is not None:
            result_digest = self._require_digest(result_digest, "result_digest")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
            if row is None:
                raise KeyError(effect_id)
            receipt = self._row(row)
            if receipt.state is not EffectState.EXECUTING:
                raise EffectFenceError("only EXECUTING effects may settle")
            if completion_known and result_digest is None:
                raise EffectFenceError("known completion requires result_digest")
            state = EffectState.COMMITTED if completion_known else EffectState.ATTEMPTED_UNKNOWN
            db.execute(
                "UPDATE effects SET state=?, result_digest=? WHERE effect_id=? AND state=?",
                (state.value, result_digest, effect_id, EffectState.EXECUTING.value),
            )
            if db.total_changes != 1:
                raise EffectFenceError("effect settlement lost atomic race")
            db.commit()
            return EffectReceipt(
                receipt.effect_id,
                receipt.request_digest,
                state,
                receipt.mechanical_permit_digest,
                receipt.authority_evidence_digest,
                receipt.currentness_evidence_digest,
                result_digest,
            )

    def cancel_before_dispatch(self, effect_id: str) -> EffectReceipt:
        self._require_id(effect_id, "effect_id")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
            if row is None:
                raise KeyError(effect_id)
            receipt = self._row(row)
            if receipt.state is not EffectState.RESERVED:
                raise EffectFenceError("operator cancellation is forbidden after dispatch claim")
            db.execute(
                "UPDATE effects SET state=? WHERE effect_id=? AND state=?",
                (EffectState.CANCELLED_PRE_DISPATCH.value, effect_id, EffectState.RESERVED.value),
            )
            db.commit()
            return EffectReceipt(
                receipt.effect_id,
                receipt.request_digest,
                EffectState.CANCELLED_PRE_DISPATCH,
                receipt.mechanical_permit_digest,
                receipt.authority_evidence_digest,
                receipt.currentness_evidence_digest,
            )

    def unresolved(self) -> tuple[EffectReceipt, ...]:
        states = (
            EffectState.RESERVED.value,
            EffectState.EXECUTING.value,
            EffectState.ATTEMPTED_UNKNOWN.value,
        )
        placeholders = ",".join("?" for _ in states)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT * FROM effects WHERE state IN ({placeholders}) ORDER BY effect_id",
                states,
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def assert_clear(self) -> None:
        unresolved = self.unresolved()
        if unresolved:
            summary = ", ".join(
                f"{receipt.effect_id}:{receipt.state.value}"
                for receipt in unresolved
            )
            raise EffectFenceError(
                "unresolved external effect barrier is active: " + summary
            )

    def reconcile_unknown(
        self,
        effect_id: str,
        *,
        effect_occurred: bool,
        result_digest: str | None,
        reconciliation_evidence_digest: str,
    ) -> EffectReceipt:
        self._require_id(effect_id, "effect_id")
        evidence = self._require_digest(
            reconciliation_evidence_digest,
            "reconciliation_evidence_digest",
        )
        if effect_occurred:
            if result_digest is None:
                raise EffectFenceError(
                    "known occurred effect requires result_digest"
                )
            result_digest = self._require_digest(
                result_digest,
                "result_digest",
            )
            target = EffectState.RECONCILED_COMMITTED
        else:
            if result_digest is not None:
                raise EffectFenceError(
                    "known no-effect reconciliation must not carry result_digest"
                )
            target = EffectState.RECONCILED_NO_EFFECT

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM effects WHERE effect_id=?",
                (effect_id,),
            ).fetchone()
            if row is None:
                raise KeyError(effect_id)
            receipt = self._row(row)
            if receipt.state not in {
                EffectState.EXECUTING,
                EffectState.ATTEMPTED_UNKNOWN,
            }:
                raise EffectFenceError(
                    "only ambiguous dispatched effects may be reconciled"
                )
            db.execute(
                """
                UPDATE effects
                SET state=?, result_digest=?, reconciliation_evidence_digest=?
                WHERE effect_id=? AND state IN (?,?)
                """,
                (
                    target.value,
                    result_digest,
                    evidence,
                    effect_id,
                    EffectState.EXECUTING.value,
                    EffectState.ATTEMPTED_UNKNOWN.value,
                ),
            )
            if db.total_changes != 1:
                raise EffectFenceError("effect reconciliation lost atomic race")
            db.commit()
            return EffectReceipt(
                receipt.effect_id,
                receipt.request_digest,
                target,
                receipt.mechanical_permit_digest,
                receipt.authority_evidence_digest,
                receipt.currentness_evidence_digest,
                result_digest,
                evidence,
            )

    def read(self, effect_id: str) -> EffectReceipt:
        with self._connect() as db:
            row = db.execute("SELECT * FROM effects WHERE effect_id=?", (effect_id,)).fetchone()
        if row is None:
            raise KeyError(effect_id)
        return self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> EffectReceipt:
        return EffectReceipt(
            effect_id=row["effect_id"],
            request_digest=row["request_digest"],
            state=EffectState(row["state"]),
            mechanical_permit_digest=row["mechanical_permit_digest"],
            authority_evidence_digest=row["authority_evidence_digest"],
            currentness_evidence_digest=row["currentness_evidence_digest"],
            result_digest=row["result_digest"],
            reconciliation_evidence_digest=row["reconciliation_evidence_digest"],
        )


@dataclass(frozen=True, slots=True)
class CurrentnessSnapshot:
    subject_id: str
    generation: int
    snapshot_digest: str
    payload_digest: str


class AtomicCurrentnessStore:
    """Local atomic snapshot ledger; not a claim of global Vera currentness."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS currentness (
                    subject_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    snapshot_digest TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    payload_json TEXT
                )
                """
            )
            columns = {
                str(row[1])
                for row in db.execute("PRAGMA table_info(currentness)").fetchall()
            }
            if "payload_json" not in columns:
                db.execute("ALTER TABLE currentness ADD COLUMN payload_json TEXT")

    def publish(
        self,
        subject_id: str,
        payload: object,
        *,
        expected_generation: int | None,
    ) -> CurrentnessSnapshot:
        if type(subject_id) is not str or not subject_id:
            raise ValueError("subject_id must be a non-empty exact string")
        payload_json = canonical_json(payload)
        payload_digest = sha256_hex(payload_json.encode("utf-8"))
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT generation FROM currentness WHERE subject_id=?", (subject_id,)
            ).fetchone()
            current_generation = None if row is None else int(row["generation"])
            if current_generation != expected_generation:
                raise EffectFenceError("stale currentness generation")
            generation = 0 if current_generation is None else current_generation + 1
            snapshot_digest = sha256_hex(
                canonical_json_bytes(
                    {
                        "subject_id": subject_id,
                        "generation": generation,
                        "payload_digest": payload_digest,
                    }
                )
            )
            db.execute(
                """
                INSERT INTO currentness(
                    subject_id,generation,snapshot_digest,payload_digest,payload_json
                )
                VALUES(?,?,?,?,?)
                ON CONFLICT(subject_id) DO UPDATE SET
                    generation=excluded.generation,
                    snapshot_digest=excluded.snapshot_digest,
                    payload_digest=excluded.payload_digest,
                    payload_json=excluded.payload_json
                """,
                (
                    subject_id,
                    generation,
                    snapshot_digest,
                    payload_digest,
                    payload_json,
                ),
            )
            db.commit()
            return CurrentnessSnapshot(subject_id, generation, snapshot_digest, payload_digest)

    def read(self, subject_id: str) -> CurrentnessSnapshot:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM currentness WHERE subject_id=?", (subject_id,)).fetchone()
        if row is None:
            raise KeyError(subject_id)
        generation = int(row["generation"])
        payload_digest = str(row["payload_digest"])
        expected_snapshot = sha256_hex(
            canonical_json_bytes(
                {
                    "subject_id": str(row["subject_id"]),
                    "generation": generation,
                    "payload_digest": payload_digest,
                }
            )
        )
        if expected_snapshot != row["snapshot_digest"]:
            raise EffectFenceError("currentness snapshot digest mismatch")
        return CurrentnessSnapshot(
            row["subject_id"],
            generation,
            row["snapshot_digest"],
            payload_digest,
        )

    def read_payload(self, subject_id: str) -> object:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT payload_json,payload_digest FROM currentness WHERE subject_id=?",
                (subject_id,),
            ).fetchone()
        if row is None:
            raise KeyError(subject_id)
        payload_json = row["payload_json"]
        if payload_json is None:
            raise EffectFenceError(
                "currentness payload predates restart-reconstruction support"
            )
        if sha256_hex(payload_json.encode("utf-8")) != row["payload_digest"]:
            raise EffectFenceError("currentness payload digest mismatch")
        import json

        return json.loads(payload_json)
