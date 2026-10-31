"""Authenticated external monotonic-witness client for host authorization.

The client is a protocol adapter, NOT a substitute for an independently
protected, single-leader witness service. The signed response binds every
event and a fresh challenge so that stale or replayed approvals cannot make
the local ClaimLedger accept a grant. Only a dedicated privileged host process
may construct it and own its trust anchor and mutually authenticated transport.

The external service MUST durably serialize claims and revocations for a host
authority/epoch, reject grant replay even across restored local claim DBs,
provide an independently managed monotonic high-water/leader fence, and not
allow its signing key and state to be cloned together. A test fake returning
signed approvals cannot qualify those physical properties.
"""

from __future__ import annotations

import base64
import binascii
from hashlib import sha256
import json
import re
import secrets
import ssl
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


REQUEST_SCHEMA = "VERA_HOST_AUTHZ_WITNESS_EVENT_V1"
RESPONSE_SCHEMA = "VERA_HOST_AUTHZ_WITNESS_RESPONSE_V1"
RESPONSE_SIGNATURE_CONTEXT = b"VERA_HOST_AUTHZ_WITNESS_RESPONSE_V1\x00"
MAX_WITNESS_RESPONSE_BYTES = 16_384
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_BODY_FIELDS = frozenset(
    {"schema", "witness_id", "leader_id", "leader_epoch", "authority_id",
     "epoch", "sequence", "nonce", "event_digest", "decision"}
)


class ExternalWitnessDenied(PermissionError):
    """The external witness did not provide a valid, current approval."""


class ExternalWitnessTransport(Protocol):
    def send(self, event_bytes: bytes) -> bytes:
        """Send canonical event to a separate, authenticated witness service."""


def _id(value: Any, name: str) -> str:
    if (
        type(value) is not str or not value or len(value) > 256
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
    ):
        raise ExternalWitnessDenied(f"invalid {name}")
    return value


