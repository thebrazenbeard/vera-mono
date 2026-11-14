"""Verify fixed-scope Ed25519-signed PUBLIC-memory grant candidates.

SOURCE CANDIDATE. The caller must independently provision and pin the issuer
public key. A valid signature authenticates only THAT key's signed bytes; it
does not prove protected issuer custody, authorization, source truth, or live
host identity. There is no signer or private key in this runtime module.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from typing import Any, Callable

from .compose import ID, MAX_RECORDS, canonical
from .host_memory_broker import PublicMemoryGrant

SCHEMA = "MINI_VERA_SIGNED_PUBLIC_GRANT_V1"
PAYLOAD_SCHEMA = "MINI_VERA_SIGNED_PUBLIC_GRANT_PAYLOAD_V1"
MAX_ENVELOPE_BYTES = 8192
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX128 = re.compile(r"[0-9a-f]{128}\Z")
ISSUER = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
PAYLOAD_FIELDS = frozenset({
    "schema", "issuer_id", "issued_at_unix", "project_id", "identity_id",
    "ledger_head", "revision", "record_ids", "record_digests",
    "approval_epoch", "authority_revision", "expires_at_unix",
})
MAX_U64 = 2**64-1


class SignedGrantRefused(ValueError):
    """The candidate is not a bounded, correctly pinned PUBLIC grant."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SignedGrantRefused("duplicate signed-grant JSON field")
        result[key] = value
    return result


def _parse(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ENVELOPE_BYTES:
        raise SignedGrantRefused("invalid signed-grant byte length")
    try:
        env = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                SignedGrantRefused("nonfinite value")))
    except (UnicodeError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise SignedGrantRefused("malformed signed PUBLIC grant") from exc
    if (type(env) is not dict
            or set(env) != {"schema", "payload", "signature_ed25519_hex"}
            or env["schema"] != SCHEMA
            or type(env["payload"]) is not dict
            or set(env["payload"]) != PAYLOAD_FIELDS
            or type(env["signature_ed25519_hex"]) is not str
            or HEX128.fullmatch(env["signature_ed25519_hex"]) is None):
        raise SignedGrantRefused("unsupported signed PUBLIC grant envelope")
    return env


def _u64(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_U64


class PinnedSignedPublicGrantReader:
    """Stateless signature+scope verifier suitable for broker current_grant.

    This does not track revocation or establish protected grant issuance.
    Callers must still provide the broker's independent authority reader,
    durable revision floor, record policy, current ledger and host clock.
    """

    def __init__(self, *, trusted_public_key: bytes,
                 expected_public_key_sha256: str,
                 expected_issuer_id: str,
                 expected_project_id: str,
                 expected_identity_id: str,
                 now_seconds: Callable[[], float] = time.time) -> None:
        if (type(trusted_public_key) is not bytes
                or len(trusted_public_key) != 32
                or type(expected_public_key_sha256) is not str
                or HEX64.fullmatch(expected_public_key_sha256) is None
                or not hmac.compare_digest(
                    hashlib.sha256(trusted_public_key).hexdigest(),
                    expected_public_key_sha256)):
            raise SignedGrantRefused("issuer public key not independently pinned")
        if (type(expected_issuer_id) is not str
                or ISSUER.fullmatch(expected_issuer_id) is None
                or type(expected_project_id) is not str
                or ID.fullmatch(expected_project_id) is None
                or type(expected_identity_id) is not str
                or ID.fullmatch(expected_identity_id) is None
                or not callable(now_seconds)):
            raise SignedGrantRefused("invalid issuer scope or host clock")
        self._key = trusted_public_key
        self._issuer = expected_issuer_id
        self._project = expected_project_id
        self._identity = expected_identity_id
        self._clock = now_seconds

    def verify(self, raw: bytes) -> PublicMemoryGrant:
        env = _parse(raw)
        payload = env["payload"]
        try:
            now = self._clock()
        except Exception as exc:
            raise SignedGrantRefused("signed grant clock unavailable") from exc
        if (type(now) not in (int, float)
                or not math.isfinite(now)):
            raise SignedGrantRefused("invalid host clock")

        if (payload["schema"] != PAYLOAD_SCHEMA
                or payload["issuer_id"] != self._issuer
                or payload["project_id"] != self._project
                or payload["identity_id"] != self._identity
                or type(payload["issuer_id"]) is not str
                or type(payload["project_id"]) is not str
                or type(payload["identity_id"]) is not str):
            raise SignedGrantRefused("signed grant issuer or scope mismatched")

        issued = payload["issued_at_unix"]
        expiry = payload["expires_at_unix"]
        if (not _u64(issued) or not _u64(expiry)
                or not (now-120 <= issued <= now+5)
                or not (now < expiry <= now+1800)
                or issued >= expiry):
            raise SignedGrantRefused("signed grant stale, future or expired")

        if (type(payload["ledger_head"]) is not str
                or HEX64.fullmatch(payload["ledger_head"]) is None
                or any(not _u64(payload[field]) for field in (
                    "revision", "approval_epoch", "authority_revision"))):
            raise SignedGrantRefused("signed grant revision or ledger head invalid")

        record_ids = payload["record_ids"]
        record_digests = payload["record_digests"]
        if (type(record_ids) is not list or type(record_digests) is not list
                or len(record_ids) != len(record_digests)
                or len(record_ids) > MAX_RECORDS):
            raise SignedGrantRefused("signed record selection invalid")
        if (any(type(x) is not str or ID.fullmatch(x) is None
                for x in record_ids)
                or len(set(record_ids)) != len(record_ids)
                or any(type(row) is not list or len(row) != 2
                       or type(row[0]) is not str or row[0] != selected
                       or type(row[1]) is not str or HEX64.fullmatch(row[1]) is None
                       for row, selected in zip(record_digests, record_ids))):
            raise SignedGrantRefused("signed record digests invalid")
        try:
            canonical_bytes = canonical(payload)
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            Ed25519PublicKey.from_public_bytes(self._key).verify(
                bytes.fromhex(env["signature_ed25519_hex"]), canonical_bytes)
        except ImportError as exc:
            raise SignedGrantRefused("optional Ed25519 verifier unavailable") from exc
        except (ValueError, InvalidSignature, UnicodeError, TypeError) as exc:
            raise SignedGrantRefused("signed grant signature invalid") from exc

        return PublicMemoryGrant(
            project_id=payload["project_id"],
            identity_id=payload["identity_id"],
            ledger_head=payload["ledger_head"],
            revision=payload["revision"],
            record_ids=tuple(record_ids),
            record_digests=tuple((row[0], row[1]) for row in record_digests),
            approval_epoch=payload["approval_epoch"],
            authority_revision=payload["authority_revision"],
            expires_at_unix=payload["expires_at_unix"],
        )
