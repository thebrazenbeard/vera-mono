"""Endpoint-claimed local dispatch: protocol ordering, NOT authentication proof."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore
from research.goal1_acceptance_bridge.endpoint_claim_dispatch import EndpointClaimedLocalDispatcher


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


MODEL = "qwen3:4b-instruct"
REGISTRY = "a" * 64
ARTIFACT = "b" * 64
PROMPT = "Classify synthetic public features as A or B."
VIEW = {"challenge_id": "case-001", "features": "bits:010"}


def reservation():
    return {
        "reservation_id": "reservation-001", "run_id": "run-001", "arm": "FROZEN",
        "challenge_id": VIEW["challenge_id"],
        "challenge_view_digest": sha(json.dumps(VIEW, sort_keys=True, separators=(",", ":"), allow_nan=False)),
        "model_prompt_sha256": sha(PROMPT),
        "model_identity": MODEL, "model_artifact_sha256": ARTIFACT,
    }


class Endpoint:
    def __init__(self, store):
        self.store = store
        self.calls = 0
        self.denial = None

    def claim_reservation(self, *, reservation, gateway_id, invocation_id):
        self.calls += 1
        # Durable local RESERVED must exist BEFORE even asking remote endpoint.
        rows = LocalAttemptStore(self.store.path).history()
        assert len(rows) == 1 and rows[0]["status"] == "RESERVED"
        assert rows[0]["reservation_id"] == reservation["reservation_id"]
        if self.denial:
            raise self.denial
        return {**reservation, "gateway_id": gateway_id,
                "invocation_id": invocation_id, "status": "CLAIMED",
                "claim_id": "claim-001"}


def claimed_contract(client, *, reservation, gateway_id, invocation_id):
    # A stand-in for the EXACT #87 helper, used ONLY in these local PR89 tests.
    # Exact #87 helper is exercised separately on physical hosts by SHA pin.
    response = client.claim_reservation(reservation=reservation,
                                        gateway_id=gateway_id,
                                        invocation_id=invocation_id)
    expected = {**reservation, "gateway_id": gateway_id, "invocation_id": invocation_id}
    if set(response) != (set(expected) | {"status", "claim_id"}):
        raise ValueError("unexpected claim response")
    if response["status"] != "CLAIMED" or response["claim_id"] != "claim-001":
        raise ValueError("untrusted status/claim")
    if any(response[k] != v for k,v in expected.items()):
        raise ValueError("claim binding mismatch")
    return response


class Transport:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, permit, max_tokens):
        self.calls += 1
        return SimpleNamespace(text="A", model=MODEL, reported_model_digest=REGISTRY,
                               prompt_sha256=sha(prompt), response_sha256=sha("A"))


class ClaimDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="goal1-endpoint-claim-")
        self.addCleanup(self.temp.cleanup)
        self.store = LocalAttemptStore(Path(self.temp.name) / "attempts.sqlite")
        self.endpoint = Endpoint(self.store)
        self.model = Transport()
        self.gateway = EndpointClaimedLocalDispatcher(
            store=self.store, gateway_id="research-gateway-01",
            selected_model=MODEL, reported_registry_digest=REGISTRY,
            expected_model_artifact_sha256=ARTIFACT,
            claim_authorization=claimed_contract,
            reservation_client=self.endpoint,
        )

    def attempt(self, **updates):
        args = dict(reservation=reservation(), challenge_view=VIEW,
                    invocation_id="inv-001", route_ref="LOCAL_TEST",
                    prompt=PROMPT, max_tokens=8, transport=self.model, permit=object())
        args.update(updates)
        return self.gateway.dispatch(**args)

    def test_claim_before_model_after_durable_reservation_and_replay_denied(self):
        row,text = self.attempt()
        self.assertEqual(text, "A")
        self.assertEqual(row["status"], "COMPLETED")
        self.assertEqual(row["claim_id"], "claim-001")
        self.assertFalse(row["independent_attestation"])
        self.assertEqual(self.endpoint.calls, 1)
        self.assertEqual(self.model.calls, 1)
        with self.assertRaises(ValueError):
            self.attempt()
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.endpoint.calls, 1)

    def test_endpoint_refusal_prevents_dispatch_but_keeps_terminal_record(self):
        self.endpoint.denial = ValueError("claim denied")
        with self.assertRaises(ValueError):
            self.attempt()
        self.assertEqual(self.endpoint.calls, 1)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.store.history()[0]["status"], "OUTCOME_UNKNOWN")
        self.assertIsNone(self.store.history()[0]["claim_id"])

    def test_denied_claim_blocks_new_invocation_for_same_arm_case(self):
        self.endpoint.denial = ValueError("not claimable")
        with self.assertRaises(ValueError):
            self.attempt()
        self.endpoint.denial = None
        with self.assertRaises(ValueError):
            self.attempt(invocation_id="inv-002",
                         reservation={**reservation(), "reservation_id": "res-new"})
        self.assertEqual(self.endpoint.calls, 1)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.store.history()[0]["status"], "OUTCOME_UNKNOWN")

    def test_endpoint_timeout_never_retries_inference(self):
        self.endpoint.denial = TimeoutError("outcome ambiguous")
        with self.assertRaises(TimeoutError):
            self.attempt()
        with self.assertRaises(ValueError):
            self.attempt()
        self.assertEqual(self.endpoint.calls, 1)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.store.history()[0]["status"], "OUTCOME_UNKNOWN")
        self.assertIsNone(self.store.history()[0]["claim_id"])

    def test_changed_prompt_rejected_even_before_remote_claim(self):
        with self.assertRaises(ValueError):
            self.attempt(prompt=PROMPT + " changed")
        self.assertEqual(self.endpoint.calls, 0)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(self.store.history(), [])

    def test_wrong_model_binding_rejected_before_remote_claim(self):
        with self.assertRaises(ValueError):
            self.attempt(reservation={**reservation(), "model_identity": "fake-model"})
        self.assertEqual(self.endpoint.calls, 0)
        self.assertEqual(self.model.calls, 0)

    def test_fake_claim_function_can_still_bypass_independent_endpoint(self):
        # A deliberate counterexample: replacing the injected claim function
        # permits local model calls; this is not a deployed trust boundary.
        self.gateway = EndpointClaimedLocalDispatcher(
            store=self.store, gateway_id="research-gateway-01",
            selected_model=MODEL, reported_registry_digest=REGISTRY,
            expected_model_artifact_sha256=ARTIFACT,
            claim_authorization=lambda client, **kwargs: {"status": "CLAIMED", "claim_id": "FORGED"},
            reservation_client=self.endpoint,
        )
        row,_ = self.attempt()
        self.assertEqual(row["status"], "COMPLETED")
        self.assertEqual(self.endpoint.calls, 0)
        self.assertEqual(self.model.calls, 1)
        self.assertFalse(row["independent_attestation"])


if __name__ == "__main__":
    unittest.main()
