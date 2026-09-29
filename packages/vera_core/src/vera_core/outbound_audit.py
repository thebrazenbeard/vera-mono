from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any, Mapping

from vera_assurance import EffectFence, EffectReceipt, EffectState

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)


class OutboundAuditError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OutboundAuditConsistency:
    audit_head_digest: str
    fence_effect_count: int
    audited_effect_count: int
    authority_only_effect_ids: tuple[str, ...]
    repaired_effect_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutboundAuditEvent:
    sequence: int
    effect_id: str
    effect_kind: str
    event_type: str
    predecessor_digest: str
    event_digest: str
    payload: Mapping[str, Any]


class OutboundExecutionAudit:
    """Append-only explanation ledger for qualified outbound effects.

    This ledger is evidence, not authority and not the mechanical effect fence.
    It records the exact lifecycle/request/authority cut consumed at dispatch so
    later trust rotation does not erase the explanation of an earlier effect.
    """

    GENESIS_HEAD = sha256_hex(b"vera-mono-outbound-execution-audit-genesis-v1")
    EVENT_TYPES = frozenset(
        {
            "AUTHORITY_VERIFIED",
            "RESERVED",
            "EXECUTING",
            "COMMITTED",
            "ATTEMPTED_UNKNOWN",
            "CANCELLED_PRE_DISPATCH",
            "RECONCILED_COMMITTED",
            "RECONCILED_NO_EFFECT",
        }
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
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY,
                    effect_id TEXT NOT NULL,
                    effect_kind TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    predecessor_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    UNIQUE(effect_id,event_type)
                );
                """
            )
            if db.execute("SELECT 1 FROM meta WHERE key='sequence'").fetchone() is None:
                db.execute("INSERT INTO meta(key,value) VALUES('sequence','0')")
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('head',?)",
                    (self.GENESIS_HEAD,),
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        if type(value) is not str or not value:
            raise OutboundAuditError(f"{label} must be a non-empty exact string")
        return value

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, str]:
        sequence = int(
            db.execute("SELECT value FROM meta WHERE key='sequence'").fetchone()[0]
        )
        head = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
        return sequence, head

    @property
    def head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    @property
    def sequence(self) -> int:
        with self._connect() as db:
            return self._meta(db)[0]

    def append(
        self,
        *,
        effect_id: str,
        effect_kind: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> OutboundAuditEvent:
        effect_id = self._require_text(effect_id, "effect_id")
        effect_kind = self._require_text(effect_kind, "effect_kind")
        if event_type not in self.EVENT_TYPES:
            raise OutboundAuditError(
                f"unsupported outbound audit event type: {event_type}"
            )
        if not isinstance(payload, Mapping):
            raise OutboundAuditError("outbound audit payload must be a mapping")
        normalized_payload = dict(payload)
        payload_json = canonical_json(normalized_payload)

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                """
                SELECT * FROM events
                WHERE effect_id=? AND event_type=?
                """,
                (effect_id, event_type),
            ).fetchone()
            if replay is not None:
                existing = self._row(replay)
                if canonical_json(dict(existing.payload)) != payload_json:
                    raise OutboundAuditError(
                        "outbound audit replay carries different payload"
                    )
                return existing

            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            body = {
                "schema": "VERA_MONO_OUTBOUND_EXECUTION_EVENT_V1",
                "sequence": next_sequence,
                "effect_id": effect_id,
                "effect_kind": effect_kind,
                "event_type": event_type,
                "predecessor_digest": predecessor,
                "payload": normalized_payload,
            }
            digest = sha256_hex(canonical_json_bytes(body))
            db.execute(
                """
                INSERT INTO events(
                    sequence,effect_id,effect_kind,event_type,
                    predecessor_digest,event_digest,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    effect_id,
                    effect_kind,
                    event_type,
                    predecessor,
                    digest,
                    payload_json,
                ),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='sequence'",
                (str(next_sequence),),
            )
            db.execute("UPDATE meta SET value=? WHERE key='head'", (digest,))
            db.commit()
            return OutboundAuditEvent(
                sequence=next_sequence,
                effect_id=effect_id,
                effect_kind=effect_kind,
                event_type=event_type,
                predecessor_digest=predecessor,
                event_digest=digest,
                payload=normalized_payload,
            )

    def events(
        self,
        effect_id: str | None = None,
    ) -> tuple[OutboundAuditEvent, ...]:
        with self._connect() as db:
            if effect_id is None:
                rows = db.execute(
                    "SELECT * FROM events ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM events
                    WHERE effect_id=?
                    ORDER BY sequence
                    """,
                    (effect_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def latest(self, effect_id: str) -> OutboundAuditEvent | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM events
                WHERE effect_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (effect_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _receipt_payload(
        receipt: EffectReceipt,
        event_type: str,
        *,
        restart_reconstructed: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_digest": receipt.request_digest,
            "mechanical_permit_digest": receipt.mechanical_permit_digest,
            "authority_evidence_digest": receipt.authority_evidence_digest,
            "currentness_evidence_digest": receipt.currentness_evidence_digest,
        }
        if event_type in {
            "COMMITTED",
            "RECONCILED_COMMITTED",
            "RECONCILED_NO_EFFECT",
        }:
            payload["result_digest"] = receipt.result_digest
        if event_type in {
            "RECONCILED_COMMITTED",
            "RECONCILED_NO_EFFECT",
        }:
            payload["reconciliation_evidence_digest"] = (
                receipt.reconciliation_evidence_digest
            )
        if restart_reconstructed:
            payload["restart_reconstructed_from_effect_fence"] = True
        return payload

    @staticmethod
    def _target_event_type(state: EffectState) -> str:
        return state.value

    def _append_missing_mechanical_stages(
        self,
        receipt: EffectReceipt,
    ) -> bool:
        current = self.latest(receipt.effect_id)
        if current is None:
            raise OutboundAuditError(
                "effect fence contains effect with no qualified outbound audit evidence"
            )
        repaired = False
        target = self._target_event_type(receipt.state)
        while current.event_type != target:
            if current.event_type == "AUTHORITY_VERIFIED":
                next_type = "RESERVED"
            elif current.event_type == "RESERVED":
                next_type = (
                    "CANCELLED_PRE_DISPATCH"
                    if target == "CANCELLED_PRE_DISPATCH"
                    else "EXECUTING"
                )
            elif current.event_type == "EXECUTING":
                if target not in {
                    "COMMITTED",
                    "ATTEMPTED_UNKNOWN",
                    "RECONCILED_COMMITTED",
                    "RECONCILED_NO_EFFECT",
                }:
                    raise OutboundAuditError(
                        "outbound audit is ahead of or incompatible with effect fence"
                    )
                next_type = target
            elif current.event_type == "ATTEMPTED_UNKNOWN":
                if target not in {
                    "RECONCILED_COMMITTED",
                    "RECONCILED_NO_EFFECT",
                }:
                    raise OutboundAuditError(
                        "outbound audit ambiguity state conflicts with effect fence"
                    )
                next_type = target
            else:
                raise OutboundAuditError(
                    "terminal outbound audit state conflicts with effect fence"
                )

            self.append(
                effect_id=receipt.effect_id,
                effect_kind=current.effect_kind,
                event_type=next_type,
                payload=self._receipt_payload(
                    receipt,
                    next_type,
                    restart_reconstructed=True,
                ),
            )
            repaired = True
            current = self.latest(receipt.effect_id)
            assert current is not None
        return repaired

    def verify_fence_consistency(
        self,
        fence: EffectFence,
        *,
        repaired_effect_ids: tuple[str, ...] = (),
    ) -> OutboundAuditConsistency:
        if type(fence) is not EffectFence:
            raise TypeError("fence must be exact EffectFence")
        audit_head = self.verify_chain()
        receipts = {receipt.effect_id: receipt for receipt in fence.all()}
        audit_effect_ids = {
            event.effect_id for event in self.events()
        }
        authority_only: list[str] = []

        for effect_id in sorted(audit_effect_ids):
            events = self.events(effect_id)
            first = events[0]
            if first.event_type != "AUTHORITY_VERIFIED":
                raise OutboundAuditError(
                    "qualified outbound audit does not begin with authority verification"
                )
            receipt = receipts.get(effect_id)
            if receipt is None:
                if len(events) == 1:
                    authority_only.append(effect_id)
                    continue
                raise OutboundAuditError(
                    "outbound audit records mechanical progress absent from effect fence"
                )

            latest = events[-1]
            if latest.event_type != self._target_event_type(receipt.state):
                raise OutboundAuditError(
                    "outbound audit latest state does not match effect fence state"
                )
            authority_payload = first.payload
            expected_authority = {
                "request_digest": receipt.request_digest,
                "mechanical_permit_digest": receipt.mechanical_permit_digest,
                "authority_evidence_digest": receipt.authority_evidence_digest,
            }
            for key, expected in expected_authority.items():
                if authority_payload.get(key) != expected:
                    raise OutboundAuditError(
                        f"outbound audit {key} does not match effect fence"
                    )
            lifecycle_permit = authority_payload.get("lifecycle_permit")
            if (
                not isinstance(lifecycle_permit, Mapping)
                or lifecycle_permit.get("permit_digest")
                != receipt.currentness_evidence_digest
            ):
                raise OutboundAuditError(
                    "outbound audit lifecycle permit does not match effect fence"
                )

            latest_payload = latest.payload
            checks = {
                "request_digest": receipt.request_digest,
                "authority_evidence_digest": receipt.authority_evidence_digest,
                "currentness_evidence_digest": receipt.currentness_evidence_digest,
            }
            if "mechanical_permit_digest" in latest_payload:
                checks["mechanical_permit_digest"] = (
                    receipt.mechanical_permit_digest
                )
            for key, expected in checks.items():
                if latest_payload.get(key) != expected:
                    raise OutboundAuditError(
                        f"outbound audit final {key} does not match effect fence"
                    )
            if receipt.state in {
                EffectState.COMMITTED,
                EffectState.RECONCILED_COMMITTED,
                EffectState.RECONCILED_NO_EFFECT,
            } and latest_payload.get("result_digest") != receipt.result_digest:
                raise OutboundAuditError(
                    "outbound audit result digest does not match effect fence"
                )
            if receipt.state in {
                EffectState.RECONCILED_COMMITTED,
                EffectState.RECONCILED_NO_EFFECT,
            } and latest_payload.get(
                "reconciliation_evidence_digest"
            ) != receipt.reconciliation_evidence_digest:
                raise OutboundAuditError(
                    "outbound audit reconciliation evidence does not match effect fence"
                )

        missing_audit = sorted(set(receipts) - audit_effect_ids)
        if missing_audit:
            raise OutboundAuditError(
                "effect fence contains unaudited effects: " + ", ".join(missing_audit)
            )
        return OutboundAuditConsistency(
            audit_head_digest=audit_head,
            fence_effect_count=len(receipts),
            audited_effect_count=len(audit_effect_ids),
            authority_only_effect_ids=tuple(authority_only),
            repaired_effect_ids=tuple(sorted(set(repaired_effect_ids))),
        )

    def repair_from_fence(
        self,
        fence: EffectFence,
    ) -> OutboundAuditConsistency:
        if type(fence) is not EffectFence:
            raise TypeError("fence must be exact EffectFence")
        self.verify_chain()
        repaired: list[str] = []
        for receipt in fence.all():
            if self._append_missing_mechanical_stages(receipt):
                repaired.append(receipt.effect_id)
        return self.verify_fence_consistency(
            fence,
            repaired_effect_ids=tuple(repaired),
        )

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM events ORDER BY sequence"
            ).fetchall()
            sequence, head = self._meta(db)

        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        terminal_types = {
            "COMMITTED",
            "CANCELLED_PRE_DISPATCH",
            "RECONCILED_COMMITTED",
            "RECONCILED_NO_EFFECT",
        }
        allowed_next = {
            None: {"AUTHORITY_VERIFIED"},
            "AUTHORITY_VERIFIED": {"RESERVED"},
            "RESERVED": {"EXECUTING", "CANCELLED_PRE_DISPATCH"},
            "EXECUTING": {
                "COMMITTED",
                "ATTEMPTED_UNKNOWN",
                "RECONCILED_COMMITTED",
                "RECONCILED_NO_EFFECT",
            },
            "ATTEMPTED_UNKNOWN": {
                "RECONCILED_COMMITTED",
                "RECONCILED_NO_EFFECT",
            },
        }
        last_type: dict[str, str] = {}
        effect_kinds: dict[str, str] = {}
        for row in rows:
            event = self._row(row)
            if event.sequence != expected_sequence:
                raise OutboundAuditError("outbound audit sequence gap")
            if event.predecessor_digest != predecessor:
                raise OutboundAuditError(
                    "outbound audit predecessor digest mismatch"
                )
            if event.event_type not in self.EVENT_TYPES:
                raise OutboundAuditError(
                    "outbound audit contains unsupported event type"
                )
            prior_type = last_type.get(event.effect_id)
            prior_kind = effect_kinds.get(event.effect_id)
            if prior_kind is not None and prior_kind != event.effect_kind:
                raise OutboundAuditError(
                    "outbound audit effect kind changed within one effect identity"
                )
            if prior_type in terminal_types:
                raise OutboundAuditError(
                    "outbound audit terminal effect has later events"
                )
            expected = allowed_next.get(prior_type, set())
            if event.event_type not in expected:
                raise OutboundAuditError(
                    "outbound audit effect stage ordering is invalid"
                )

            body = {
                "schema": "VERA_MONO_OUTBOUND_EXECUTION_EVENT_V1",
                "sequence": event.sequence,
                "effect_id": event.effect_id,
                "effect_kind": event.effect_kind,
                "event_type": event.event_type,
                "predecessor_digest": event.predecessor_digest,
                "payload": dict(event.payload),
            }
            observed = sha256_hex(canonical_json_bytes(body))
            if observed != event.event_digest:
                raise OutboundAuditError(
                    "outbound audit event digest mismatch"
                )
            predecessor = observed
            last_type[event.effect_id] = event.event_type
            effect_kinds[event.effect_id] = event.effect_kind
            expected_sequence += 1

        if sequence != expected_sequence - 1:
            raise OutboundAuditError("outbound audit meta sequence mismatch")
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise OutboundAuditError("outbound audit meta head mismatch")
        return head

    def context(self) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_OUTBOUND_EXECUTION_AUDIT_CONTEXT_V1",
            "sequence": self.sequence,
            "head_digest": self.verify_chain(),
            "effect_count": len(
                {event.effect_id for event in self.events()}
            ),
        }

    @staticmethod
    def _row(row: sqlite3.Row) -> OutboundAuditEvent:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise OutboundAuditError(
                "outbound audit payload is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise OutboundAuditError(
                "outbound audit payload must be an object"
            )
        return OutboundAuditEvent(
            sequence=int(row["sequence"]),
            effect_id=str(row["effect_id"]),
            effect_kind=str(row["effect_kind"]),
            event_type=str(row["event_type"]),
            predecessor_digest=str(row["predecessor_digest"]),
            event_digest=str(row["event_digest"]),
            payload=payload,
        )
