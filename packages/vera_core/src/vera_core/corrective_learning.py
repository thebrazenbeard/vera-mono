from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3


class CorrectiveStage(StrEnum):
    FLAG = "FLAG"
    UNDERSTAND = "UNDERSTAND"
    CALIBRATE = "CALIBRATE"
    KNOW = "KNOW"
    UNLEARN = "UNLEARN"
    PREVENT = "PREVENT"


CORRECTIVE_STAGE_ORDER = (
    CorrectiveStage.FLAG,
    CorrectiveStage.UNDERSTAND,
    CorrectiveStage.CALIBRATE,
    CorrectiveStage.KNOW,
    CorrectiveStage.UNLEARN,
    CorrectiveStage.PREVENT,
)


def _refs(values: tuple[str, ...], *, field: str) -> tuple[str, ...]:
    if not values or any(type(value) is not str or not value for value in values):
        raise ValueError(f"{field} must contain non-empty exact strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field} must not contain duplicates")
    return values


def _digest(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CorrectionEvent:
    correction_id: str
    failure_signature_id: str
    sequence: int
    stage: CorrectiveStage
    summary: str
    evidence_refs: tuple[str, ...]
    guardrail_refs: tuple[str, ...]
    verification_refs: tuple[str, ...]
    previous_digest: str | None
    event_digest: str


@dataclass(frozen=True, slots=True)
class CorrectionState:
    correction_id: str
    failure_signature_id: str
    events: tuple[CorrectionEvent, ...]
    @property
    def current_stage(self) -> CorrectiveStage:
        return self.events[-1].stage

    @property
    def completed(self) -> bool:
        return self.current_stage is CorrectiveStage.PREVENT


class CorrectiveLearningLedger:
    """Append-only durable corrective-learning cycle.

    A cycle may not skip stages. PREVENT is terminal only when an explicit
    guardrail and an independent verification reference are both recorded.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS correction_events (
                    correction_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    failure_signature_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    guardrail_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    previous_digest TEXT,
                    event_digest TEXT NOT NULL,
                    PRIMARY KEY (correction_id, sequence),
                    UNIQUE (correction_id, stage)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def start(
        self,
        *,
        correction_id: str,
        failure_signature_id: str,
        summary: str,
        evidence_refs: tuple[str, ...],
    ) -> CorrectionEvent:
        if type(correction_id) is not str or not correction_id:
            raise ValueError("correction_id must be a non-empty exact string")
        if type(failure_signature_id) is not str or not failure_signature_id:
            raise ValueError("failure_signature_id must be a non-empty exact string")
        return self._append(
            correction_id=correction_id,
            failure_signature_id=failure_signature_id,
            stage=CorrectiveStage.FLAG,
            summary=summary,
            evidence_refs=evidence_refs,
            guardrail_refs=(),
            verification_refs=(),
            require_new=True,
        )

    def advance(
        self,
        correction_id: str,
        *,
        stage: CorrectiveStage,
        summary: str,
        evidence_refs: tuple[str, ...],
        guardrail_refs: tuple[str, ...] = (),
        verification_refs: tuple[str, ...] = (),
    ) -> CorrectionEvent:
        current = self.state(correction_id)
        expected_index = len(current.events)
        if expected_index >= len(CORRECTIVE_STAGE_ORDER):
            raise ValueError("corrective learning cycle is already complete")
        expected = CORRECTIVE_STAGE_ORDER[expected_index]
        if stage is not expected:
            raise ValueError(
                f"corrective stage must advance exactly to {expected.value}"
            )
        if stage is CorrectiveStage.PREVENT:
            _refs(guardrail_refs, field="guardrail_refs")
            _refs(verification_refs, field="verification_refs")
        elif guardrail_refs or verification_refs:
            raise ValueError(
                "guardrail_refs and verification_refs belong only to PREVENT"
            )
        return self._append(
            correction_id=correction_id,
            failure_signature_id=current.failure_signature_id,
            stage=stage,
            summary=summary,
            evidence_refs=evidence_refs,
            guardrail_refs=guardrail_refs,
            verification_refs=verification_refs,
            require_new=False,
        )

    def _append(
        self,
        *,
        correction_id: str,
        failure_signature_id: str,
        stage: CorrectiveStage,
        summary: str,
        evidence_refs: tuple[str, ...],
        guardrail_refs: tuple[str, ...],
        verification_refs: tuple[str, ...],
        require_new: bool,
    ) -> CorrectionEvent:
        if type(summary) is not str or not summary.strip():
            raise ValueError("summary must be non-empty")
        evidence_refs = _refs(evidence_refs, field="evidence_refs")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM correction_events WHERE correction_id=? "
                "ORDER BY sequence",
                (correction_id,),
            ).fetchall()
            if require_new and rows:
                raise ValueError("correction_id is already bound")
            if not require_new and not rows:
                raise KeyError(correction_id)
            if rows:
                existing = self._decode_rows(rows)
                if existing.failure_signature_id != failure_signature_id:
                    raise ValueError("correction_id cannot rebind failure signature")
                sequence = len(existing.events)
                previous_digest = existing.events[-1].event_digest
            else:
                sequence = 0
                previous_digest = None
            payload = {
                "correction_id": correction_id,
                "failure_signature_id": failure_signature_id,
                "sequence": sequence,
                "stage": stage.value,
                "summary": summary.strip(),
                "evidence_refs": list(evidence_refs),
                "guardrail_refs": list(guardrail_refs),
                "verification_refs": list(verification_refs),
                "previous_digest": previous_digest,
            }
            event_digest = _digest(payload)
            db.execute(
                "INSERT INTO correction_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    correction_id,
                    sequence,
                    failure_signature_id,
                    stage.value,
                    summary.strip(),
                    json.dumps(list(evidence_refs)),
                    json.dumps(list(guardrail_refs)),
                    json.dumps(list(verification_refs)),
                    previous_digest,
                    event_digest,
                ),
            )
            db.commit()
        return CorrectionEvent(
            correction_id=correction_id,
            failure_signature_id=failure_signature_id,
            sequence=sequence,
            stage=stage,
            summary=summary.strip(),
            evidence_refs=evidence_refs,
            guardrail_refs=guardrail_refs,
            verification_refs=verification_refs,
            previous_digest=previous_digest,
            event_digest=event_digest,
        )

    def state(self, correction_id: str) -> CorrectionState:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM correction_events WHERE correction_id=? "
                "ORDER BY sequence",
                (correction_id,),
            ).fetchall()
        if not rows:
            raise KeyError(correction_id)
        return self._decode_rows(rows)

    def _decode_rows(self, rows: list[sqlite3.Row]) -> CorrectionState:
        events: list[CorrectionEvent] = []
        failure_signature_id = str(rows[0]["failure_signature_id"])
        previous_digest: str | None = None
        for sequence, row in enumerate(rows):
            stage = CorrectiveStage(str(row["stage"]))
            if sequence >= len(CORRECTIVE_STAGE_ORDER):
                raise ValueError("correction ledger contains excess stages")
            if stage is not CORRECTIVE_STAGE_ORDER[sequence]:
                raise ValueError("correction ledger stage order is invalid")
            if str(row["failure_signature_id"]) != failure_signature_id:
                raise ValueError("correction ledger failure binding changed")
            evidence_refs = tuple(json.loads(str(row["evidence_json"])))
            guardrail_refs = tuple(json.loads(str(row["guardrail_json"])))
            verification_refs = tuple(json.loads(str(row["verification_json"])))
            payload = {
                "correction_id": str(row["correction_id"]),
                "failure_signature_id": failure_signature_id,
                "sequence": sequence,
                "stage": stage.value,
                "summary": str(row["summary"]),
                "evidence_refs": list(evidence_refs),
                "guardrail_refs": list(guardrail_refs),
                "verification_refs": list(verification_refs),
                "previous_digest": previous_digest,
            }
            observed = str(row["event_digest"])
            if row["sequence"] != sequence:
                raise ValueError("correction ledger sequence is invalid")
            if row["previous_digest"] != previous_digest:
                raise ValueError("correction ledger digest chain is invalid")
            if observed != _digest(payload):
                raise ValueError("correction ledger event digest is invalid")
            events.append(
                CorrectionEvent(
                    correction_id=str(row["correction_id"]),
                    failure_signature_id=failure_signature_id,
                    sequence=sequence,
                    stage=stage,
                    summary=str(row["summary"]),
                    evidence_refs=evidence_refs,
                    guardrail_refs=guardrail_refs,
                    verification_refs=verification_refs,
                    previous_digest=previous_digest,
                    event_digest=observed,
                )
            )
            previous_digest = observed
        return CorrectionState(
            correction_id=events[0].correction_id,
            failure_signature_id=failure_signature_id,
            events=tuple(events),
        )

    def context(self) -> dict[str, object]:
        with self._connect() as db:
            ids = [
                str(row[0])
                for row in db.execute(
                    "SELECT DISTINCT correction_id FROM correction_events "
                    "ORDER BY correction_id"
                ).fetchall()
            ]
        states = [self.state(correction_id) for correction_id in ids]
        return {
            "schema": "VERA_CORRECTIVE_LEARNING_CONTEXT_V1",
            "correction_count": len(states),
            "open_count": sum(not state.completed for state in states),
            "completed_count": sum(state.completed for state in states),
            "correction_ids": ids,
        }