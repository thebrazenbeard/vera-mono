"""Reference contract for gateway-pulled, authenticated reservation claims.

This is a source-level client contract, not a network endpoint or authentication
implementation. Production use requires the selected gateway to call a separately
administered endpoint over authenticated transport and the endpoint to atomically
claim the durable reservation before model dispatch.
"""
from __future__ import annotations

from typing import Protocol

_BINDING_FIELDS = (
    "reservation_id", "run_id", "arm", "challenge_id",
    "challenge_view_digest", "model_prompt_sha256",
    "model_identity", "model_artifact_sha256",
)
_RESPONSE_FIELDS = frozenset((*_BINDING_FIELDS, "status", "gateway_id", "invocation_id", "claim_id"))


class AuthenticatedReservationStatusClient(Protocol):
    """Transport adapter with independently verified server and caller identity.

    Authentication MUST be enforced by the transport/endpoint, not a boolean
    supplied by this client. The endpoint atomically changes RESERVED to CLAIMED
    and binds one gateway + invocation ID. It never returns private truth.
    """
    def claim_reservation(self, *, reservation: dict[str, str],
                          gateway_id: str, invocation_id: str) -> dict[str, str]:
        ...


def claim_dispatch_authorization(
    client: AuthenticatedReservationStatusClient, *,
    reservation: dict[str, str], gateway_id: str, invocation_id: str,
) -> dict[str, str]:
    """Ask the trusted endpoint to claim a reservation; reject any mismatch.

    No signed bearer ticket is minted or accepted. The endpoint response is
    trusted only when the injected transport independently authenticates it.
    This helper cannot prevent direct transport bypass or same-process compromise.
    """
    if type(reservation) is not dict or frozenset(reservation) != frozenset(_BINDING_FIELDS):
        raise ValueError("reservation binding fields invalid")
    if any(type(reservation[k]) is not str or not reservation[k] for k in _BINDING_FIELDS):
        raise ValueError("reservation binding values must be non-empty strings")
    for name, value in (("gateway_id", gateway_id), ("invocation_id", invocation_id)):
        if type(value) is not str or not value:
            raise ValueError(f"{name} required")
    response = client.claim_reservation(
        reservation=dict(reservation), gateway_id=gateway_id,
        invocation_id=invocation_id,
    )
    if type(response) is not dict or frozenset(response) != _RESPONSE_FIELDS:
        raise ValueError("reservation endpoint response schema invalid")
    if response["status"] != "CLAIMED":
        raise ValueError("reservation not claimable")
    expected = {**reservation, "gateway_id": gateway_id, "invocation_id": invocation_id}
    if any(response.get(k) != v for k, v in expected.items()):
        raise ValueError("reservation endpoint binding mismatch")
    if type(response["claim_id"]) is not str or not response["claim_id"]:
        raise ValueError("reservation endpoint claim identity missing")
    return dict(response)
