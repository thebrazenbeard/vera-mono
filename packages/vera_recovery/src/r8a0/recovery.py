"""Public recovery API for the bounded R8A0 slice."""
from .recovery_core import CheckpointState, RecoveryError, checkpoint_state_from_mapping, verify_state_attestations
from .recovery_evidence import (
    read_checkpoint_receipt, read_exit_attestation, read_termination_intent,
    write_checkpoint, write_exit_attestation, write_termination_intent,
)
from .recovery_runtime import recover

__all__ = [
    "CheckpointState", "RecoveryError", "checkpoint_state_from_mapping",
    "verify_state_attestations", "read_checkpoint_receipt", "read_exit_attestation",
    "read_termination_intent", "write_checkpoint", "write_exit_attestation",
    "write_termination_intent", "recover",
]
