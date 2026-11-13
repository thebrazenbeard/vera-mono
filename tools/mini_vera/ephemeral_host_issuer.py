"""One fixed read-only host source observation, ephemeral Ed25519 subprocess.

Operator trial ONLY. This process runs under the caller's account and has no
independent host/OS principal protection. The ephemeral public key returned
alongside its signature is NOT an independently authenticated trust anchor.
No persistent signing key, service, listener, model or user-selected action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import sys
from typing import Any

from . import host_read_probe, signed_host_receipt

REQUEST_SCHEMA = "MINI_VERA_EPHEMERAL_ISSUE_REQUEST_V1"
RESULT_SCHEMA = "MINI_VERA_EPHEMERAL_ISSUE_RESULT_V1"
MAX_REQUEST_BYTES = 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
FIELDS = frozenset({
    "schema", "request_sha256", "turn_sha256",
    "expected_source_sha256", "challenge_hex",
})


class IssueRefused(ValueError):
    """An unauthenticated or incorrectly scoped issuer request was refused."""


def _read_request() -> dict[str, str]:
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if (not raw.endswith(b"\n") or len(raw) > MAX_REQUEST_BYTES
            or raw.count(b"\n") != 1 or not raw[:-1]):
        raise IssueRefused("invalid bounded request")
    # Require EOF after exactly one record. Caller must close stdin before
    # signing; a controller must impose a process timeout for stalled pipes.
    if sys.stdin.buffer.read(1):
        raise IssueRefused("more than one request record")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in pairs:
            if k in result:
                raise IssueRefused("duplicate request fields")
            result[k] = v
        return result

    try:
        request = json.loads(
            raw[:-1].decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                IssueRefused("nonfinite request field")))
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise IssueRefused("unparseable issue request") from exc
    if (type(request) is not dict or set(request) != FIELDS
            or request["schema"] != REQUEST_SCHEMA):
        raise IssueRefused("issuer only accepts one fixed operation schema")
    for field in ("request_sha256", "turn_sha256", "expected_source_sha256"):
        value = request[field]
        if type(value) is not str or HEX64.fullmatch(value) is None:
            raise IssueRefused("invalid digest binding")
    challenge = request["challenge_hex"]
    if type(challenge) is not str or HEX32.fullmatch(challenge) is None:
        raise IssueRefused("invalid fresh challenge")
    return request


def _read_source_checked(request: dict[str, str]) -> bytes:
    source = host_read_probe._read_fixed_source()
    # This read is a real local file observation, not a model claim.
    host_read_probe._manifest_binding(source)
    source_sha = hashlib.sha256(source).hexdigest()
    if not hmac.compare_digest(request["expected_source_sha256"], source_sha):
        raise IssueRefused("source digest disagrees with controller expectation")
    return source


def issue_once() -> int:
    try:
        request = _read_request()
        source = _read_source_checked(request)
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError as exc:
            raise IssueRefused("Ed25519 signing dependency unavailable") from exc
        # Only a disposable, process-local signer key. No key export/write.
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        payload = {
            "schema": signed_host_receipt.PAYLOAD_SCHEMA,
            "issuer_id": "mini-vera-ephemeral-v1",
            "operation": "READ_ONLY_SOURCE_SHA256",
            "source_name": "tools/mini_vera/compose.py",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "source_size_bytes": len(source),
            "effect": "NONE",
            "request_sha256": request["request_sha256"],
            "turn_sha256": request["turn_sha256"],
            "challenge_hex": request["challenge_hex"],
            "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        signed_receipt = {
            "schema": signed_host_receipt.SCHEMA,
            "payload": payload,
            "signature_ed25519_hex": key.sign(
                signed_host_receipt.canonical(payload)).hex(),
        }
        response = {
            "schema": RESULT_SCHEMA,
            "ephemeral_public_key_hex": public.hex(),
            "ephemeral_public_key_sha256": hashlib.sha256(public).hexdigest(),
            "issuer_process_id": os.getpid(),
            "key_trust": "UNPINNED_EPHEMERAL_KEY_NOT_HOST_TRUST",
            "host_issuer_qualified": False,
            "signed_receipt": signed_receipt,
        }
        sys.stdout.buffer.write(signed_host_receipt.canonical(response) + b"\n")
        sys.stdout.buffer.flush()
        return 0
    except (IssueRefused, host_read_probe.ProbeRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-once", action="store_true",
                        help="Accept one bounded read-only digest challenge on stdin")
    args = parser.parse_args(argv)
    if not args.issue_once:
        parser.error("explicit --issue-once required")
    return issue_once()


if __name__ == "__main__":
    raise SystemExit(main())