def _positive(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ExternalWitnessDenied(f"invalid {name}")
    return value


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExternalWitnessDenied("invalid canonical witness data") from exc


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExternalWitnessDenied("duplicate witness response key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> Any:
    raise ExternalWitnessDenied("nonfinite witness response")


def _exact_json(blob: bytes) -> dict[str, Any]:
    if type(blob) is not bytes or not blob or len(blob) > MAX_WITNESS_RESPONSE_BYTES:
        raise ExternalWitnessDenied("invalid witness response size")
    try:
        raw = json.loads(
            blob.decode("utf-8", errors="strict"), object_pairs_hook=_unique,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ExternalWitnessDenied("invalid witness response JSON") from exc
    if type(raw) is not dict or _canonical(raw) != blob:
        raise ExternalWitnessDenied("noncanonical witness response")
    return raw


class ExternalWitnessClient(tuple):
    """Mandatory signed, challenge-bound reply for a local ClaimLedger event.

    True is returned only for an exact signed APPROVED decision. A signed
    DENIED returns False, and an absent, altered, ambiguous, replayed or stale
    result raises ExternalWitnessDenied. The local ledger then fails closed.
    """

    # Tuple storage has no writable __dict__ and cannot be rebound even by
    # object.__setattr__. The bound external transport can still retain mutable
    # collaborators; it MUST live only inside the privileged host process.
    __slots__ = ()

    def __new__(
        cls,
        transport: ExternalWitnessTransport,
        *,
        witness_id: str,
        leader_id: str,
        leader_epoch: int,
        response_public_key: bytes,
    ) -> "ExternalWitnessClient":
        _id(witness_id, "witness_id")
        _id(leader_id, "leader_id")
        _positive(leader_epoch, "leader_epoch")
        if type(response_public_key) is not bytes or len(response_public_key) != 32:
            raise ValueError("host-pinned Ed25519 witness public key required")
        send = getattr(transport, "send", None)
        if not callable(send):
            raise ValueError("external witness transport must have send")
        return tuple.__new__(
            cls,
            (send, witness_id, leader_id, leader_epoch,
             Ed25519PublicKey.from_public_bytes(response_public_key)),
        )

    @property
    def _send(self):
        return self[0]

    @property
    def _witness_id(self) -> str:
        return self[1]

    @property
    def _leader_id(self) -> str:
        return self[2]

    @property
    def _leader_epoch(self) -> int:
        return self[3]

    @property
    def _public_key(self) -> Ed25519PublicKey:
        return self[4]

    def attest_claim(
        self, *, authority_id: str, epoch: int, sequence: int,
        grant_id: str, claim_digest: str,
    ) -> bool:
        if type(claim_digest) is not str or _DIGEST.fullmatch(claim_digest) is None:
            raise ExternalWitnessDenied("invalid claim digest")
        return self._attest(
            "CLAIM", authority_id, epoch, sequence, grant_id, claim_digest
        )

    def attest_revocation(
        self, *, authority_id: str, epoch: int, sequence: int, grant_id: str
    ) -> bool:
        return self._attest("REVOKE", authority_id, epoch, sequence, grant_id, None)

    def _attest(
        self, kind: str, authority_id: str, epoch: int, sequence: int,
        grant_id: str, claim_digest: str | None,
    ) -> bool:
        _id(authority_id, "authority_id")
        _id(grant_id, "grant_id")
        _positive(epoch, "epoch")
        _positive(sequence, "sequence")
        # Fresh per-request anti-replay challenge; this must never originate
        # from a model or be persisted with the local claim DB.
        nonce = secrets.token_hex(32)
        event = {
            "schema": REQUEST_SCHEMA,
            "witness_id": self._witness_id,
            "leader_epoch": self._leader_epoch,
            "authority_id": authority_id,
            "epoch": epoch,
            "sequence": sequence,
            "grant_id": grant_id,
            "kind": kind,
            "claim_digest": claim_digest,
            "nonce": nonce,
        }
        event_bytes = _canonical(event)
        try:
            response_bytes = self._send(event_bytes)
        except Exception as exc:
            raise ExternalWitnessDenied("external witness unavailable") from exc
        envelope = _exact_json(response_bytes)
        if envelope.keys() != {"body", "signature"}:
            raise ExternalWitnessDenied("invalid signed witness envelope")
        body = envelope["body"]
        signature = envelope["signature"]
        if type(body) is not dict or body.keys() != _BODY_FIELDS:
            raise ExternalWitnessDenied("invalid signed witness response body")
        if type(signature) is not str or len(signature) != 86:
            raise ExternalWitnessDenied("invalid witness signature encoding")
        try:
            raw_sig = base64.urlsafe_b64decode(signature + "==")
        except (binascii.Error, ValueError) as exc:
            raise ExternalWitnessDenied("invalid witness signature") from exc
        if (
            len(raw_sig) != 64
            or base64.urlsafe_b64encode(raw_sig).rstrip(b"=").decode() != signature
        ):
            raise ExternalWitnessDenied("noncanonical witness signature")
        try:
            self._public_key.verify(
                raw_sig, RESPONSE_SIGNATURE_CONTEXT + _canonical(body)
            )
        except Exception as exc:
            raise ExternalWitnessDenied("invalid witness signature") from exc
        expected = {
            "schema": RESPONSE_SCHEMA,
            "witness_id": self._witness_id,
            "leader_id": self._leader_id,
            "leader_epoch": self._leader_epoch,
            "authority_id": authority_id,
            "epoch": epoch,
            "sequence": sequence,
            "nonce": nonce,
            "event_digest": sha256(event_bytes).hexdigest(),
        }
        if any(type(body.get(k)) is not type(v) or body.get(k) != v for k, v in expected.items()):
            raise ExternalWitnessDenied("response belongs to another witness event")
        if body["decision"] not in ("APPROVED", "DENIED") or type(body["decision"]) is not str:
            raise ExternalWitnessDenied("invalid witness decision")
        return body["decision"] == "APPROVED"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class HTTPSWitnessTransport(tuple):
    """Host-configured HTTPS+mTLS transport to a separately owned witness.

    The caller must load CA roots and a client certificate/private key into the
    SSLContext from OS-owned storage and qualify key/cert custody. Python's
    SSLContext cannot attest that the client credential really is hardware- or
    OS-isolated; this constructor deliberately makes no such claim.
    """

    __slots__ = ()

    def __new__(cls, url: str, tls_context: ssl.SSLContext,
                *, timeout_seconds: float = 5.0) -> "HTTPSWitnessTransport":
        if type(url) is not str:
            raise ValueError("witness endpoint must be exact HTTPS URL")
        parts = urlsplit(url)
        if (
            parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment or not parts.path
        ):
            raise ValueError("witness endpoint must be fixed HTTPS URL without userinfo/redirect")
        if type(tls_context) is not ssl.SSLContext:
            raise ValueError("host TLS context required")
        if (
            not tls_context.check_hostname
            or tls_context.verify_mode != ssl.CERT_REQUIRED
            or tls_context.minimum_version < ssl.TLSVersion.TLSv1_2
        ):
            raise ValueError("TLS hostname and CA verification are mandatory")
        if type(timeout_seconds) not in (int, float) or not (0 < timeout_seconds <= 30):
            raise ValueError("bounded witness timeout required")
        return tuple.__new__(cls, (url, tls_context, float(timeout_seconds)))

    @property
    def _url(self) -> str:
        return self[0]

    @property
    def _context(self) -> ssl.SSLContext:
        return self[1]

    @property
    def _timeout(self) -> float:
        return self[2]

    def send(self, event_bytes: bytes) -> bytes:
        if type(event_bytes) is not bytes or not event_bytes or len(event_bytes) > 16_384:
            raise ExternalWitnessDenied("invalid outbound witness event")
        opener = build_opener(
            HTTPSHandler(context=self._context), _NoRedirect(), ProxyHandler({})
        )
        request = Request(
            self._url, data=event_bytes, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != self._url:
                    raise ExternalWitnessDenied("witness endpoint status/identity mismatch")
                blob = response.read(MAX_WITNESS_RESPONSE_BYTES + 1)
        except ExternalWitnessDenied:
            raise
        except Exception as exc:
            raise ExternalWitnessDenied("witness HTTPS transport unavailable") from exc
        if len(blob) > MAX_WITNESS_RESPONSE_BYTES:
            raise ExternalWitnessDenied("oversized witness reply")
        return blob
