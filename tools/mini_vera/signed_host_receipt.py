"""Verify an externally signed, one-shot host observation without holding signing keys.

SOURCE CANDIDATE ONLY: accepting a signature from a test key does not
qualify its issuer, Windows ACLs, host identity, clock or the model weights.
Optional cryptography dependency is loaded only when verifying a receipt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import threading
from typing import Any

SCHEMA = "MINI_VERA_SIGNED_HOST_RECEIPT_V1"
PAYLOAD_SCHEMA = "MINI_VERA_HOST_READ_SIGNED_PAYLOAD_V1"
MAX_RECEIPT_BYTES = 4096
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX128 = re.compile(r"[0-9a-f]{128}\Z")
ISSUER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
PAYLOAD_KEYS = frozenset({
    "schema", "issuer_id", "operation", "source_name", "source_sha256",
    "source_size_bytes", "effect", "request_sha256", "turn_sha256",
    "challenge_hex", "issued_at_utc",
})


class ReceiptRefused(ValueError):
    """Signed receipt lacks a bounded, externally anchored verification."""


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _parse_receipt(blob: bytes) -> dict[str, Any]:
    if type(blob) is not bytes or not 0 < len(blob) <= MAX_RECEIPT_BYTES:
        raise ReceiptRefused("receipt missing or oversized")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in pairs:
            if k in result:
                raise ReceiptRefused("duplicate JSON field")
            result[k] = v
        return result

    try:
        data = json.loads(blob.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ReceiptRefused("nonfinite JSON refused")))
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ReceiptRefused("malformed signed receipt") from exc
    if (type(data) is not dict
            or set(data) != {"schema", "payload", "signature_ed25519_hex"}
            or data["schema"] != SCHEMA
            or type(data["payload"]) is not dict
            or set(data["payload"]) != PAYLOAD_KEYS
            or type(data["signature_ed25519_hex"]) is not str
            or HEX128.fullmatch(data["signature_ed25519_hex"]) is None):
        raise ReceiptRefused("unexpected signed receipt shape")
    return data


def _digest(value: Any, field: str) -> str:
    if type(value) is not str or HEX64.fullmatch(value) is None:
        raise ReceiptRefused(f"invalid {field}")
    return value


class OneShotSignedHostVerifier:
    """Trust anchor comes from caller, never a model-provided instruction.

    Each verifier instance accepts at most one valid receipt. A fresh 128-bit
    challenge must be allocated by the operator's independent controller for
    each turn/restart. This alone is NOT host-protected replay durability.
    """

    def __init__(self, *, trusted_public_key: bytes,
                 expected_public_key_sha256: str,
                 expected_request_sha256: str,
                 expected_turn_sha256: str,
                 expected_source_sha256: str,
                 challenge_hex: str,
                 now: datetime | None = None) -> None:
        self._pin = _digest(expected_public_key_sha256, "trusted public key pin")
        self._request = _digest(expected_request_sha256, "request binding")
        self._turn = _digest(expected_turn_sha256, "turn binding")
        self._source = _digest(expected_source_sha256, "source binding")
        if type(challenge_hex) is not str or HEX32.fullmatch(challenge_hex) is None:
            raise ReceiptRefused("invalid challenge")
        if (type(trusted_public_key) is not bytes or len(trusted_public_key) != 32
                or not hmac.compare_digest(
                    hashlib.sha256(trusted_public_key).hexdigest(), self._pin)):
            raise ReceiptRefused("trusted issuer public key does not match operator pin")
        self._public_key = trusted_public_key
        self._challenge = challenge_hex
        self._now = datetime.now(timezone.utc) if now is None else now
        if self._now.tzinfo is None or self._now.utcoffset() != timedelta(0):
            raise ReceiptRefused("clock must be UTC aware")
        self._used = False
        self._lock = threading.Lock()

    def accept(self, blob: bytes) -> dict[str, Any]:
        with self._lock:
            if self._used:
                raise ReceiptRefused("one-shot challenge already consumed")
            env = _parse_receipt(blob)
            data = env["payload"]
            if (data["schema"] != PAYLOAD_SCHEMA
                    or type(data["issuer_id"]) is not str
                    or ISSUER.fullmatch(data["issuer_id"]) is None
                    or data["operation"] != "READ_ONLY_SOURCE_SHA256"
                    or data["source_name"] != "tools/mini_vera/compose.py"
                    or data["effect"] != "NONE"
                    or type(data["source_size_bytes"]) is not int
                    or not 0 < data["source_size_bytes"] <= 256 * 1024):
                raise ReceiptRefused("invalid host operation or effect claim")
            for field, expected in (
                ("request_sha256", self._request),
                ("turn_sha256", self._turn),
                ("source_sha256", self._source),
                ("challenge_hex", self._challenge),
            ):
                text = data[field]
                pattern = HEX32 if field == "challenge_hex" else HEX64
                if type(text) is not str or pattern.fullmatch(text) is None or not hmac.compare_digest(text, expected):
                    raise ReceiptRefused(f"mismatched host {field}")
            if type(data["issued_at_utc"]) is not str:
                raise ReceiptRefused("invalid issuance time")
            try:
                issued = datetime.fromisoformat(data["issued_at_utc"])
            except ValueError as exc:
                raise ReceiptRefused("invalid issuance timestamp") from exc
            if (issued.tzinfo is None or issued.utcoffset() != timedelta(0)
                    or issued < self._now - timedelta(seconds=120)
                    or issued > self._now + timedelta(seconds=5)):
                raise ReceiptRefused("stale or future-dated observation")
            try:
                from cryptography.exceptions import InvalidSignature
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            except ImportError as exc:
                raise ReceiptRefused("Ed25519 verification dependency unavailable") from exc
            try:
                Ed25519PublicKey.from_public_bytes(self._public_key).verify(
                    bytes.fromhex(env["signature_ed25519_hex"]), canonical(data))
            except (InvalidSignature, ValueError) as exc:
                raise ReceiptRefused("issuer signature invalid") from exc
            self._used = True
            return {
                "schema": "MINI_VERA_VERIFIED_EXTERNAL_SIGNATURE_V1",
                "issuer_id": data["issuer_id"],
                "signature_status": "VALID_ED25519_PINNED_KEY",
                "source_name": data["source_name"],
                "source_sha256": data["source_sha256"],
                "source_size_bytes": data["source_size_bytes"],
                "request_sha256": data["request_sha256"],
                "turn_sha256": data["turn_sha256"],
                "operation": data["operation"],
                "effect": "NONE",
                "evidence_class": "EXTERNAL_SIGNED_PAYLOAD_NOT_HOST_QUALIFICATION",
                "host_issuer_qualified": False,
            }
