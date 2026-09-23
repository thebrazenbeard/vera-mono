from __future__ import annotations

from hashlib import sha256
import json

from .provenance import canonical_producer_execution_id
from .receipts import EffectState, FailureState, ResultReceipt
from .runner import RunOutcome
from .trace import ExecutionTrace, TraceRecord


RUN_EVIDENCE_SCHEMA = "rezon.run-evidence.v1"


class RunEvidenceError(ValueError):
    pass


def _require_exact_outcome(outcome: RunOutcome) -> tuple[ResultReceipt, tuple[TraceRecord, ...]]:
    if type(outcome) is not RunOutcome:
        raise RunEvidenceError("run evidence requires exact RunOutcome")
    if type(outcome.receipt) is not ResultReceipt:
        raise RunEvidenceError("run evidence requires exact ResultReceipt")
    if type(outcome.trace) is not ExecutionTrace:
        raise RunEvidenceError("run evidence requires exact ExecutionTrace")
    if type(outcome.trace.records) is not tuple or any(
        type(record) is not TraceRecord for record in outcome.trace.records
    ):
        raise RunEvidenceError("run evidence requires exact TraceRecord values")
    return outcome.receipt, outcome.trace.records


def _validate_receipt_trace_binding(
    receipt: ResultReceipt,
    records: tuple[TraceRecord, ...],
) -> None:
    if receipt.effect_state is not EffectState.PLAN:
        raise RunEvidenceError("run evidence may export PLAN receipts only")

    expected_execution_ids = tuple(record.execution_id for record in records)
    if receipt.execution_ids != expected_execution_ids:
        raise RunEvidenceError("receipt execution ids do not match trace")

    expected_source_versions: list[str] = []
    for record in records:
        for source_version in record.source_versions:
            if source_version not in expected_source_versions:
                expected_source_versions.append(source_version)
    if receipt.source_versions != tuple(expected_source_versions):
        raise RunEvidenceError("receipt source versions do not match trace")

    trace_failures: list[FailureState] = []
    for record in records:
        for failure in record.failures:
            if failure not in trace_failures:
                trace_failures.append(failure)
    missing_trace_failures = [
        failure for failure in trace_failures if failure not in receipt.failures
    ]
    if missing_trace_failures:
        raise RunEvidenceError("receipt failure summary does not cover trace failures")

    expected_output_bindings = tuple(
        (record.execution_id, record.canonical_output_digest)
        for record in records
        if record.canonical_output_digest is not None
    )
    if receipt.execution_output_digests != expected_output_bindings:
        raise RunEvidenceError("receipt output bindings do not match trace")

    expected_producer_bindings = tuple(
        (record.execution_id, record.canonical_producer_execution_id)
        for record in records
        if record.canonical_producer_execution_id is not None
    )
    if receipt.execution_producer_ids != expected_producer_bindings:
        raise RunEvidenceError("receipt producer bindings do not match trace")

    if any(
        record.task_envelope_digest != receipt.task_envelope_digest
        for record in records
    ):
        raise RunEvidenceError("receipt task envelope digest does not match trace")

    for record in records:
        producer_id = record.canonical_producer_execution_id
        if producer_id is None:
            continue
        if (
            record.canonical_episode_snapshot_digest is None
            or record.canonical_output_digest is None
        ):
            raise RunEvidenceError(
                "canonical producer binding requires snapshot and output digests"
            )
        expected_producer_id = canonical_producer_execution_id(
            record.node_id,
            record.canonical_episode_snapshot_digest,
            record.executor_task_specification_digest,
            record.canonical_output_digest,
        )
        if producer_id != expected_producer_id:
            raise RunEvidenceError(
                "trace canonical producer identity does not recompute"
            )


def _receipt_payload(receipt: ResultReceipt) -> dict[str, object]:
    return {
        "task_id": receipt.task_id,
        "episode_version": receipt.episode_version,
        "accepted_claim_ids": list(receipt.accepted_claim_ids),
        "rejected_claim_ids": list(receipt.rejected_claim_ids),
        "unresolved": list(receipt.unresolved),
        "failures": [failure.value for failure in receipt.failures],
        "effect_state": receipt.effect_state.value,
        "source_versions": list(receipt.source_versions),
        "execution_ids": list(receipt.execution_ids),
        "execution_output_digests": [
            list(binding) for binding in receipt.execution_output_digests
        ],
        "execution_producer_ids": [
            list(binding) for binding in receipt.execution_producer_ids
        ],
        "task_envelope_digest": receipt.task_envelope_digest,
        "claim_disposition_complete": receipt.claim_disposition_complete,
    }


def _record_payload(record: TraceRecord) -> dict[str, object]:
    return {
        "execution_id": record.execution_id,
        "node_id": record.node_id,
        "episode_version": record.episode_version,
        "visible_proposition_ids": list(record.visible_proposition_ids),
        "blinded_proposition_ids": list(record.blinded_proposition_ids),
        "visible_relation_ids": list(record.visible_relation_ids),
        "blinded_relation_ids": list(record.blinded_relation_ids),
        "emitted_proposition_ids": list(record.emitted_proposition_ids),
        "independence_demonstrated": record.independence_demonstrated,
        "task_envelope_digest": record.task_envelope_digest,
        "executor_task_specification_digest": (
            record.executor_task_specification_digest
        ),
        "executor_episode_version": record.executor_episode_version,
        "canonical_producer_execution_id": record.canonical_producer_execution_id,
        "canonical_episode_snapshot_digest": (
            record.canonical_episode_snapshot_digest
        ),
        "canonical_output_digest": record.canonical_output_digest,
        "source_refs": list(record.source_refs),
        "source_versions": list(record.source_versions),
        "reported_source_refs": list(record.reported_source_refs),
        "reported_source_versions": list(record.reported_source_versions),
        "failures": [failure.value for failure in record.failures],
    }


def export_run_evidence(outcome: RunOutcome) -> dict[str, object]:
    """Return deterministic, JSON-safe, non-promotional Rezon run evidence.

    The evidence intentionally omits runtime duration and performs no I/O,
    authority translation, lease handling, or effect promotion.
    """

    receipt, records = _require_exact_outcome(outcome)
    _validate_receipt_trace_binding(receipt, records)

    body: dict[str, object] = {
        "schema_version": RUN_EVIDENCE_SCHEMA,
        "receipt": _receipt_payload(receipt),
        "executions": [_record_payload(record) for record in records],
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        **body,
        "evidence_digest": sha256(encoded).hexdigest(),
    }
