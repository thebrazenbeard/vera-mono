"""Proposed signed dispatch-authorization gate: synthetic keys, no deployment."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore
from research.goal1_acceptance_bridge.reservation_auth import (
    AuthorizedLocalDispatcher, canonical_authorization_bytes,
)

MODEL = "qwen3:4b-instruct"
MODEL_DIGEST = "a" * 64
ARTIFACT = "b" * 64
AUDIENCE = "lappy-research-gateway-01"
PROMPT = "Synthetic transport probe: answer A."
CHALLENGE = {"challenge_id": "case-001", "features": "bits:010"}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def public_digest(obj):
    return sha(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False))


class CountingTransport:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, permit, max_tokens):
        self.calls += 1
        return SimpleNamespace(
            text="A", model=MODEL, reported_model_digest=MODEL_DIGEST,
            prompt_sha256=sha(prompt), response_sha256=sha("A"),
        )


class SignedReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="goal1-signed-dispatch-")
        self.addCleanup(self.temp.cleanup)
        self.key = Ed25519PrivateKey.generate()  # disposable synthetic signer
        pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.store = LocalAttemptStore(Path(self.temp.name) / "attempts.sqlite")
        self.dispatcher = AuthorizedLocalDispatcher(
            store=self.store, trusted_issuer_public_key=pub,
            expected_audience=AUDIENCE, selected_model=MODEL,
            expected_model_artifact_sha256=ARTIFACT,
            reported_registry_digest=MODEL_DIGEST,
        )
        self.transport = CountingTransport()
        now = int(time.time())
        self.claims = {
            "schema": "GOAL1_DISPATCH_AUTHORIZATION_CANDIDATE_V1",
            "audience": AUDIENCE, "invocation_id": "inv-001",
            "route_ref": "ISOLATED_RESEARCH", "max_tokens": 8,
            "issued_at_epoch": now - 1, "expires_at_epoch": now + 60,
            "reservation": {
                "reservation_id": "res-001", "run_id": "run-001",
                "arm": "FROZEN", "challenge_id": CHALLENGE["challenge_id"],
                "challenge_view_digest": public_digest(CHALLENGE),
                "model_prompt_sha256": sha(PROMPT),
                "model_identity": MODEL,
                "model_artifact_sha256": ARTIFACT,
            },
        }

    def sign(self, data=None, key=None):
        obj = dict(self.claims if data is None else data)
        signing_key = self.key if key is None else key
        obj["signature_b64"] = base64.b64encode(
            signing_key.sign(canonical_authorization_bytes(obj))
        ).decode("ascii")
        return obj

    def call(self, ticket, *, prompt=PROMPT, challenge=CHALLENGE):
        return self.dispatcher.dispatch(
            ticket=ticket, challenge_view=challenge, prompt=prompt,
            transport=self.transport, permit=object(),
        )

    def reject_without_dispatch(self, ticket, **kwargs):
        with self.assertRaises(ValueError):
            self.call(ticket, **kwargs)
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(self.store.history(), [])

    def test_correct_signature_one_dispatch_replay_blocked_across_store_reopen(self):
        ticket = self.sign()
        record, text = self.call(ticket)
        self.assertEqual(record["status"], "COMPLETED")
        self.assertEqual(record["reservation_id"], "res-001")
        self.assertEqual(record["response_sha256"], sha(text))
        self.assertFalse(record["independent_attestation"])
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(LocalAttemptStore(self.store.path).history(), [record])
        with self.assertRaises(ValueError):
            self.call(ticket)
        self.assertEqual(self.transport.calls, 1)

    def test_missing_or_invalid_signature_rejected_before_transport(self):
        self.reject_without_dispatch(self.claims)
        self.reject_without_dispatch({**self.claims, "signature_b64": "not base64"})
        self.reject_without_dispatch({**self.sign(), "signature_b64": "AA=="})
        another = Ed25519PrivateKey.generate()
        self.reject_without_dispatch(self.sign(key=another))

    def test_wrong_audience_and_expired_or_future_ticket(self):
        self.reject_without_dispatch(self.sign({**self.claims, "audience": "other-gateway"}))
        self.reject_without_dispatch(self.sign({**self.claims, "expires_at_epoch": int(time.time())-10}))
        self.reject_without_dispatch(self.sign({**self.claims, "issued_at_epoch": int(time.time())+3600, "expires_at_epoch": int(time.time())+3700}))
        self.reject_without_dispatch(self.sign({**self.claims, "expires_at_epoch": int(time.time())+3600}))

    def test_signed_claims_not_substitutable(self):
        ticket = self.sign()
        for altered in (
            {**ticket, "invocation_id": "inv-evil"},
            {**ticket, "max_tokens": 128},
            {**ticket, "route_ref": "OTHER_ROUTE"},
            {**ticket, "reservation": {**ticket["reservation"], "model_identity": "evil"}},
            {**ticket, "reservation": {**ticket["reservation"], "challenge_id": "other"}},
        ):
            with self.subTest(modification=str(altered)[:50]):
                self.reject_without_dispatch(altered)

    def test_signed_ticket_still_rejects_modified_prompt_or_public_view(self):
        ticket = self.sign()
        self.reject_without_dispatch(ticket, prompt=PROMPT+" injection")
        self.reject_without_dispatch(ticket, challenge={**CHALLENGE, "features": "bits:111"})

    def test_malformed_request_and_extra_field_rejected(self):
        ticket = self.sign()
        self.reject_without_dispatch({**ticket, "self_appointed_witness": True})
        self.reject_without_dispatch({**ticket, "max_tokens": True})
        self.reject_without_dispatch({**ticket, "reservation": {**ticket["reservation"], "extra": True}})
        self.reject_without_dispatch({**ticket, "signature_b64": None})

    def test_no_issuer_private_key_in_dispatcher(self):
        self.assertFalse(hasattr(self.dispatcher, "sign"))
        self.assertFalse(hasattr(self.dispatcher, "private_key"))


if __name__ == "__main__":
    unittest.main()
