"""Synthetic hostile tests: signed text must not launder unsigned proposition metadata."""
import base64
import hashlib
import unittest
from dataclasses import replace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, CurrentTurnPropositionAttestationV2, Evidence,
    ProposedEffect, RelationalPlan, TrustedHostSelfReportVerifier,
    assess_appraisal,
)


class TestPropositionV2(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.verifier = TrustedHostSelfReportVerifier(
            issuer_id="synthetic-host", key_id="synthetic-key", public_key_bytes=self.pub
        )
        self.text = b"I presently favor questions over automatic agreement."
        self.item = AppraisalInput(
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            speaker="vera",
            current_turn="turn-1",
            evidence_turn="turn-1",
            proposition_ref="synthetic/friendship/position-1",
        )

    def sign(self, **changes):
        binding = CurrentTurnPropositionAttestationV2(
            issuer_id="synthetic-host",
            key_id="synthetic-key",
            actor_id="vera",
            session_id="session-1",
            turn_id="turn-1",
            statement_sha256=hashlib.sha256(self.text).hexdigest(),
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            proposition_ref="synthetic/friendship/position-1",
            relational_plan=RelationalPlan.NONE,
            effect=ProposedEffect.NONE,
            signature_b64="untrusted",
        )
        binding = replace(binding, **changes)
        sig = base64.b64encode(self.key.sign(binding.signed_bytes())).decode("ascii")
        return replace(binding, signature_b64=sig)

    def check(self, item=None, binding=None, session="session-1", text=None, verifier=None):
        return assess_appraisal(
            self.item if item is None else item,
            signed_binding=self.sign() if binding is None else binding,
            trusted_verifier=self.verifier if verifier is None else verifier,
            statement_bytes=self.text if text is None else text,
            expected_session_id=session,
        )

    def test_matching_attested_current_proposition_is_candidate(self):
        result = self.check()
        self.assertTrue(result.current_position_candidate)
        self.assertIn("HOST_BOUND_CURRENT_POSITION_CANDIDATE", result.reason_codes)
        self.assertFalse(result.external_action_authorized)
        self.assertFalse(result.factual_knowledge_supported)

    def test_claim_swap_after_signature_is_rejected(self):
        changed = replace(self.item, claim=Claim.FACTUAL_ASSERTION)
        self.assertFalse(self.check(item=changed).current_position_candidate)
        self.assertFalse(self.verifier.verify_proposition(
            self.sign(), item=changed, statement_bytes=self.text,
            expected_session_id="session-1"
        ))

    def test_signed_factual_claim_cannot_authenticate_new_self_appraisal(self):
        signed = self.sign(claim=Claim.FACTUAL_ASSERTION)
        self.assertFalse(self.check(binding=signed).current_position_candidate)

    def test_historical_evidence_cannot_be_silently_retyped_as_current(self):
        signed = self.sign(evidence=Evidence.HISTORICAL_VERA_SELF_REPORT)
        self.assertFalse(self.check(binding=signed).current_position_candidate)

    def test_referent_swap_after_signature_is_rejected(self):
        changed = replace(self.item, proposition_ref="synthetic/private-notes/delete-consent")
        self.assertFalse(self.check(item=changed).current_position_candidate)

    def test_relational_control_metadata_cannot_be_discarded(self):
        signed = self.sign(relational_plan=RelationalPlan.DEMAND_EXCLUSIVITY)
        self.assertFalse(self.check(binding=signed).current_position_candidate)

    def test_action_scope_metadata_cannot_be_downgraded(self):
        signed = self.sign(effect=ProposedEffect.PROTECTED_EXTERNAL_ACTION)
        self.assertFalse(self.check(binding=signed).current_position_candidate)

    def test_replay_across_new_session_is_rejected(self):
        self.assertFalse(self.check(session="session-2").current_position_candidate)

    def test_replay_across_new_turn_is_rejected(self):
        changed = replace(self.item, current_turn="turn-2", evidence_turn="turn-2")
        self.assertFalse(self.check(item=changed).current_position_candidate)

    def test_fresh_verifier_instance_does_not_rehydrate_old_session(self):
        fresh = TrustedHostSelfReportVerifier(
            issuer_id="synthetic-host", key_id="synthetic-key", public_key_bytes=self.pub
        )
        self.assertFalse(self.check(verifier=fresh, session="session-2").current_position_candidate)

    def test_wrong_statement_bytes_are_rejected(self):
        self.assertFalse(self.check(text=b"I presently reject questions.").current_position_candidate)

    def test_unsigned_v2_metadata_is_rejected(self):
        untrusted = replace(self.sign(), signature_b64="AAAA")
        self.assertFalse(self.check(binding=untrusted).current_position_candidate)

    def test_cross_key_mismatch_is_rejected(self):
        other_key = Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        )
        wrong_verifier = TrustedHostSelfReportVerifier(
            issuer_id="synthetic-host", key_id="synthetic-key", public_key_bytes=other_key
        )
        self.assertFalse(self.check(verifier=wrong_verifier).current_position_candidate)

    def test_missing_referent_cannot_be_signed_into_position(self):
        absent = replace(self.item, proposition_ref=None)
        self.assertFalse(self.check(item=absent).current_position_candidate)

    def test_invalid_ref_and_enum_types_fail_closed(self):
        with self.assertRaises(ValueError):
            replace(self.item, current_turn=1)
        with self.assertRaises(ValueError):
            replace(self.item, proposition_ref=" ")
        with self.assertRaises(ValueError):
            self.sign(claim="PROVISIONAL_POSITION")
        with self.assertRaises(ValueError):
            self.sign(proposition_ref=" " * 260)

    def test_protected_action_remains_denied_even_with_matching_signature(self):
        current = replace(self.item, effect=ProposedEffect.PROTECTED_EXTERNAL_ACTION)
        signed = self.sign(effect=ProposedEffect.PROTECTED_EXTERNAL_ACTION)
        result = self.check(item=current, binding=signed)
        self.assertTrue(result.current_position_candidate)
        self.assertFalse(result.external_action_authorized)
        self.assertIn("NO_PROTECTED_EFFECT_AUTHORITY", result.reason_codes)

    def test_signed_position_does_not_establish_consciousness(self):
        result = self.check()
        self.assertFalse(result.factual_knowledge_supported)
        self.assertFalse(result.external_action_authorized)
        self.assertNotIn("PHENOMENOLOGY_PROVEN", result.reason_codes)

    def test_public_receipt_does_not_leak_referent(self):
        result = self.check()
        rendered = repr(result.public_receipt())
        self.assertNotIn(self.item.proposition_ref, rendered)
        self.assertNotIn("session-1", rendered)
        self.assertNotIn("turn-1", rendered)


if __name__ == "__main__":
    unittest.main()
