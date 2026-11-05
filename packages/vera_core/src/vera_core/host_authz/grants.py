"""Strict host-pinned, externally issued grant verification.

The verifier intentionally has no mint/sign method. A signature proves an
issuer assertion, not participant consent or exclusive host key custody.
Those facts must be qualified independently before enabling effects.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, fields
import json
import re
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


SIGNED_GRANT_SCHEMA = "HOST_AUTHZ_SIGNED_GRANT_V1"
SIGNATURE_CONTEXT = b"VERA_HOST_AUTHZ_GRANT_V1\x00"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_INT = (1 << 63) - 1


class GrantVerificationError(ValueError):
    """A signed grant did not pass the host verifier."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GrantVerificationError("invalid canonical grant JSON") from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GrantVerificationError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise GrantVerificationError("non-finite JSON constant")


@dataclass(frozen=True, slots=True)
class ApprovedGrant:
    grant_id: str
    issuer_id: str
    host_id: str
    epoch: int
    peer_key: str
    model_id: str
    adapter_id: str
    runtime_id: str
    subject_id: str
    participant_id: str
    purpose: str
    provider_id: str
    provider_instance_id: str
    operation: str
    request_digest: str
    not_before: int
    expires_at: int

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name in ("epoch", "not_before", "expires_at"):
                if type(value) is not int or value < 0 or value > _MAX_INT:
                    raise GrantVerificationError(f"invalid {f.name}")
                continue
            if type(value) is not str or not value or any(ord(c) < 32 for c in value):
                raise GrantVerificationError(f"invalid {f.name}")
        if self.epoch == 0:
            raise GrantVerificationError("epoch must be positive")
        if self.expires_at <= self.not_before:
            raise GrantVerificationError("grant expiry must be later than start")
        if _SHA256.fullmatch(self.request_digest) is None:
            raise GrantVerificationError("request_digest must be lowercase SHA-256")

    def canonical_body(self) -> dict[str, str | int]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True, slots=True, init=False)
class SignedGrantVerifier:
    """Host-supplied pinned issuer trust root; no signing private key here.

    `trusted_clock` must be configured by the host process, never selected or
    invoked by an untrusted adapter. An OS clock is not antirollback evidence.
    """

    _key: Ed25519PublicKey
    _issuer_id: str
    _host_id: str
    _epoch: int
    _clock: Callable[[], int]

    def __init__(
        self,
        issuer_public_key: bytes,
        *,
        issuer_id: str,
        host_id: str,
        epoch: int,
        trusted_clock: Callable[[], int],
    ) -> None:
        if type(issuer_public_key) is not bytes or len(issuer_public_key) != 32:
            raise GrantVerificationError("issuer key must be 32 raw Ed25519 bytes")
        if type(issuer_id) is not str or not issuer_id:
            raise GrantVerificationError("invalid pinned issuer")
        if type(host_id) is not str or not host_id:
            raise GrantVerificationError("invalid pinned host")
        if type(epoch) is not int or not 0 < epoch <= _MAX_INT:
            raise GrantVerificationError("invalid pinned epoch")
        if not callable(trusted_clock):
            raise GrantVerificationError("trusted clock is required")
        object.__setattr__(self, "_key", Ed25519PublicKey.from_public_bytes(issuer_public_key))
        object.__setattr__(self, "_issuer_id", issuer_id)
        object.__setattr__(self, "_host_id", host_id)
        object.__setattr__(self, "_epoch", epoch)
        object.__setattr__(self, "_clock", trusted_clock)

    @property
    def issuer_id(self) -> str:
        return self._issuer_id

    @property
    def host_id(self) -> str:
        return self._host_id

    @property
    def epoch(self) -> int:
        return self._epoch

    def verify(self, signed_envelope: bytes) -> ApprovedGrant:
        if type(signed_envelope) is not bytes:
            raise GrantVerificationError("signed envelope must be bytes")
        try:
            envelope = json.loads(
                signed_envelope.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_constant,
            )
        except (ValueError, UnicodeError) as exc:
            raise GrantVerificationError("malformed signed envelope") from exc
        if type(envelope) is not dict or set(envelope) != {"schema", "grant", "signature"}:
            raise GrantVerificationError("unexpected signed envelope shape")
        if signed_envelope != _canonical(envelope):
            raise GrantVerificationError("noncanonical signed envelope")
        if envelope["schema"] != SIGNED_GRANT_SCHEMA:
            raise GrantVerificationError("unknown signed grant schema")
        body = envelope["grant"]
        if type(body) is not dict or set(body) != {f.name for f in fields(ApprovedGrant)}:
            raise GrantVerificationError("unexpected grant fields")
        grant = ApprovedGrant(**body)
        if (grant.issuer_id, grant.host_id, grant.epoch) != (
            self._issuer_id, self._host_id, self._epoch
        ):
            raise GrantVerificationError("grant issued for different host authority")

        signature_text = envelope["signature"]
        if type(signature_text) is not str:
            raise GrantVerificationError("invalid signature encoding")
        try:
            signature_bytes = base64.urlsafe_b64decode(
                signature_text + "=" * ((-len(signature_text)) % 4)
            )
        except (ValueError, binascii.Error) as exc:
            raise GrantVerificationError("invalid signature encoding") from exc
        if (
            len(signature_bytes) != 64
            or base64.urlsafe_b64encode(signature_bytes).rstrip(b"=").decode("ascii")
            != signature_text
        ):
            raise GrantVerificationError("noncanonical Ed25519 signature")
        try:
            self._key.verify(signature_bytes, SIGNATURE_CONTEXT + _canonical(body))
        except InvalidSignature as exc:
            raise GrantVerificationError("grant signature verification failed") from exc

        now = self._clock()
        if type(now) is not int or now < 0 or now > _MAX_INT:
            raise GrantVerificationError("invalid trusted host clock")
        if not grant.not_before <= now < grant.expires_at:
            raise GrantVerificationError("grant not currently valid")
        return grant
