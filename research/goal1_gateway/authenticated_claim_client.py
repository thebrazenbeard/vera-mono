"""Gateway-owned HTTPS/mTLS transport for evaluator-pulled atomic claims.

Only the separately administered evaluator endpoint owns RESERVED -> CLAIMED.
This client never generates bearer tickets, self-issues claims, verifies evaluator
custody, grants learner Ollama access, or signs terminal outcomes. TLS trust
materials and the process privilege boundary must be supplied by the host.
"""
from __future__ import annotations

import json
from pathlib import Path
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)

_MAX_RESPONSE = 4096
_MAX_REQUEST = 2048
_BINDING_FIELDS = frozenset({
    "reservation_id", "run_id", "arm", "challenge_id",
    "challenge_view_digest", "model_prompt_sha256",
    "model_identity", "model_artifact_sha256",
})
_CLAIM_PATH = "/v1/reservations/claim"


class ClaimTransportHold(RuntimeError):
    """Untrusted or ambiguous claim result. NEVER re-issue automatically."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClaimTransportHold("reservation claim redirect denied")


def _claim_url(url: str) -> str:
    if type(url) is not str:
        raise ValueError("claim endpoint URL required")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid claim endpoint URL") from exc
    if (parts.scheme != "https" or not parts.hostname or
            parts.username is not None or parts.password is not None or
            parts.path != _CLAIM_PATH or parts.query or parts.fragment or
            parts.netloc.endswith(":") or (port is not None and port < 1)):
        raise ValueError("exact HTTPS reservation claim URL required")
    return url


class AuthenticatedReservationClaimClient:
    """One outbound, no-retry mTLS call from the gateway security principal.

    Certificate-based server hostname verification and client authentication
    are real TLS checks; independent issuer/operator custody cannot be inferred
    from passing a path to a CA/cert/key. The caller must pin those materials
    outside learner-writable space and ensure that only the gateway can access
    them. Malaphor #87's claim_dispatch_authorization validates the EXACT
    returned claim binding; this adapter only establishes the TLS channel.
    """

    def __init__(self, *, endpoint_url: str, ca_bundle: str | Path,
                 client_certificate: str | Path, client_private_key: str | Path,
                 timeout_seconds: float = 5.0) -> None:
        self.endpoint_url = _claim_url(endpoint_url)
        if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 10:
            raise ValueError("bounded TLS claim timeout required")
        self.timeout_seconds = timeout_seconds
        try:
            context = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH,
                cafile=str(ca_bundle),
            )
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_cert_chain(
                certfile=str(client_certificate),
                keyfile=str(client_private_key),
            )
        except (OSError, ValueError, ssl.SSLError) as exc:
            raise ClaimTransportHold("gateway mTLS trust materials unavailable") from exc
        self._opener = build_opener(
            ProxyHandler({}), HTTPSHandler(context=context), _NoRedirect()
        )

    def claim_reservation(self, *, reservation: dict[str, str],
                          gateway_id: str, invocation_id: str) -> dict[str, Any]:
        # This is only wire framing. The separately imported exact #87 helper
        # must enforce binding equality and atomic remote claim semantics.
        if (type(reservation) is not dict or
                frozenset(reservation) != _BINDING_FIELDS or
                any(type(v) is not str or not v for v in reservation.values()) or
                type(gateway_id) is not str or not gateway_id or
                type(invocation_id) is not str or not invocation_id):
            raise ValueError("reservation claim request invalid")
        body = json.dumps({
            "reservation": reservation,
            "gateway_id": gateway_id,
            "invocation_id": invocation_id,
        }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > _MAX_REQUEST:
            raise ValueError("claim request exceeds fixed envelope cap")
        request = Request(self.endpoint_url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise ClaimTransportHold("evaluator claim HTTP status not 200")
                raw = response.read(_MAX_RESPONSE + 1)
                if len(raw) > _MAX_RESPONSE:
                    raise ClaimTransportHold("evaluator claim response oversized")
        except ClaimTransportHold:
            raise
        except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
            raise ClaimTransportHold("evaluator claim unavailable or ambiguous") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ClaimTransportHold("evaluator claim response invalid JSON") from exc
        if type(result) is not dict:
            raise ClaimTransportHold("evaluator claim response must be an object")
        return result
