"""Issuer, supervisor, and recovery entry points for bounded R8A0."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_bytes, strict_loads
from .recovery import (
    checkpoint_state_from_mapping,
    read_checkpoint_receipt,
    read_termination_intent,
    recover,
    write_checkpoint,
    write_exit_attestation,
    write_termination_intent,
)
from .temporal import evidence_from_mapping
from .trust import load_trust_registry

_DER = bytes.fromhex("3031300d060960864801650304020105000420")

TRUST_REFERENCE_FIELDS = {
    "trust_registry_id",
    "trust_registry_digest",
    "trust_key_set_digests",
}



def _load_provisioned_trust_registry(
    input_data: Mapping[str, Any], *, expected_project_id: str, expected_identity_id: str
):
    return load_trust_registry(
        expected_registry_id=input_data["trust_registry_id"],
        expected_registry_digest=input_data["trust_registry_digest"],
        expected_key_set_digests=input_data["trust_key_set_digests"],
        expected_project_id=expected_project_id,
        expected_identity_id=expected_identity_id,
    )


def _env(prefix: str) -> tuple[str, str, int, int]:
    issuer = os.environ.get(prefix + "_ISSUER", "")
    key_id = os.environ.get(prefix + "_KEY_ID", "")
    modulus = int(os.environ.get(prefix + "_N_HEX", "0"), 16)
    private_exponent = int(os.environ.get(prefix + "_D_HEX", "0"), 16)
    if (
        not issuer
        or not key_id
        or modulus.bit_length() < 1024
        or private_exponent < 2
    ):
        raise ValueError(prefix + " private signing material is incomplete")
    return issuer, key_id, modulus, private_exponent


def _signer(prefix: str):
    issuer, key_id, modulus, private_exponent = _env(prefix)
    width = (modulus.bit_length() + 7) // 8

    def sign(payload: Any) -> str:
        tail = _DER + hashlib.sha256(canonical_bytes(payload)).digest()
        encoded = b"\x00\x01" + b"\xff" * (width - len(tail) - 3) + b"\x00" + tail
        return format(
            pow(int.from_bytes(encoded, "big"), private_exponent, modulus), "x"
        )

    return issuer, key_id, sign


def _load_object(path: str | Path, *, expected_fields: set[str]) -> dict[str, Any]:
    value = strict_loads(Path(path).read_bytes())
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise ValueError("input fields are missing or unknown")
    return value


def _worker(args: argparse.Namespace) -> int:
    input_data = _load_object(
        args.input,
        expected_fields={"state", "state_attestations", *TRUST_REFERENCE_FIELDS},
    )
    if not isinstance(input_data["state"], Mapping):
        raise ValueError("checkpoint state must be an object")
    state = checkpoint_state_from_mapping(input_data["state"])
    trust_registry = _load_provisioned_trust_registry(
        input_data, expected_project_id=state.project_id, expected_identity_id=state.identity_id
    )
    issuer, key_id, signer = _signer("VERA_R8A0_LIFECYCLE")
    checkpoint = write_checkpoint(
        args.checkpoint,
        state,
        checkpoint_receipt_path=args.checkpoint_receipt,
        state_attestations=input_data["state_attestations"],
        trusted_state_keys=trust_registry.keys("state"),
        lifecycle_issuer=issuer,
        lifecycle_key_id=key_id,
        lifecycle_signer=signer,
    )
    termination = write_termination_intent(
        checkpoint_receipt_path=args.checkpoint_receipt,
        termination_intent_path=args.termination_intent,
        trusted_lifecycle_keys=trust_registry.keys("lifecycle"),
        lifecycle_issuer=issuer,
        lifecycle_key_id=key_id,
        lifecycle_signer=signer,
        process_id=os.getpid(),
    )
    print(
        json.dumps(
            {
                "checkpoint_signature": checkpoint["signature"],
                "termination_signature": termination["signature"],
                "process_id": os.getpid(),
            },
            sort_keys=True,
        )
    )
    return 0


def _supervise(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        "-m",
        "r8a0.cli",
        "checkpoint-worker",
        "--input",
        args.input,
        "--checkpoint",
        args.checkpoint,
        "--checkpoint-receipt",
        args.checkpoint_receipt,
        "--termination-intent",
        args.termination_intent,
    ]
    child_environment = os.environ.copy()
    for key in tuple(child_environment):
        if key.startswith("VERA_R8A0_SUPERVISOR_"):
            child_environment.pop(key)
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=child_environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    input_data = _load_object(
        args.input,
        expected_fields={"state", "state_attestations", *TRUST_REFERENCE_FIELDS},
    )
    if not isinstance(input_data["state"], Mapping):
        raise ValueError("checkpoint state must be an object")
    state = checkpoint_state_from_mapping(input_data["state"])
    trust_registry = _load_provisioned_trust_registry(
        input_data, expected_project_id=state.project_id, expected_identity_id=state.identity_id
    )
    checkpoint = read_checkpoint_receipt(
        args.checkpoint_receipt,
        trusted_lifecycle_keys=trust_registry.keys("lifecycle"),
    )
    termination = read_termination_intent(
        args.termination_intent,
        trusted_lifecycle_keys=trust_registry.keys("lifecycle"),
    )
    issuer, key_id, signer = _signer("VERA_R8A0_SUPERVISOR")
    exit_attestation = write_exit_attestation(
        path=args.exit_attestation,
        checkpoint_receipt=checkpoint,
        termination_intent=termination,
        exit_code=process.returncode,
        observed_at=datetime.now(timezone.utc).isoformat(),
        supervisor_issuer=issuer,
        supervisor_key_id=key_id,
        supervisor_signer=signer,
    )
    print(
        json.dumps(
            {
                "worker_stdout": stdout,
                "worker_stderr": stderr,
                "exit_signature": exit_attestation["signature"],
                "exit_code": process.returncode,
            },
            sort_keys=True,
        )
    )
    return 0 if process.returncode == 0 else process.returncode


def _recover(args: argparse.Namespace) -> int:
    required = {
        "orientation_evidence",
        "orientation_source_mode",
        *TRUST_REFERENCE_FIELDS,
        "checkpoint_receipt_path",
        "termination_intent_path",
        "exit_attestation_path",
        "expected_checkpoint_receipt_signature",
        "expected_termination_intent_signature",
        "expected_exit_attestation_signature",
        "expected_project_id",
        "expected_identity_id",
        "expected_predecessor_checkpoint_digest",
        "expected_memory_head_digest",
        "expected_self_model_head_digest",
        "expected_authority_state_digest",
        "successor_runtime_id",
    }
    input_data = _load_object(args.input, expected_fields=required)
    receipt = recover(
        args.checkpoint,
        orientation_evidence=evidence_from_mapping(input_data["orientation_evidence"]),
        orientation_source_mode=input_data["orientation_source_mode"],
        expected_trust_registry_id=input_data["trust_registry_id"],
        expected_trust_registry_digest=input_data["trust_registry_digest"],
        expected_trust_key_set_digests=input_data["trust_key_set_digests"],
        checkpoint_receipt_path=input_data["checkpoint_receipt_path"],
        termination_intent_path=input_data["termination_intent_path"],
        exit_attestation_path=input_data["exit_attestation_path"],
        expected_checkpoint_receipt_signature=input_data[
            "expected_checkpoint_receipt_signature"
        ],
        expected_termination_intent_signature=input_data[
            "expected_termination_intent_signature"
        ],
        expected_exit_attestation_signature=input_data[
            "expected_exit_attestation_signature"
        ],
        expected_project_id=input_data["expected_project_id"],
        expected_identity_id=input_data["expected_identity_id"],
        expected_predecessor_checkpoint_digest=input_data[
            "expected_predecessor_checkpoint_digest"
        ],
        expected_memory_head_digest=input_data["expected_memory_head_digest"],
        expected_self_model_head_digest=input_data["expected_self_model_head_digest"],
        expected_authority_state_digest=input_data["expected_authority_state_digest"],
        successor_runtime_id=input_data["successor_runtime_id"],
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("checkpoint-worker", _worker), ("supervise", _supervise)):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--checkpoint", required=True)
        command.add_argument("--checkpoint-receipt", required=True)
        command.add_argument("--termination-intent", required=True)
        if name == "supervise":
            command.add_argument("--exit-attestation", required=True)
        command.set_defaults(handler=handler)
    command = subparsers.add_parser("recover")
    command.add_argument("checkpoint")
    command.add_argument("--input", required=True)
    command.set_defaults(handler=_recover)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
