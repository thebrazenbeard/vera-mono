"""Fail-closed WebAuthn assertion verification for a *future* Vera reviewer broker.

This is a public, source-only verifier. It neither enrolls a credential nor
opens Windows Hello, and is NOT connected to Vera's Ed25519-only journal.

The proposed trusted journal seam must accept the raw assertion and verify it
itself against a pinned enrollment; a caller-created receipt is not authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import base64
import hmac
import json
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


_DOMAIN = b"vera.synthetic-review.webauthn-es256.v1\0"
_UP = 0x01
_UV = 0x04
_AT = 0x40
_ED = 0x80


class ReviewAssertionRejected(ValueError):
    """The assertion did not cryptographically authorize this exact review."""


@dataclass(frozen=True, slots=True)
class WebAuthnAssertion:
    """Untrusted raw values copied from a Windows WebAuthn assertion."""

    credential_id: bytes
    client_data_json: bytes
    authenticator_data: bytes
    signature_der: bytes


@dataclass(frozen=True, slots=True)
class VerifiedWebAuthnAction:
    """Ephemeral evidence, not an independently trusted authorization token.

    The journal must re-verify the embedded assertion against an independently
    pinned credential before applying the matching action; applications must
    never authorize based on the mere existence of this Python object.
    """

    signed_review_sha256: str
    pinned_credential_id: bytes
    authenticator_counter: int
    assertion: WebAuthnAssertion


def review_challenge(review_signable_bytes: bytes) -> bytes:
    """Bind a WebAuthn challenge to the complete action-bound ReviewDecision."""
    if type(review_signable_bytes) is not bytes or not 1 <= len(review_signable_bytes) <= 4096:
        raise ReviewAssertionRejected("review bytes must be bounded and nonempty")
    return sha256(_DOMAIN + review_signable_bytes).digest()


def _strict_json_object(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 1 <= len(raw) <= 2048:
        raise ReviewAssertionRejected("clientDataJSON length invalid")

    def pairs_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewAssertionRejected("duplicate clientDataJSON key")
            result[key] = value
        return result

    def reject_non_json_constant(value: str):
        raise ReviewAssertionRejected("non-JSON numeric constant prohibited")

    try:
        obj = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_no_duplicates,
            parse_constant=reject_non_json_constant,
        )
    except ReviewAssertionRejected:
        raise
    except (ValueError, UnicodeError) as exc:
        raise ReviewAssertionRejected("invalid clientDataJSON") from exc
    if type(obj) is not dict:
        raise ReviewAssertionRejected("clientDataJSON must be an object")
    return obj


class WebAuthnReviewVerifier:
    """Verify a P-256/ES256 user-verified assertion against a pinned credential.

    Registration/attestation and storage of the registered credential/public key
    are deliberately outside this module. Never obtain them from writable model
    output, a journal event, or user-supplied request fields at verify time.
    """

    def __init__(
        self,
        *,
        rp_id: str,
        expected_origin: str,
        credential_id: bytes,
        public_key_pem: bytes,
    ) -> None:
        if (
            type(rp_id) is not str or not rp_id or rp_id != rp_id.lower()
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in rp_id)
            or rp_id.startswith(".") or rp_id.endswith(".")
        ):
            raise ReviewAssertionRejected("invalid relying-party ID")
        parsed = urlsplit(expected_origin)
        if (
            parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or not (
                parsed.hostname == rp_id
                or parsed.hostname.endswith("." + rp_id)
            )
        ):
            raise ReviewAssertionRejected("origin must be a matching HTTPS origin")
        if type(credential_id) is not bytes or not 1 <= len(credential_id) <= 1024:
            raise ReviewAssertionRejected("pinned credential ID invalid")
        try:
            key = serialization.load_pem_public_key(public_key_pem)
        except (ValueError, TypeError) as exc:
            raise ReviewAssertionRejected("pinned public key invalid") from exc
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ReviewAssertionRejected("only pinned P-256/ES256 keys are supported")
        self.rp_id = rp_id
        self.expected_origin = expected_origin
        self.credential_id = credential_id
        self._key = key

    def verify(
        self, review_signable_bytes: bytes, assertion: WebAuthnAssertion,
    ) -> VerifiedWebAuthnAction:
        expected_challenge = review_challenge(review_signable_bytes)
        if type(assertion) is not WebAuthnAssertion:
            raise ReviewAssertionRejected("raw WebAuthn assertion required")
        if not hmac.compare_digest(assertion.credential_id, self.credential_id):
            raise ReviewAssertionRejected("credential ID mismatch")
        client = _strict_json_object(assertion.client_data_json)
        if client.get("type") != "webauthn.get" or client.get("origin") != self.expected_origin:
            raise ReviewAssertionRejected("client assertion type/origin mismatch")
        if client.get("crossOrigin", False) is not False or "topOrigin" in client:
            raise ReviewAssertionRejected("cross-origin assertion prohibited")
        claimed_challenge = client.get("challenge")
        canonical_challenge = base64.urlsafe_b64encode(expected_challenge).rstrip(b"=").decode("ascii")
        if type(claimed_challenge) is not str or not hmac.compare_digest(
            claimed_challenge, canonical_challenge
        ):
            raise ReviewAssertionRejected("review action/challenge mismatch")
        auth = assertion.authenticator_data
        # Only the 37-byte unextended assertion format is supported in v1.
        if type(auth) is not bytes or len(auth) != 37:
            raise ReviewAssertionRejected("authenticator data length invalid")
        if not hmac.compare_digest(auth[:32], sha256(self.rp_id.encode("utf-8")).digest()):
            raise ReviewAssertionRejected("relying-party hash mismatch")
        flags = auth[32]
        if (flags & (_UP | _UV)) != (_UP | _UV) or flags & (_AT | _ED):
            raise ReviewAssertionRejected("user presence/verification missing or extensions unsupported")
        signature = assertion.signature_der
        if type(signature) is not bytes or not 1 <= len(signature) <= 160:
            raise ReviewAssertionRejected("signature invalid")
        signed_bytes = auth + sha256(assertion.client_data_json).digest()
        try:
            self._key.verify(signature, signed_bytes, ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError) as exc:
            raise ReviewAssertionRejected("signature verification failed") from exc
        return VerifiedWebAuthnAction(
            signed_review_sha256=sha256(review_signable_bytes).hexdigest(),
            pinned_credential_id=self.credential_id,
            authenticator_counter=int.from_bytes(auth[33:37], "big"),
            assertion=assertion,
        )
