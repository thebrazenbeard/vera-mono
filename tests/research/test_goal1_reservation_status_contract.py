import pytest

from research.goal1_evaluator.reservation_status_contract import claim_dispatch_authorization

RESERVATION = {
    "reservation_id": "res-1", "run_id": "run-1", "arm": "LEARNED",
    "challenge_id": "case-1", "challenge_view_digest": "a" * 64,
    "model_prompt_sha256": "b" * 64, "model_identity": "model-v1",
    "model_artifact_sha256": "c" * 64,
}


class Endpoint:
    def __init__(self, mutate=None, status="CLAIMED"):
        self.calls = []
        self.mutate = mutate
        self.status = status

    def claim_reservation(self, *, reservation, gateway_id, invocation_id):
        self.calls.append((reservation, gateway_id, invocation_id))
        result = {**reservation, "status": self.status, "gateway_id": gateway_id,
                  "invocation_id": invocation_id, "claim_id": "claim-1"}
        if self.mutate:
            self.mutate(result)
        return result


def test_claim_is_pulled_for_specific_gateway_and_invocation():
    endpoint = Endpoint()
    result = claim_dispatch_authorization(endpoint, reservation=RESERVATION,
        gateway_id="qvr-gateway-1", invocation_id="inv-1")
    assert result["status"] == "CLAIMED"
    assert endpoint.calls == [(RESERVATION, "qvr-gateway-1", "inv-1")]


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(gateway_id="attacker-gateway"),
    lambda r: r.update(invocation_id="other-invocation"),
    lambda r: r.update(reservation_id="other-reservation"),
    lambda r: r.update(model_artifact_sha256="d" * 64),
    lambda r: r.update(status="RESERVED"),
    lambda r: r.update(claim_id=""),
    lambda r: r.update(extra="unexpected"),
])
def test_mismatched_or_malformed_endpoint_claim_fails_closed(mutation):
    with pytest.raises(ValueError):
        claim_dispatch_authorization(Endpoint(mutate=mutation), reservation=RESERVATION,
            gateway_id="qvr-gateway-1", invocation_id="inv-1")


def test_unclaimed_reservation_fails_closed():
    with pytest.raises(ValueError, match="not claimable"):
        claim_dispatch_authorization(Endpoint(status="UNKNOWN"), reservation=RESERVATION,
            gateway_id="qvr-gateway-1", invocation_id="inv-1")


def test_invalid_request_does_not_call_endpoint():
    endpoint = Endpoint()
    with pytest.raises(ValueError):
        claim_dispatch_authorization(endpoint, reservation={**RESERVATION, "secret": "label"},
            gateway_id="qvr-gateway-1", invocation_id="inv-1")
    assert endpoint.calls == []
