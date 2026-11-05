"""Source-only ES256 WebAuthn verifier regression and hostile tests."""

from dataclasses import replace
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from vera_memory.webauthn_review import (
    ReviewAssertionRejected, WebAuthnAssertion, WebAuthnReviewVerifier,
    review_challenge,
)


REVIEW = (
    b'{"action":"APPROVE","approval_ref":"review-1",'
    b'"candidate_revision":"candidate-abc","expected_journal_head":"head-123",'
    b'"nonce":"1234567890abcdef1234567890abcdef"}'
)
RP = "review.example.com"
ORIGIN = "https://review.example.com"
CREDENTIAL_ID = b"test-credential-id-unique-1"


class ReviewVerifierTests(unittest.TestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.verifier = WebAuthnReviewVerifier(
            rp_id=RP,
            expected_origin=ORIGIN,
            credential_id=CREDENTIAL_ID,
            public_key_pem=self.key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ),
        )

    def assertion(self, *, review=REVIEW, flags=0x05, rp=RP, credential=CREDENTIAL_ID, client=None):
        if client is None:
            client = {
                "type": "webauthn.get",
                "origin": ORIGIN,
                "challenge": base64.urlsafe_b64encode(review_challenge(review)).rstrip(b"=").decode(),
                "crossOrigin": False,
            }
        client_bytes = json.dumps(client, separators=(",", ":")).encode("utf-8")
        auth = sha256(rp.encode()).digest() + bytes([flags]) + (1).to_bytes(4, "big")
        sig = self.key.sign(auth + sha256(client_bytes).digest(), ec.ECDSA(hashes.SHA256()))
        return WebAuthnAssertion(credential, client_bytes, auth, sig)

    def test_exact_action_and_checkpoint_are_cryptographically_bound(self):
        proof = self.assertion()
        verified = self.verifier.verify(REVIEW, proof)
        self.assertEqual(verified.signed_review_sha256, sha256(REVIEW).hexdigest())
        self.assertEqual(verified.authenticator_counter, 1)
        self.assertEqual(verified.assertion, proof)
        with self.assertRaisesRegex(ReviewAssertionRejected, "challenge"):
            self.verifier.verify(REVIEW.replace(b"APPROVE", b"REVOKE"), proof)
        with self.assertRaisesRegex(ReviewAssertionRejected, "challenge"):
            self.verifier.verify(REVIEW.replace(b"head-123", b"head-456"), proof)

    def test_user_presence_and_verification_both_required(self):
        for flags in (0, 1, 4):
            with self.subTest(flags=flags), self.assertRaisesRegex(ReviewAssertionRejected, "presence"):
                self.verifier.verify(REVIEW, self.assertion(flags=flags))

    def test_unknown_credential_id_rejected_even_with_valid_signature(self):
        with self.assertRaisesRegex(ReviewAssertionRejected, "credential"):
            self.verifier.verify(REVIEW, self.assertion(credential=b"attacker-credential"))

    def test_origin_and_rp_hash_pinned(self):
        client = {
            "type": "webauthn.get", "origin": "https://attacker.example.com",
            "challenge": base64.urlsafe_b64encode(review_challenge(REVIEW)).rstrip(b"=").decode(),
        }
        with self.assertRaisesRegex(ReviewAssertionRejected, "origin"):
            self.verifier.verify(REVIEW, self.assertion(client=client))
        with self.assertRaisesRegex(ReviewAssertionRejected, "relying-party"):
            self.verifier.verify(REVIEW, self.assertion(rp="attacker.example.com"))

    def test_invalid_signature_rejected(self):
        proof = self.assertion()
        changed_signature = proof.signature_der[:-1] + bytes([proof.signature_der[-1] ^ 0x01])
        with self.assertRaisesRegex(ReviewAssertionRejected, "signature"):
            self.verifier.verify(REVIEW, replace(proof, signature_der=changed_signature))

    def test_cross_origin_and_extensions_fail_closed(self):
        client = {
            "type": "webauthn.get", "origin": ORIGIN,
            "challenge": base64.urlsafe_b64encode(review_challenge(REVIEW)).rstrip(b"=").decode(),
            "crossOrigin": True,
        }
        with self.assertRaisesRegex(ReviewAssertionRejected, "cross-origin"):
            self.verifier.verify(REVIEW, self.assertion(client=client))
        with self.assertRaisesRegex(ReviewAssertionRejected, "extensions"):
            self.verifier.verify(REVIEW, self.assertion(flags=0x85))

    def test_duplicate_client_json_key_rejected(self):
        good = self.assertion()
        client_bytes = good.client_data_json[:-1] + b',"origin":"https://review.example.com"}'
        sig = self.key.sign(
            good.authenticator_data + sha256(client_bytes).digest(), ec.ECDSA(hashes.SHA256())
        )
        with self.assertRaisesRegex(ReviewAssertionRejected, "duplicate"):
            self.verifier.verify(REVIEW, replace(good, client_data_json=client_bytes, signature_der=sig))

    def test_nonstandard_json_nan_rejected_even_if_signed(self):
        good = self.assertion()
        client_bytes = good.client_data_json[:-1] + b',"unsupported":NaN}'
        sig = self.key.sign(
            good.authenticator_data + sha256(client_bytes).digest(), ec.ECDSA(hashes.SHA256())
        )
        with self.assertRaisesRegex(ReviewAssertionRejected, "non-JSON"):
            self.verifier.verify(REVIEW, replace(good, client_data_json=client_bytes, signature_der=sig))

    def test_wrong_algorithm_key_rejected(self):
        other = ec.generate_private_key(ec.SECP384R1())
        pem = other.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with self.assertRaisesRegex(ReviewAssertionRejected, "P-256"):
            WebAuthnReviewVerifier(
                rp_id=RP, expected_origin=ORIGIN,
                credential_id=CREDENTIAL_ID, public_key_pem=pem,
            )

    def test_assertion_is_not_a_caller_boolean(self):
        with self.assertRaisesRegex(ReviewAssertionRejected, "raw WebAuthn"):
            self.verifier.verify(REVIEW, True)

    @unittest.expectedFailure
    def test_unmet_acceptance_current_ed25519_journal_cannot_admit_webauthn(self):
        """Expected RED until journal dispatches and re-verifies WebAuthn proof.

        A valid ES256 proof is deliberately rejected by the current exact-type
        Ed25519-only apply_review. This is an unmet acceptance criterion,
        not a passing end-to-end human approval. Opt in with VERA_MONO_SOURCE.
        """
        repo = os.environ.get("VERA_MONO_SOURCE")
        if not repo:
            self.skipTest("set VERA_MONO_SOURCE to run current-API integration gap")
        root = Path(repo).resolve()
        with (root / "pyproject.toml").open("rb") as config:
            for relative in tomllib.load(config)["tool"]["pytest"]["ini_options"]["pythonpath"]:
                sys.path.insert(0, str(root / relative))
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from vera_memory.supervised_feedback import SupervisedFeedbackJournal

        valid_webauthn_proof = self.verifier.verify(REVIEW, self.assertion())
        ed25519_key = Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        with tempfile.TemporaryDirectory() as directory:
            journal = SupervisedFeedbackJournal(
                Path(directory) / "feedback.sqlite3",
                installation_id="synthetic-only",
                trusted_reviewer_key=ed25519_key,
                synthetic_fixture_mode=True,
            )
            # Fails today: the journal accepts only ReviewDecision containing
            # a raw Ed25519 signature, not a verified ES256 assertion.
            journal.apply_review(valid_webauthn_proof)


if __name__ == "__main__":
    unittest.main()
