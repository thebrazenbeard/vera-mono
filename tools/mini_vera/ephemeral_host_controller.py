"""Operator-only one-shot external source-read signing trial.

Runs the issuer in a new same-user process and verifies its response.
A public key supplied in the SAME untrusted response is NOT an independent
trust anchor, and no protected host signer/issuer is activated by this trial.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from typing import Any

from . import signed_host_receipt

TRIAL_SCHEMA = "MINI_VERA_EPHEMERAL_HOST_TRIAL_V1"
PUBLIC_KEY = re.compile(r"[a-f0-9]{64}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
MAX_RESULT_BYTES = 4096
ISSUE_RESULT_FIELDS = frozenset({
    "schema", "ephemeral_public_key_hex", "ephemeral_public_key_sha256",
    "issuer_process_id", "key_trust", "host_issuer_qualified",
    "signed_receipt",
})


class TrialRefused(ValueError):
    """The one-read IPC session could not be independently parsed/validated."""


def _minimal_environment() -> dict[str, str]:
    # Avoid carrying user/AI secrets, PYTHONPATH, and host tool credentials
    # unnecessarily into the disposable issuer subprocess.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _parse_result(blob: bytes) -> dict[str, Any]:
    if (type(blob) is not bytes or len(blob) > MAX_RESULT_BYTES
            or not blob.endswith(b"\n") or blob.count(b"\n") != 1):
        raise TrialRefused("issuer did not produce exactly one bounded record")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in pairs:
            if k in result:
                raise TrialRefused("duplicate issuer field")
            result[k] = v
        return result

    try:
        packet = json.loads(blob[:-1].decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise TrialRefused("issuer output is not canonical JSON structure") from exc
    if (type(packet) is not dict or set(packet) != ISSUE_RESULT_FIELDS
            or packet["schema"] != "MINI_VERA_EPHEMERAL_ISSUE_RESULT_V1"
            or packet["key_trust"] != "UNPINNED_EPHEMERAL_KEY_NOT_HOST_TRUST"
            or packet["host_issuer_qualified"] is not False
            or type(packet["issuer_process_id"]) is not int
            or packet["issuer_process_id"] <= 0
            or packet["issuer_process_id"] == os.getpid()
            or type(packet["ephemeral_public_key_hex"]) is not str
            or PUBLIC_KEY.fullmatch(packet["ephemeral_public_key_hex"]) is None
            or type(packet["ephemeral_public_key_sha256"]) is not str
            or HEX64.fullmatch(packet["ephemeral_public_key_sha256"]) is None
            or type(packet["signed_receipt"]) is not dict):
        raise TrialRefused("unsupported or spoofed issuer status")
    key = bytes.fromhex(packet["ephemeral_public_key_hex"])
    if hashlib.sha256(key).hexdigest() != packet["ephemeral_public_key_sha256"]:
        raise TrialRefused("issuer public key hash mismatch")
    return packet


def run_trial(*, request_sha256: str, turn_sha256: str,
              expected_source_sha256: str) -> dict[str, Any]:
    """Observe, sign and verify one source hash across real process boundaries."""
    for label, value in (
        ("request", request_sha256),
        ("turn", turn_sha256),
        ("expected source", expected_source_sha256),
    ):
        if type(value) is not str or HEX64.fullmatch(value) is None:
            raise TrialRefused(f"invalid {label} digest")
    challenge = secrets.token_hex(16)
    request = {
        "schema": "MINI_VERA_EPHEMERAL_ISSUE_REQUEST_V1",
        "request_sha256": request_sha256,
        "turn_sha256": turn_sha256,
        "expected_source_sha256": expected_source_sha256,
        "challenge_hex": challenge,
    }
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "tools.mini_vera.ephemeral_host_issuer",
             "--issue-once"],
            input=signed_host_receipt.canonical(request) + b"\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            cwd=str(Path(__file__).resolve().parents[2]),
            env=_minimal_environment(), timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TrialRefused("bounded issuer subprocess failed") from exc
    if completed.returncode != 0:
        raise TrialRefused("issuer refused or failed to complete source read")
    packet = _parse_result(completed.stdout)
    try:
        raw_key = bytes.fromhex(packet["ephemeral_public_key_hex"])
        verifier = signed_host_receipt.OneShotSignedHostVerifier(
            trusted_public_key=raw_key,
            expected_public_key_sha256=packet["ephemeral_public_key_sha256"],
            expected_request_sha256=request_sha256,
            expected_turn_sha256=turn_sha256,
            expected_source_sha256=expected_source_sha256,
            challenge_hex=challenge, now=datetime.now(timezone.utc))
        receipt_bytes = signed_host_receipt.canonical(packet["signed_receipt"])
        proof = verifier.accept(receipt_bytes)
    except (signed_host_receipt.ReceiptRefused, ValueError, TypeError) as exc:
        raise TrialRefused("unverified ephemeral source signature") from exc
    return {
        "schema": TRIAL_SCHEMA,
        "status": "EPHEMERAL_SIGNATURE_CONSISTENT_SOURCE_READ_NOT_ATTESTED",
        "signature_status": proof["signature_status"],
        "source_name": proof["source_name"],
        "source_sha256": proof["source_sha256"],
        "source_size_bytes": proof["source_size_bytes"],
        "operation": proof["operation"],
        "request_sha256": request_sha256,
        "turn_sha256": turn_sha256,
        "challenge_hex": challenge,
        "issuer_process_id": packet["issuer_process_id"],
        "trust_root": "UNTRUSTED_SAME_USER_EPHEMERAL_SESSION_KEY",
        "host_issuer_qualified": False,
        "source_read_attested": False,
        "issuer_pid_provenance": "UNTRUSTED_CHILD_REPORT_NOT_OS_ATTESTATION",
        "verified_external_effects": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-one-read-only-trial", action="store_true")
    parser.add_argument("--request-sha256")
    parser.add_argument("--turn-sha256")
    parser.add_argument("--expected-source-sha256")
    args = parser.parse_args(argv)
    if not args.run_one_read_only_trial:
        parser.error("explicit --run-one-read-only-trial required")
    try:
        report = run_trial(
            request_sha256=args.request_sha256,
            turn_sha256=args.turn_sha256,
            expected_source_sha256=args.expected_source_sha256)
    except TrialRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(signed_host_receipt.canonical(report).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
