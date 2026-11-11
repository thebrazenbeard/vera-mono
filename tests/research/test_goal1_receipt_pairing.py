"""A signed-looking receipt cannot qualify a local record by self-assertion."""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore
from research.goal1_acceptance_bridge.receipt_pairing import pair_local_terminal

SHA = "a" * 64
RESPONSE = "b" * 64


def local_record(store):
    store.reserve(
        invocation_id="inv-pair", reservation_id="res-pair", run_id="run-pair",
        arm="FROZEN", challenge_id="case-pair",
        challenge_view_digest=SHA, route_ref="LOCAL_RESEARCH",
        model="model-pair", reported_model_digest=SHA,
        prompt_sha256=SHA, max_tokens=8,
    )
    store.record_claim("inv-pair", "claim-pair")
    store._finish("inv-pair", status="COMPLETED",
                  response_sha256=RESPONSE, elapsed_ms=14)
    return store.history()[0]


def envelope():
    return {
        "witness_kind": "independent_dispatch_gateway",
        "gateway_id": "test-gateway", "attestation_id": "attest-pair",
        "invocation_id": "inv-pair", "reservation_id": "res-pair",
        "run_id": "run-pair", "arm": "FROZEN",
        "challenge_id": "case-pair", "challenge_view_digest": SHA,
        "model_prompt_sha256": SHA, "model_response_sha256": RESPONSE,
        "model_identity": "model-pair", "model_artifact_sha256": SHA,
        "dispatch_monotonic_ns": 1000, "response_monotonic_ns": 2000,
        "outcome_status": "COMPLETED",
        "resource_usage": {
            "input_tokens": 3, "output_tokens": 1, "wall_time_ms": 1,
        },
        "signature": "SYNTHETIC_NOT_VALID",
    }


class ReceiptPairingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="goal1-pair-")
        self.addCleanup(self.directory.cleanup)
        self.store = LocalAttemptStore(Path(self.directory.name) / "attempt.sqlite")
        self.local = local_record(self.store)

    def test_matching_ids_and_self_asserted_witness_are_not_qualification(self):
        result = pair_local_terminal(self.local, envelope())
        self.assertEqual(result["status"], "LOCAL_ENVELOPE_MATCH_UNVERIFIED")
        self.assertFalse(result["qualified"])
        self.assertFalse(result["gateway_signature_verified"])
        self.assertFalse(result["remote_claim_verified"])
        self.assertFalse(result["claim_id_cryptographically_bound"])
        self.assertFalse(result["model_artifact_verified"])
        self.assertFalse(result["resource_usage_independently_measured"])
        self.assertEqual(result["claim_id"], "claim-pair")
        self.assertIn("EXTERNAL_SIGNATURE_AND_KEY_CUSTODY", result["pending"])

    def test_all_identity_substitutions_refused(self):
        fields = ("invocation_id", "reservation_id", "run_id", "arm", "challenge_id",
                  "challenge_view_digest", "model_prompt_sha256",
                  "model_response_sha256", "model_identity")
        for field in fields:
            with self.subTest(field=field):
                altered = envelope()
                altered[field] = "substituted" if not field.endswith("sha256") and field != "challenge_view_digest" else "c" * 64
                with self.assertRaises(ValueError):
                    pair_local_terminal(self.local, altered)

    def test_unsupported_terminal_conditions_are_refused(self):
        with self.assertRaises(ValueError):
            pair_local_terminal({**self.local, "status": "OUTCOME_UNKNOWN"}, envelope())
        with self.assertRaises(ValueError):
            pair_local_terminal({**self.local, "claim_id": None}, envelope())
        with self.assertRaises(ValueError):
            pair_local_terminal(self.local, {**envelope(), "outcome_status": "OUTCOME_UNKNOWN"})

    def test_malformed_usage_and_monotonic_ordering_are_refused(self):
        with self.assertRaises(ValueError):
            pair_local_terminal(self.local, {
                **envelope(), "resource_usage": {
                    "input_tokens": True, "output_tokens": 1, "wall_time_ms": 1,
                },
            })
        with self.assertRaises(ValueError):
            pair_local_terminal(self.local, {
                **envelope(), "response_monotonic_ns": 1000,
            })

    def test_extra_claim_id_or_missing_signature_is_refused(self):
        with self.assertRaises(ValueError):
            pair_local_terminal(self.local, {**envelope(), "claim_id": "claim-pair"})
        incomplete = envelope()
        incomplete.pop("signature")
        with self.assertRaises(ValueError):
            pair_local_terminal(self.local, incomplete)

    def test_mutated_local_attestation_bit_cannot_change_verdict(self):
        report = pair_local_terminal(
            {**self.local, "independent_attestation": True}, envelope())
        self.assertFalse(report["qualified"])
        self.assertFalse(report["gateway_signature_verified"])
        self.assertFalse(report["remote_claim_verified"])

    def test_caller_supplied_fake_signed_fields_never_qualify(self):
        fake = envelope()
        fake["signature"] = "a-token-the-model-invented"
        fake["gateway_id"] = "a-name-the-model-invented"
        report = pair_local_terminal(self.local, fake)
        self.assertFalse(report["qualified"])
        self.assertEqual(report["status"], "LOCAL_ENVELOPE_MATCH_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
