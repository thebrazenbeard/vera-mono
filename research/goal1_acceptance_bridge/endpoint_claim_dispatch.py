"""Research adapter for Malaphor #87's gateway-pulled reservation claim.

The claim contract is supplied by the exact evaluator implementation at the
call site. This module does not implement remote authentication or claim-state
authority, provision keys, expose ingress, or activate QVR. A same-process fake
client/callable or raw transport bypass can still cause unauthorized inference.
"""
from __future__ import annotations

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore


class _ClaimBeforeModel:
    def __init__(self, *, dispatcher, reservation: dict, invocation_id: str,
                 underlying: object):
        self.dispatcher = dispatcher
        self.reservation = reservation
        self.invocation_id = invocation_id
        self.underlying = underlying

    def generate(self, prompt: str, *, permit: object, max_tokens: int):
        # Called only from LocalAttemptStore.execute_controller_reserved AFTER
        # its durable RESERVED commit and all local binding checks.
        d = self.dispatcher
        result = d._claim_authorization(
            d._client, reservation=dict(self.reservation),
            gateway_id=d._gateway_id, invocation_id=self.invocation_id,
        )
        # The #87 helper validates every binding and exact schema. These two
        # checks protect against accidental malformed injected helpers, but
        # cannot authenticate a malicious same-process replacement.
        if type(result) is not dict or result.get("status") != "CLAIMED":
            raise ValueError("authenticated endpoint did not grant claim")
        claim_id = result.get("claim_id")
        if type(claim_id) is not str or not claim_id:
            raise ValueError("claim identity missing")
        d._store.record_claim(self.invocation_id, claim_id)
        return self.underlying.generate(prompt, permit=permit,
                                        max_tokens=max_tokens)


class EndpointClaimedLocalDispatcher:
    """Source-level glue around actual #87 claim_dispatch_authorization.

    The real callable must be imported from #87's exact source by the host
    composition root; a trusted authenticated client is a separate dependency.
    This class is not itself a trust boundary or endpoint implementation.
    """

    def __init__(
        self, *, store: LocalAttemptStore, gateway_id: str,
        selected_model: str, reported_registry_digest: str,
        expected_model_artifact_sha256: str,
        claim_authorization: object, reservation_client: object,
    ):
        if not isinstance(store, LocalAttemptStore):
            raise ValueError("LocalAttemptStore required")
        if not callable(claim_authorization):
            raise ValueError("claim authorization callable required")
        if not callable(getattr(reservation_client, "claim_reservation", None)):
            raise ValueError("authenticated reservation client required")
        if not gateway_id or type(gateway_id) is not str:
            raise ValueError("gateway id required")
        self._store = store
        self._gateway_id = gateway_id
        self._model = selected_model
        self._registry = reported_registry_digest
        self._artifact = expected_model_artifact_sha256
        self._claim_authorization = claim_authorization
        self._client = reservation_client

    def dispatch(
        self, *, reservation: dict, challenge_view: dict,
        invocation_id: str, route_ref: str, prompt: str, max_tokens: int,
        transport: object, permit: object,
    ):
        # Reuse all strict #87 envelope-shape and public challenge / selected
        # model consistency checks before any network claim or local dispatch.
        fence = _ClaimBeforeModel(
            dispatcher=self, reservation=reservation,
            invocation_id=invocation_id, underlying=transport,
        )
        return self._store.execute_controller_reserved(
            reservation=reservation, challenge_view=challenge_view,
            invocation_id=invocation_id, route_ref=route_ref,
            selected_model=self._model,
            expected_model_artifact_sha256=self._artifact,
            reported_model_digest=self._registry,
            prompt=prompt, max_tokens=max_tokens, transport=fence,
            permit=permit,
        )
