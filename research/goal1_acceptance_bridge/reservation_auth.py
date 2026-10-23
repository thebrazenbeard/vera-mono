"""Opt-in verification-only dispatch authorization for Goal 1 research.

This proposal consumes a *separately signed* authorization and never holds
a private key. #87 does NOT currently issue this ticket, and this source is
not an installed or enforced selected QVR gateway. Direct local model calls
can bypass this wrapper. No independent execution evidence results from it.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore

_SCHEMA = "GOAL1_DISPATCH_AUTHORIZATION_CANDIDATE_V1"
_FIELDS = frozenset({
    "schema", "audience", "invocation_id", "route_ref", "max_tokens",
    "issued_at_epoch", "expires_at_epoch", "reservation", "signature_b64",
})
_RESERVATION_FIELDS = frozenset({
    "reservation_id", "run_id", "arm", "challenge_id",
    "challenge_view_digest", "model_prompt_sha256", "model_identity",
    "model_artifact_sha256",
})
_MAX_TTL_SECONDS = 120


def canonical_authorization_bytes(ticket: dict) -> bytes:
    """Deterministic signature subject; excludes detached signature only."""
    if type(ticket) is not dict:
        raise ValueError("authorization must be a plain object")
    try:
        return json.dumps(
            {key: value for key, value in ticket.items() if key != "signature_b64"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError("invalid canonical authorization") from exc


class AuthorizedLocalDispatcher:
    """Verify a pinned signer/audience and call local attempt fence exactly once.

    Source-level candidate only. An untrusted client that can invoke Ollama or
    LocalAttemptStore directly can bypass this class entirely. Network endpoint
    isolation, key custody, and selected-route deployment are NOT included.
    """

    def __init__(
        self, *, store: LocalAttemptStore, trusted_issuer_public_key: bytes,
        expected_audience: str, selected_model: str,
        expected_model_artifact_sha256: str, reported_registry_digest: str,
    ):
        if not isinstance(store, LocalAttemptStore):
            raise TypeError("LocalAttemptStore required")
        try:
            self._issuer = Ed25519PublicKey.from_public_bytes(
                trusted_issuer_public_key,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid pinned issuer public key") from exc
        if (type(expected_audience) is not str or not expected_audience
                or type(selected_model) is not str or not selected_model):
            raise ValueError("pinned audience and model required")
        for name, val in (
            ("expected_model_artifact_sha256", expected_model_artifact_sha256),
            ("reported_registry_digest", reported_registry_digest),
        ):
            if (type(val) is not str or len(val) != 64
                    or any(c not in "0123456789abcdef" for c in val)):
                raise ValueError("invalid " + name)
        self._store = store
        self._audience = expected_audience
        self._model = selected_model
        self._artifact = expected_model_artifact_sha256
        self._registry = reported_registry_digest

    def dispatch(
        self, *, ticket: dict, challenge_view: dict, prompt: str,
        transport: object, permit: object,
    ):
        if type(ticket) is not dict or frozenset(ticket) != _FIELDS:
            raise ValueError("unsigned or malformed authorization")
        if ticket["schema"] != _SCHEMA or ticket["audience"] != self._audience:
            raise ValueError("wrong authorization schema or audience")
        if (type(ticket["reservation"]) is not dict
                or frozenset(ticket["reservation"]) != _RESERVATION_FIELDS):
            raise ValueError("authorization reservation fields invalid")
        if type(ticket["max_tokens"]) is not int or not 1 <= ticket["max_tokens"] <= 128:
            raise ValueError("authorization token limit invalid")
        issued = ticket["issued_at_epoch"]
        expires = ticket["expires_at_epoch"]
        if type(issued) is not int or type(expires) is not int:
            raise ValueError("authorization validity epoch invalid")
        now = int(time.time())
        if (issued > now or expires <= now
                or expires <= issued or expires - issued > _MAX_TTL_SECONDS
                or now - issued > _MAX_TTL_SECONDS):
            raise ValueError("authorization expired, future-dated, or too long-lived")
        if not isinstance(ticket["signature_b64"], str):
            raise ValueError("authorization signature missing")
        try:
            sig = base64.b64decode(ticket["signature_b64"], validate=True)
            if len(sig) != 64:
                raise ValueError("invalid signature length")
            self._issuer.verify(sig, canonical_authorization_bytes(ticket))
        except (InvalidSignature, ValueError, binascii.Error) as exc:
            raise ValueError("untrusted dispatch authorization signature") from exc
        # Signature verified only against the configured public key. The
        # signed reservation must also match the chosen local model and
        # exact prompt and public challenge before creating local state.
        return self._store.execute_controller_reserved(
            reservation=ticket["reservation"],
            challenge_view=challenge_view,
            invocation_id=ticket["invocation_id"],
            route_ref=ticket["route_ref"],
            selected_model=self._model,
            expected_model_artifact_sha256=self._artifact,
            reported_model_digest=self._registry,
            prompt=prompt, max_tokens=ticket["max_tokens"],
            transport=transport, permit=permit,
        )
