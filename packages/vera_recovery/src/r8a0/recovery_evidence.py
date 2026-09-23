"""Signed checkpoint and lifecycle evidence persistence."""
from __future__ import annotations

import hashlib
from pathlib import Path
from .canonical import canonical_sha256, strict_loads
from typing import Any, Callable, Mapping

from .recovery_core import (
    MAX_CLOCK_SKEW, MAX_LIFECYCLE_AGE, CheckpointState, RecoveryError,
    _atomic, _signed, _utc_now, _verify, parse_time, verify_state_attestations,
)
def write_checkpoint(
    path: str | Path,
    state: CheckpointState,
    *,
    checkpoint_receipt_path: str | Path,
    state_attestations: Mapping[str, Mapping[str, Any]],
    trusted_state_keys: Mapping[str, Mapping[str, Any]],
    lifecycle_issuer: str,
    lifecycle_key_id: str,
    lifecycle_signer: Callable[[Any], str],
) -> dict[str, Any]:
    state.validate()
    checkpoint_observed = _utc_now()
    created = parse_time(state.created_at)
    if created > checkpoint_observed + MAX_CLOCK_SKEW:
        raise RecoveryError("checkpoint creation time is in the future")
    if checkpoint_observed - created > MAX_LIFECYCLE_AGE:
        raise RecoveryError("checkpoint creation time is stale")

    attestation_digest = verify_state_attestations(
        state_attestations,
        trusted_state_keys=trusted_state_keys,
        state=state,
    )
    payload = state.payload()
    envelope = {
        "schema": "VERA_R8A0_CHECKPOINT_V4",
        "payload": payload,
        "payload_digest": canonical_sha256(payload),
        "state_attestations": dict(state_attestations),
        "state_attestations_digest": attestation_digest,
        "complete": True,
    }
    _atomic(path, envelope)
    checkpoint = Path(path).resolve()
    checkpoint_digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    body = {
        "schema": "VERA_R8A0_CHECKPOINT_WRITE_RECEIPT_V5",
        "result": "CHECKPOINT_COMMITTED",
        "checkpoint_path": str(checkpoint),
        "checkpoint_digest": checkpoint_digest,
        "payload_digest": envelope["payload_digest"],
        "state_attestations_digest": attestation_digest,
        "project_id": state.project_id,
        "identity_id": state.identity_id,
        "runtime_id": state.runtime_id,
        "runtime_instance_nonce": state.runtime_instance_nonce,
        "checkpoint_observed_at": checkpoint_observed.isoformat(),
    }
    receipt = _signed(body, lifecycle_issuer, lifecycle_key_id, lifecycle_signer)
    _atomic(checkpoint_receipt_path, receipt)
    return receipt


CP_FIELDS = {
    "schema",
    "result",
    "checkpoint_path",
    "checkpoint_digest",
    "payload_digest",
    "state_attestations_digest",
    "project_id",
    "identity_id",
    "runtime_id",
    "runtime_instance_nonce",
    "checkpoint_observed_at",
}


