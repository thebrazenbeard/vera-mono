"""Synthetic host-checkpoint signatures: binding is not host custody."""
from __future__ import annotations

from dataclasses import replace
import base64
import hashlib
import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from vera_core.social_checkpoint_witness import (
    SignedSocialCheckpointV1,
    TrustedCheckpointVerifier,
    CHECKPOINT_GENESIS,
)


class TestSignedSocialCheckpoint(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        self.other_key = Ed25519PrivateKey.generate()
        self.verifier = TrustedCheckpointVerifier(
            issuer_id="synthetic-checkpoint-service",
            key_id="ephemeral-host-key",
            public_key_bytes=self.public,
        )
        self.release = "a" * 40
        self.correction_signer = hashlib.sha256(b"synthetic-public-key").hexdigest()
        self.fence_head = hashlib.sha256(b"after-synthetic-candidate").hexdigest()
        self.previous_head = CHECKPOINT_GENESIS

    def signed(self, **changes):
        unsigned = SignedSocialCheckpointV1(
            issuer_id="synthetic-checkpoint-service", key_id="ephemeral-host-key",
            installation_id="fixture-install",
            source_session_id="fixture-source-session",
            release_commit=self.release,
            correction_key_sha256=self.correction_signer,
            candidate_count=1,
            fence_head=self.fence_head,
            previous_checkpoint_digest=self.previous_head,
            monotonic_epoch=1,
            signature_b64="",
        )
        unsigned = replace(unsigned, **changes)
        return replace(
            unsigned,
            signature_b64=base64.b64encode(
                self.private.sign(unsigned.signed_bytes())
            ).decode("ascii"),
        )

    def check(self, checkpoint, **expected):
        params = {
            "expected_installation_id": "fixture-install",
            "expected_session_id": "fixture-source-session",
            "expected_release_commit": self.release,
            "expected_correction_key_sha256": self.correction_signer,
            "expected_candidate_count": 1,
            "expected_fence_head": self.fence_head,
            "expected_previous_checkpoint_digest": self.previous_head,
            "expected_monotonic_epoch": 1,
        }
        params.update(expected)
        return self.verifier.verify(checkpoint, **params)

    def test_exact_checkpoint_assertion_is_valid_but_not_authority(self):
        w = self.signed()
        self.assertTrue(self.check(w))
        receipt = self.verifier.public_receipt(
            w, expected_installation_id="fixture-install",
            expected_session_id="fixture-source-session",
            expected_release_commit=self.release,
            expected_correction_key_sha256=self.correction_signer,
            expected_candidate_count=1,
            expected_fence_head=self.fence_head,
            expected_previous_checkpoint_digest=self.previous_head,
            expected_monotonic_epoch=1,
        )
        self.assertTrue(receipt["signature_valid_under_supplied_key"])
        self.assertFalse(receipt["independent_host_custody_verified"])
        self.assertFalse(receipt["actual_user_source_verified"])
        self.assertFalse(receipt["canonical_memory_admitted"])
        self.assertFalse(receipt["external_effect_authorized"])
        visible = json.dumps(receipt)
        for hidden in (
            w.signature_b64, w.installation_id, w.source_session_id,
            w.fence_head, w.correction_key_sha256, w.previous_checkpoint_digest,
        ):
            self.assertNotIn(hidden, visible)

    def test_wrong_expected_current_epoch_or_session_denied(self):
        w = self.signed()
        for field, value in (
            ("expected_monotonic_epoch", 2),
            ("expected_session_id", "other-session"),
            ("expected_fence_head", hashlib.sha256(b"other").hexdigest()),
            ("expected_previous_checkpoint_digest", "b"*64),
            ("expected_release_commit", "b"*40),
            ("expected_correction_key_sha256", "c"*64),
            ("expected_candidate_count", 0),
            ("expected_installation_id", "other-install"),
        ):
            with self.subTest(field=field):
                self.assertFalse(self.check(w, **{field: value}))

    def test_cryptographically_valid_resigned_wrong_fields_denied(self):
        w = self.signed()
        changes = (
            ("installation_id", "other-install"),
            ("source_session_id", "old-session"),
            ("release_commit", "b"*40),
            ("correction_key_sha256", "f"*64),
            ("candidate_count", 5),
            ("fence_head", "f"*64),
            ("previous_checkpoint_digest", "c"*64),
            ("monotonic_epoch", 3),
            ("issuer_id", "untrusted-issuer"),
            ("key_id", "forged-key"),
        )
        for field, value in changes:
            with self.subTest(field=field):
                forged = self.signed(**{field: value})
                self.assertFalse(self.check(forged))

    def test_signature_and_wrong_key_denied(self):
        w = self.signed()
        for signature in ("", "%bad", "AAAA", None):
            with self.subTest(signature=signature):
                self.assertFalse(self.check(replace(w, signature_b64=signature)))
        other_public = self.other_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )
        other_verifier = TrustedCheckpointVerifier(
            issuer_id=self.verifier.issuer_id,
            key_id=self.verifier.key_id,
            public_key_bytes=other_public,
        )
        self.assertFalse(other_verifier.verify(
            w, expected_installation_id="fixture-install",
            expected_session_id="fixture-source-session",
            expected_release_commit=self.release,
            expected_correction_key_sha256=self.correction_signer,
            expected_candidate_count=1,
            expected_fence_head=self.fence_head,
            expected_previous_checkpoint_digest=self.previous_head,
            expected_monotonic_epoch=1,
        ))

    def test_signed_bytes_require_exact_typed_bounds(self):
        w = self.signed()
        for field, value in (
            ("candidate_count", True),
            ("candidate_count", -1),
            ("monotonic_epoch", 0),
            ("monotonic_epoch", 1.5),
            ("release_commit", "short"),
            ("fence_head", "nothex"),
            ("source_session_id", ""),
            ("issuer_id", ""),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(w, **{field: value}).signed_bytes()

    def test_bare_boolean_cannot_generate_receipt(self):
        with self.assertRaises(TypeError):
            self.verifier.public_receipt(True)

    def test_old_signed_checkpoint_is_still_replayable_without_external_epoch(self):
        w = self.signed()
        self.assertTrue(self.check(w))
        self.assertTrue(self.check(w))
        self.assertFalse(self.check(w, expected_monotonic_epoch=2))
        # Explicitly no semantic one-time replay claim when caller supplies epoch.


if __name__ == "__main__":
    unittest.main()
