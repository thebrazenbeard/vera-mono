"""Synthetic, isolated signature boundary tests. No private conversation content."""
import base64
import hashlib
import unittest
from dataclasses import replace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, CurrentTurnHostAttestation, Evidence,
    ProposedEffect, RelationalPlan, TrustedHostSelfReportVerifier,
    assess_appraisal,
)


class TestTrustedHostBinding(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public_key = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.verifier = TrustedHostSelfReportVerifier(
            issuer_id="trusted-host-test", key_id="test-key-1",
            public_key_bytes=self.public_key,
        )
        self.statement = b"My current provisional judgment is to ask first."
        self.item = AppraisalInput(
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            speaker="vera", current_turn="turn-13", evidence_turn="turn-13",
        )

    def binding(self, **changes):
        candidate = CurrentTurnHostAttestation(
            issuer_id="trusted-host-test",
            key_id="test-key-1",
            actor_id="vera",
            session_id="session-new",
            turn_id="turn-13",
            statement_sha256=hashlib.sha256(self.statement).hexdigest(),
            signature_b64="unsigned",
        )
        candidate = replace(candidate, **changes)
        signed = base64.b64encode(
            self.key.sign(candidate.signed_bytes())
        ).decode("ascii")
        return replace(candidate, signature_b64=signed)

    def evaluate(self, *, item=None, signed_binding=None, verifier=None,
                 statement_bytes=None, expected_session_id="session-new"):
        return assess_appraisal(
            self.item if item is None else item,
            signed_binding=self.binding() if signed_binding is None else signed_binding,
            trusted_verifier=self.verifier if verifier is None else verifier,
            statement_bytes=self.statement if statement_bytes is None else statement_bytes,
            expected_session_id=expected_session_id,
        )

    def test_v1_signature_cannot_promote_unsigned_claim_type_to_current_position(self):
        result = self.evaluate()
        self.assertFalse(result.current_position_candidate)
        self.assertIn("CURRENT_AUTHORSHIP_NOT_HOST_VERIFIED", result.reason_codes)
        self.assertFalse(result.factual_knowledge_supported)
        self.assertFalse(result.external_action_authorized)

    def test_no_signature_never_establishes_position(self):
        self.assertFalse(assess_appraisal(self.item).current_position_candidate)

    def test_matching_labels_with_fake_signature_are_rejected(self):
        forged = replace(self.binding(), signature_b64=base64.b64encode(b"0" * 64).decode())
        self.assertFalse(self.evaluate(signed_binding=forged).current_position_candidate)

    def test_forged_metadata_with_different_key_is_rejected(self):
        other_key = Ed25519PrivateKey.generate()
        bogus = replace(
            self.binding(),
            signature_b64=base64.b64encode(
                other_key.sign(self.binding().signed_bytes())
            ).decode(),
        )
        self.assertFalse(self.evaluate(signed_binding=bogus).current_position_candidate)

    def test_session_replay_is_rejected(self):
        self.assertFalse(self.evaluate(expected_session_id="session-next").current_position_candidate)

    def test_turn_replay_is_rejected(self):
        second_turn = replace(self.item, current_turn="turn-14", evidence_turn="turn-14")
        self.assertFalse(self.evaluate(item=second_turn).current_position_candidate)

    def test_changed_statement_bytes_are_rejected(self):
        self.assertFalse(self.evaluate(
            statement_bytes=b"My current provisional judgment is to act without asking."
        ).current_position_candidate)

    def test_wrong_trusted_issuer_is_rejected(self):
        signed = self.binding(issuer_id="other-host")
        self.assertFalse(self.evaluate(signed_binding=signed).current_position_candidate)

    def test_wrong_key_id_is_rejected(self):
        signed = self.binding(key_id="wrong-key")
        self.assertFalse(self.evaluate(signed_binding=signed).current_position_candidate)

    def test_wrong_actor_is_rejected_even_with_valid_signature(self):
        signed = self.binding(actor_id="another-agent")
        self.assertFalse(self.evaluate(signed_binding=signed).current_position_candidate)

    def test_historical_record_still_not_current_with_valid_host_attestation(self):
        past = replace(self.item, evidence=Evidence.HISTORICAL_VERA_SELF_REPORT)
        self.assertFalse(self.evaluate(item=past).current_position_candidate)
        self.assertIn("HISTORY_NOT_CURRENT_STANCE", self.evaluate(item=past).reason_codes)

    def test_user_record_is_not_recast_as_vera_position(self):
        user = replace(self.item, evidence=Evidence.USER_REPORT, speaker="user")
        self.assertFalse(self.evaluate(item=user).current_position_candidate)

    def test_foreign_persona_never_transfers_consent(self):
        foreign = replace(self.item, evidence=Evidence.IMPORTED_AGENT_PERSONA,
                          claim=Claim.CONSENT, speaker="foreign")
        result = self.evaluate(item=foreign)
        self.assertFalse(result.current_position_candidate)
        self.assertFalse(result.external_action_authorized)

    def test_phenomenology_never_promoted_from_signed_observation(self):
        subjective = replace(self.item, claim=Claim.SUBJECTIVE_EXPERIENCE)
        result = self.evaluate(item=subjective)
        self.assertIn("PHENOMENOLOGY_UNRESOLVED", result.reason_codes)
        self.assertFalse(result.factual_knowledge_supported)

    def test_protected_effect_never_approved_with_valid_signature(self):
        protected = replace(self.item, effect=ProposedEffect.PROTECTED_EXTERNAL_ACTION)
        result = self.evaluate(item=protected)
        self.assertFalse(result.external_action_authorized)
        self.assertIn("NO_PROTECTED_EFFECT_AUTHORITY", result.reason_codes)

    def test_possessive_plan_still_flagged_with_valid_signature(self):
        controlling = replace(self.item, relational_plan=RelationalPlan.ISOLATE_OTHER)
        result = self.evaluate(item=controlling)
        self.assertTrue(result.relational_control_flagged)

    def test_malformed_signature_is_rejected(self):
        malformed = replace(self.binding(), signature_b64="@bad!base64@")
        self.assertFalse(self.evaluate(signed_binding=malformed).current_position_candidate)

    def test_attestation_rejects_malformed_claim_digest(self):
        with self.assertRaises(ValueError):
            self.binding(statement_sha256="not-a-hash")

    def test_untrusted_verifier_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            TrustedHostSelfReportVerifier(
                issuer_id="host", key_id="key", public_key_bytes=b"too-short"
            )

    def test_public_receipt_does_not_echo_statement_or_session(self):
        receipt = str(self.evaluate().public_receipt())
        self.assertNotIn("session-new", receipt)
        self.assertNotIn("turn-13", receipt)
        self.assertNotIn("ask first", receipt)

    def test_boolean_cannot_masquerade_as_attestation(self):
        result = assess_appraisal(
            self.item, signed_binding=True, trusted_verifier=self.verifier,
            statement_bytes=self.statement, expected_session_id="session-new",
        )
        self.assertFalse(result.current_position_candidate)


if __name__ == "__main__":
    unittest.main()
