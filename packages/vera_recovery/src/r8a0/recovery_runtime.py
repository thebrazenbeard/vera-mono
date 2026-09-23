"""Fresh-process recovery verification and lifecycle consumption."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical import canonical_sha256, strict_loads
from .lifecycle import LifecycleRegistry
from .recovery_core import (
    MAX_CLOCK_SKEW, MAX_LIFECYCLE_AGE, CheckpointState, RecoveryError,
    _utc_now, checkpoint_state_from_mapping, verify_state_attestations,
)
from .recovery_evidence import read_checkpoint_receipt, read_exit_attestation, read_termination_intent
from .temporal import OrientationGate, OrientationState, TimeEvidence, parse_time
from .trust import load_lifecycle_registry_key, load_trust_registry
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _validate_lifecycle_order(
    *,
    state: CheckpointState,
    checkpoint_receipt: Mapping[str, Any],
    termination_intent: Mapping[str, Any],
    exit_attestation: Mapping[str, Any],
    recovery_time: datetime,
) -> tuple[datetime, datetime, datetime, datetime]:
    created = parse_time(state.created_at)
    checkpoint_time = parse_time(str(checkpoint_receipt["checkpoint_observed_at"]))
    intent_time = parse_time(str(termination_intent["intent_emitted_at"]))
    exit_time = parse_time(str(exit_attestation["observed_at"]))
    if created > checkpoint_time + MAX_CLOCK_SKEW:
        raise RecoveryError("checkpoint creation follows observation")
    if checkpoint_time > intent_time:
        raise RecoveryError("termination intent predates checkpoint")
    if intent_time > exit_time + MAX_CLOCK_SKEW:
        raise RecoveryError("exit observation predates termination intent")
    if exit_time > recovery_time + MAX_CLOCK_SKEW:
        raise RecoveryError("recovery predates observed exit")
    if recovery_time - created > MAX_LIFECYCLE_AGE:
        raise RecoveryError("checkpoint lifecycle is stale")
    if recovery_time - exit_time > MAX_LIFECYCLE_AGE:
        raise RecoveryError("exit observation is stale")
    return created, checkpoint_time, intent_time, exit_time


def recover(
    checkpoint_path: str | Path,
    *,
    orientation_evidence: Iterable[TimeEvidence],
    orientation_source_mode: str,
    expected_trust_registry_id: str,
    expected_trust_registry_digest: str,
    expected_trust_key_set_digests: Mapping[str, str],
    checkpoint_receipt_path: str | Path,
    termination_intent_path: str | Path,
    exit_attestation_path: str | Path,
    expected_checkpoint_receipt_signature: str,
    expected_termination_intent_signature: str,
    expected_exit_attestation_signature: str,
    expected_project_id: str,
    expected_identity_id: str,
    expected_predecessor_checkpoint_digest: str,
    expected_memory_head_digest: str,
    expected_self_model_head_digest: str,
    expected_authority_state_digest: str,
    successor_runtime_id: str,
) -> dict[str, Any]:
    if not expected_project_id or not expected_identity_id or not successor_runtime_id.strip():
        raise RecoveryError("expected scope and successor runtime are required")
    trust_registry = load_trust_registry(
        expected_registry_id=expected_trust_registry_id,
        expected_registry_digest=expected_trust_registry_digest,
        expected_key_set_digests=expected_trust_key_set_digests,
        expected_project_id=expected_project_id,
        expected_identity_id=expected_identity_id,
    )
    lifecycle_registry_key = load_lifecycle_registry_key(trust_registry)
    recovery_time = _utc_now()
    orientation = OrientationGate(
        trusted_source_keys=trust_registry.keys("temporal")
    ).evaluate(
        orientation_evidence,
        now=recovery_time,
        source_mode=orientation_source_mode,
    )
    if orientation.state not in {
        OrientationState.COMPLETE,
        OrientationState.COMPLETE_FROM_FRESH_SNAPSHOT,
    }:
        raise RecoveryError("fresh temporal authority is required")

    checkpoint_receipt = read_checkpoint_receipt(
        checkpoint_receipt_path, trusted_lifecycle_keys=trust_registry.keys("lifecycle")
    )
    termination_intent = read_termination_intent(
        termination_intent_path, trusted_lifecycle_keys=trust_registry.keys("lifecycle")
    )
    exit_attestation = read_exit_attestation(
        exit_attestation_path, trusted_supervisor_keys=trust_registry.keys("supervisor")
    )
    if (
        checkpoint_receipt["signature"] != expected_checkpoint_receipt_signature
        or termination_intent["signature"] != expected_termination_intent_signature
        or exit_attestation["signature"] != expected_exit_attestation_signature
    ):
        raise RecoveryError("lifecycle evidence does not match independently observed signatures")
    if (
        termination_intent["checkpoint_receipt_signature"]
        != checkpoint_receipt["signature"]
        or exit_attestation["checkpoint_receipt_signature"]
        != checkpoint_receipt["signature"]
        or exit_attestation["termination_intent_signature"]
        != termination_intent["signature"]
    ):
        raise RecoveryError("lifecycle evidence chain mismatch")
    for key in ("runtime_id", "runtime_instance_nonce"):
        if (
            checkpoint_receipt[key] != termination_intent[key]
            or termination_intent[key] != exit_attestation[key]
        ):
            raise RecoveryError("runtime instance chain mismatch")
    if _alive(int(exit_attestation["process_id"])):
        raise RecoveryError("predecessor process remains alive")

    checkpoint = Path(checkpoint_path).resolve()
    if (
        str(checkpoint) != checkpoint_receipt["checkpoint_path"]
        or hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        != checkpoint_receipt["checkpoint_digest"]
    ):
        raise RecoveryError("checkpoint receipt target mismatch")
    data = strict_loads(checkpoint.read_bytes())
    if (
        set(data)
        != {
            "schema",
            "payload",
            "payload_digest",
            "state_attestations",
            "state_attestations_digest",
            "complete",
        }
        or data["schema"] != "VERA_R8A0_CHECKPOINT_V4"
        or data["complete"] is not True
    ):
        raise RecoveryError("checkpoint is partial or unsupported")
    if (
        canonical_sha256(data["payload"]) != data["payload_digest"]
        or data["payload_digest"] != checkpoint_receipt["payload_digest"]
    ):
        raise RecoveryError("checkpoint payload mismatch")

    state = checkpoint_state_from_mapping(data["payload"])
    attestation_digest = verify_state_attestations(
        data["state_attestations"],
        trusted_state_keys=trust_registry.keys("state"),
        state=state,
    )
    if (
        attestation_digest != data["state_attestations_digest"]
        or attestation_digest != checkpoint_receipt["state_attestations_digest"]
    ):
        raise RecoveryError("state attestation bundle mismatch")
    expected = {
        "project_id": expected_project_id,
        "identity_id": expected_identity_id,
        "predecessor_checkpoint_digest": expected_predecessor_checkpoint_digest,
        "memory_head_digest": expected_memory_head_digest,
        "self_model_head_digest": expected_self_model_head_digest,
        "authority_state_digest": expected_authority_state_digest,
    }
    for key, value in expected.items():
        if getattr(state, key) != value:
            raise RecoveryError("checkpoint scope or state-root mismatch")
    if successor_runtime_id == state.runtime_id:
        raise RecoveryError("successor runtime must differ")

    created, checkpoint_time, intent_time, exit_time = _validate_lifecycle_order(
        state=state,
        checkpoint_receipt=checkpoint_receipt,
        termination_intent=termination_intent,
        exit_attestation=exit_attestation,
        recovery_time=recovery_time,
    )

    registry = LifecycleRegistry(
        trust_registry.lifecycle_registry_path, lifecycle_registry_key
    )
    lifecycle_pre_head = registry.current_head()
    claim = {
        "schema": "VERA_R8A0_RUNTIME_RESUMPTION_CLAIM_V2",
        "project_id": state.project_id,
        "identity_id": state.identity_id,
        "prior_runtime_id": state.runtime_id,
        "successor_runtime_id": successor_runtime_id,
        "checkpoint_receipt_signature": checkpoint_receipt["signature"],
        "termination_intent_signature": termination_intent["signature"],
        "exit_attestation_signature": exit_attestation["signature"],
        "lifecycle_registry_pre_head": lifecycle_pre_head,
        "trust_binding": trust_registry.binding(),
    }
    claim_digest = canonical_sha256(claim)
    lifecycle_post_head = registry.consume(
        termination_signature=termination_intent["signature"],
        checkpoint_signature=checkpoint_receipt["signature"],
        predecessor_runtime_id=state.runtime_id,
        successor_runtime_id=successor_runtime_id,
        resumption_claim_digest=claim_digest,
        expected_head=lifecycle_pre_head,
    )
    body = {
        "schema": "VERA_R8A0_RUNTIME_RESUMPTION_RECEIPT_V7",
        "result": "RECOVERED_FROM_VERIFIED_CHECKPOINT",
        "project_id": state.project_id,
        "identity_id": state.identity_id,
        "prior_runtime_id": state.runtime_id,
        "prior_runtime_instance_nonce": state.runtime_instance_nonce,
        "successor_runtime_id": successor_runtime_id,
        "prior_process_id": exit_attestation["process_id"],
        "successor_process_id": os.getpid(),
        "runtime_transition_observed": True,
        "new_runtime_is_separate_person": False,
        "same_governed_identity_resumed": True,
        "uninterrupted_consciousness_claimed": False,
        "memory_head_digest": state.memory_head_digest,
        "self_model_head_digest": state.self_model_head_digest,
        "authority_state_digest": state.authority_state_digest,
        "predecessor_checkpoint_digest": state.predecessor_checkpoint_digest,
        "active_commitments": list(state.active_commitments),
        "unfinished_work": list(state.unfinished_work),
        "checkpoint_created_at": created.isoformat(),
        "checkpoint_observed_at": checkpoint_time.isoformat(),
        "termination_intent_at": intent_time.isoformat(),
        "exit_observed_at": exit_time.isoformat(),
        "recovery_evaluated_at": recovery_time.isoformat(),
        "checkpoint_receipt_signature": checkpoint_receipt["signature"],
        "termination_intent_signature": termination_intent["signature"],
        "exit_attestation_signature": exit_attestation["signature"],
        "resumption_claim_digest": claim_digest,
        "lifecycle_registry_pre_head": lifecycle_pre_head,
        "lifecycle_registry_post_head": lifecycle_post_head,
        "orientation_receipt": orientation.as_dict(),
        "trust_binding": trust_registry.binding(),
    }
    return body | {"receipt_digest": canonical_sha256(body)}

