"""Research-only persistent linkage of actual local Rezon method/consumer calls.

No trusted clock, authenticated evaluator, host-selected route, closed code
dependencies, QVR consumption, learning effect, or external effect authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from .method_observation import MethodInvocationObservation, _hash
from .method_evaluation_join import (
    MethodSelectionCommitment, DeclaredEvaluatorOutcome, join_method_evaluation,
)
from .method_consumer_observation import LocalConsumerObservation


class MethodUseHold(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalMethodUseReceipt:
    event_id: str
    selected_source_head: str
    method_id: str
    revision_id: str
    task_id: str
    execution_cut_id: str
    selection_sha256: str
    request_sha256: str
    method_code_sha256: str
    method_result_sha256: str
    invocation_number: int
    declared_evaluator_id: str
    declared_verdict: str
    consumer_id: str
    consumer_execution_id: str
    consumer_code_sha256: str
    consumer_result_sha256: str
    method_host_pid: int
    consumer_host_pid: int
    status: str = "LOCAL_RESTART_READBACK_ONLY"
    evaluator_independence_verified: bool = False
    precommit_timing_verified: bool = False
    callable_dependency_closure_verified: bool = False
    mutable_state_verified: bool = False
    qualified_runtime_consumption_verified: bool = False
    causal_learning_verified: bool = False
    external_effect_authority: bool = False


def join_local_use(
    event_id: str,
    selection: MethodSelectionCommitment,
    invocation: MethodInvocationObservation,
    evaluation: DeclaredEvaluatorOutcome,
    consumer: LocalConsumerObservation,
) -> LocalMethodUseReceipt:
    """No caller may supply a receipt directly in place of these typed records."""
    if type(event_id) is not str or not event_id:
        raise MethodUseHold("exact event ID required")
    if type(consumer) is not LocalConsumerObservation:
        raise MethodUseHold("exact local consumer observation required")
    link = join_method_evaluation(selection, invocation, evaluation)
    if (consumer.outcome != "RETURNED" or consumer.consumer_result_sha256 is None
            or consumer.status != "LOCAL_CONSUMER_CALL_ONLY"
            or not consumer.local_consumer_call_observed):
        raise MethodUseHold("no actual returned local consumer call")
    if any((
        consumer.consumer_route_independently_verified,
        consumer.consumer_semantic_use_verified,
        consumer.transitive_dependency_closure_measured,
        consumer.mutable_closure_state_measured,
        consumer.evaluator_custody_verified,
        consumer.precommit_timing_verified,
        consumer.qualified_runtime_consumption_verified,
        consumer.cold_restart_reuse_verified,
    )):
        raise MethodUseHold("local consumer record advertises unqualified proof")
    if (
        consumer.method_id, consumer.revision_id, consumer.task_id,
        consumer.execution_cut_id, consumer.invocation_number,
        consumer.selection_sha256, consumer.method_result_sha256,
    ) != (
        link.method_id, link.revision_id, link.task_id,
        link.execution_cut_id, link.invocation_number,
        link.selection_sha256, link.result_sha256,
    ):
        raise MethodUseHold("consumer not bound to evaluated selected method")
    if consumer.consumer_code_before_sha256 != consumer.consumer_code_after_sha256:
        raise MethodUseHold("consumer code changed during local call")
    if (consumer.host_pid <= 0 or invocation.host_pid <= 0
            or selection.envelope.expected_bytecode_sha256 != invocation.code_after_sha256):
        raise MethodUseHold("invalid local method/consumer measurement")
    return LocalMethodUseReceipt(
        event_id=event_id, selected_source_head=selection.envelope.selected_source_head,
        method_id=link.method_id, revision_id=link.revision_id, task_id=link.task_id,
        execution_cut_id=link.execution_cut_id,
        selection_sha256=link.selection_sha256, request_sha256=link.request_sha256,
        method_code_sha256=invocation.code_after_sha256,
        method_result_sha256=link.result_sha256,
        invocation_number=link.invocation_number,
        declared_evaluator_id=link.declared_evaluator_id,
        declared_verdict=link.declared_verdict,
        consumer_id=consumer.consumer_id,
        consumer_execution_id=consumer.consumer_execution_id,
        consumer_code_sha256=consumer.consumer_code_after_sha256,
        consumer_result_sha256=consumer.consumer_result_sha256,
        method_host_pid=invocation.host_pid, consumer_host_pid=consumer.host_pid,
    )


def _bytes(record: LocalMethodUseReceipt) -> bytes:
    return json.dumps(asdict(record), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


class LocalMethodUseLedger:
    """Disposable research SQLite with strict append, re-open and chain verification.

    Same-user writers can rewrite the entire DB/chain. Verification is
    INTERNAL LOCAL consistency, not external notarization or producer proof.
    """
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS method_uses (
                sequence INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                body_json TEXT NOT NULL,
                body_sha256 TEXT NOT NULL,
                previous_sha256 TEXT,
                chain_sha256 TEXT NOT NULL
            )""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def append(self, receipt: LocalMethodUseReceipt) -> str:
        if type(receipt) is not LocalMethodUseReceipt:
            raise TypeError("exact LocalMethodUseReceipt required")
        if receipt != LocalMethodUseReceipt(**asdict(receipt)):
            raise MethodUseHold("invalid receipt serialization")
        if any((
            receipt.evaluator_independence_verified, receipt.precommit_timing_verified,
            receipt.callable_dependency_closure_verified, receipt.mutable_state_verified,
            receipt.qualified_runtime_consumption_verified, receipt.causal_learning_verified,
            receipt.external_effect_authority,
        )) or receipt.status != "LOCAL_RESTART_READBACK_ONLY":
            raise MethodUseHold("cannot promote evidence or authority through local ledger")
        body = _bytes(receipt)
        digest = hashlib.sha256(body).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT sequence,body_json,body_sha256,previous_sha256,chain_sha256 FROM method_uses ORDER BY sequence").fetchall()
            _verify_rows(rows)
            prev = rows[-1][4] if rows else None
            seq = len(rows) + 1
            chain = _hash({"seq": seq, "previous": prev, "digest": digest})
            db.execute("INSERT INTO method_uses VALUES (?,?,?,?,?,?)",
                       (seq, receipt.event_id, body.decode("utf-8"), digest, prev, chain))
        return chain

    def all(self) -> tuple[LocalMethodUseReceipt, ...]:
        with self._connect() as db:
            rows = db.execute("SELECT sequence,body_json,body_sha256,previous_sha256,chain_sha256 FROM method_uses ORDER BY sequence").fetchall()
        _verify_rows(rows)
        records = tuple(LocalMethodUseReceipt(**json.loads(row[1])) for row in rows)
        if any(record.status != "LOCAL_RESTART_READBACK_ONLY"
               or record.evaluator_independence_verified
               or record.qualified_runtime_consumption_verified
               or record.external_effect_authority for record in records):
            raise MethodUseHold("stored receipt claims elevated evidence")
        return records

    def later_use(self, first_event_id: str, later_event_id: str) -> "LocalLaterUseLink":
        # Only compare records that were independently read back from THIS
        # research ledger. This is not external producer authentication.
        records = {record.event_id: record for record in self.all()}
        if first_event_id not in records or later_event_id not in records:
            raise MethodUseHold("later use event not present in local ledger")
        return link_local_later_use(records[first_event_id], records[later_event_id])


def _verify_rows(rows: list[tuple]) -> None:
    previous = None
    for position, (seq, body, digest, parent, chain) in enumerate(rows, 1):
        if seq != position or parent != previous:
            raise MethodUseHold("local ledger order/parent changed")
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != digest or chain != _hash({"seq": seq, "previous": parent, "digest": digest}):
            raise MethodUseHold("local ledger digest changed")
        previous = chain


@dataclass(frozen=True, slots=True)
class LocalLaterUseLink:
    first_event_id: str
    later_event_id: str
    method_id: str
    revision_id: str
    status: str = "LOCAL_CROSS_TASK_REUSE_ONLY"
    later_runtime_consumption_verified: bool = False
    causal_improvement_verified: bool = False


def link_local_later_use(
    first: LocalMethodUseReceipt,
    later: LocalMethodUseReceipt,
) -> LocalLaterUseLink:
    if type(first) is not LocalMethodUseReceipt or type(later) is not LocalMethodUseReceipt:
        raise TypeError("two exact local use receipts required")
    if first.event_id == later.event_id or first.task_id == later.task_id:
        raise MethodUseHold("later use must be a distinct task/event")
    if (
        first.method_id, first.revision_id, first.selected_source_head,
        first.method_code_sha256, first.consumer_id, first.consumer_code_sha256,
    ) != (
        later.method_id, later.revision_id, later.selected_source_head,
        later.method_code_sha256, later.consumer_id, later.consumer_code_sha256,
    ):
        raise MethodUseHold("different selected method/consumer revision")
    if first.consumer_execution_id == later.consumer_execution_id:
        raise MethodUseHold("later use needs a separately named consumer execution")
    return LocalLaterUseLink(first.event_id, later.event_id, first.method_id, first.revision_id)