def read_checkpoint_receipt(
    path: str | Path,
    *,
    trusted_lifecycle_keys: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    receipt_path = Path(path)
    if not receipt_path.exists():
        raise RecoveryError("checkpoint receipt is missing")
    receipt = strict_loads(receipt_path.read_bytes())
    material = _verify(
        receipt,
        trusted_lifecycle_keys,
        "VERA_R8A0_CHECKPOINT_WRITE_RECEIPT_V5",
        CP_FIELDS,
    )
    if material["result"] != "CHECKPOINT_COMMITTED":
        raise RecoveryError("checkpoint receipt is not committed")
    parse_time(str(material["checkpoint_observed_at"]))
    checkpoint = Path(material["checkpoint_path"])
    if (
        not checkpoint.exists()
        or hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        != material["checkpoint_digest"]
    ):
        raise RecoveryError("checkpoint receipt target mismatch")
    return dict(receipt)


def write_termination_intent(
    *,
    checkpoint_receipt_path: str | Path,
    termination_intent_path: str | Path,
    trusted_lifecycle_keys: Mapping[str, Mapping[str, Any]],
    lifecycle_issuer: str,
    lifecycle_key_id: str,
    lifecycle_signer: Callable[[Any], str],
    process_id: int,
) -> dict[str, Any]:
    if not isinstance(process_id, int) or process_id <= 0:
        raise RecoveryError("process ID must be a positive integer")
    checkpoint = read_checkpoint_receipt(
        checkpoint_receipt_path, trusted_lifecycle_keys=trusted_lifecycle_keys
    )
    intent_emitted = _utc_now()
    checkpoint_observed = parse_time(checkpoint["checkpoint_observed_at"])
    if checkpoint_observed > intent_emitted:
        raise RecoveryError("termination intent predates checkpoint observation")
    body = {
        "schema": "VERA_R8A0_TERMINATION_INTENT_RECEIPT_V2",
        "result": "TERMINATION_INTENT_EMITTED",
        "runtime_id": checkpoint["runtime_id"],
        "runtime_instance_nonce": checkpoint["runtime_instance_nonce"],
        "process_id": process_id,
        "checkpoint_digest": checkpoint["checkpoint_digest"],
        "checkpoint_receipt_signature": checkpoint["signature"],
        "intent_emitted_at": intent_emitted.isoformat(),
    }
    receipt = _signed(body, lifecycle_issuer, lifecycle_key_id, lifecycle_signer)
    _atomic(termination_intent_path, receipt)
    return receipt


TI_FIELDS = {
    "schema",
    "result",
    "runtime_id",
    "runtime_instance_nonce",
    "process_id",
    "checkpoint_digest",
    "checkpoint_receipt_signature",
    "intent_emitted_at",
}


def read_termination_intent(
    path: str | Path,
    *,
    trusted_lifecycle_keys: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    intent_path = Path(path)
    if not intent_path.exists():
        raise RecoveryError("termination intent is missing")
    receipt = strict_loads(intent_path.read_bytes())
    material = _verify(
        receipt,
        trusted_lifecycle_keys,
        "VERA_R8A0_TERMINATION_INTENT_RECEIPT_V2",
        TI_FIELDS,
    )
    if (
        material["result"] != "TERMINATION_INTENT_EMITTED"
        or not isinstance(material["process_id"], int)
        or material["process_id"] <= 0
    ):
        raise RecoveryError("invalid termination intent")
    parse_time(str(material["intent_emitted_at"]))
    return dict(receipt)


def write_exit_attestation(
    *,
    path: str | Path,
    checkpoint_receipt: Mapping[str, Any],
    termination_intent: Mapping[str, Any],
    exit_code: int,
    observed_at: str,
    supervisor_issuer: str,
    supervisor_key_id: str,
    supervisor_signer: Callable[[Any], str],
) -> dict[str, Any]:
    observed = parse_time(observed_at)
    intent_time = parse_time(str(termination_intent["intent_emitted_at"]))
    if intent_time > observed + MAX_CLOCK_SKEW:
        raise RecoveryError("exit observation predates termination intent")
    if not isinstance(exit_code, int):
        raise RecoveryError("exit code must be an integer")
    body = {
        "schema": "VERA_R8A0_PROCESS_EXIT_ATTESTATION_V2",
        "result": "EXIT_OBSERVED",
        "runtime_id": termination_intent["runtime_id"],
        "runtime_instance_nonce": termination_intent["runtime_instance_nonce"],
        "process_id": termination_intent["process_id"],
        "exit_code": exit_code,
        "checkpoint_receipt_signature": checkpoint_receipt["signature"],
        "termination_intent_signature": termination_intent["signature"],
        "observed_at": observed.isoformat(),
    }
    receipt = _signed(body, supervisor_issuer, supervisor_key_id, supervisor_signer)
    _atomic(path, receipt)
    return receipt


EXIT_FIELDS = {
    "schema",
    "result",
    "runtime_id",
    "runtime_instance_nonce",
    "process_id",
    "exit_code",
    "checkpoint_receipt_signature",
    "termination_intent_signature",
    "observed_at",
}


def read_exit_attestation(
    path: str | Path,
    *,
    trusted_supervisor_keys: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    attestation_path = Path(path)
    if not attestation_path.exists():
        raise RecoveryError("process exit attestation is missing")
    receipt = strict_loads(attestation_path.read_bytes())
    material = _verify(
        receipt,
        trusted_supervisor_keys,
        "VERA_R8A0_PROCESS_EXIT_ATTESTATION_V2",
        EXIT_FIELDS,
    )
    if material["result"] != "EXIT_OBSERVED" or material["exit_code"] != 0:
        raise RecoveryError("predecessor exit was not successfully observed")
    parse_time(str(material["observed_at"]))
    return dict(receipt)

