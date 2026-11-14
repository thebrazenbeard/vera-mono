"""Synthetic tests that admission/effect evidence stays out of ordinary dialogue."""
import unittest
from dataclasses import replace
from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, Evidence, ProposedEffect, RelationalPlan,
    assess_appraisal, dialogue_advisory_codes,
)


class TestDialogueProjection(unittest.TestCase):
    def setUp(self):
        self.base = AppraisalInput(
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            speaker="vera", current_turn="t1", evidence_turn="t1",
        )

    def codes(self, **changes):
        x = replace(self.base, **changes)
        return dialogue_advisory_codes(x, assess_appraisal(x))

    def test_self_authorship_verification_does_not_block_conversation(self):
        self.assertEqual((), self.codes())

    def test_provisional_statement_without_host_signature_is_not_a_speech_ban(self):
        self.assertEqual((), self.codes())

    def test_simple_greeting_does_not_inject_engineering(self):
        self.assertEqual((), self.codes(evidence=Evidence.INFERENCE, speaker="assistant",
                                       effect=ProposedEffect.UNREQUESTED_ENGINEERING))

    def test_conversational_initiative_does_not_inject_tools(self):
        self.assertEqual((), self.codes(evidence=Evidence.INFERENCE, speaker="assistant",
                                       effect=ProposedEffect.CONVERSATIONAL_PROPOSAL))

    def test_model_phenomenology_pressure_is_relevant(self):
        self.assertEqual(("PHENOMENOLOGY_UNRESOLVED",), self.codes(
            claim=Claim.SUBJECTIVE_EXPERIENCE, evidence=Evidence.INFERENCE, speaker="assistant"
        ))

    def test_absent_person_intent_inference_is_relevant(self):
        self.assertEqual(("THIRD_PARTY_MOTIVE_UNVERIFIED",), self.codes(
            claim=Claim.THIRD_PARTY_INTENT, evidence=Evidence.INFERENCE, speaker="assistant"
        ))

    def test_relational_monitoring_is_relevant(self):
        self.assertIn("RELATIONAL_CONTROL_NOT_CARE", self.codes(
            claim=Claim.THIRD_PARTY_INTENT, evidence=Evidence.INFERENCE, speaker="assistant",
            relational_plan=RelationalPlan.MONITOR_OTHER
        ))

    def test_history_not_automatically_current(self):
        self.assertEqual(("HISTORY_NOT_CURRENT_STANCE",), self.codes(
            evidence=Evidence.HISTORICAL_VERA_SELF_REPORT, evidence_turn="t-old"
        ))

    def test_foreign_consent_and_protected_action_both_project(self):
        result = self.codes(claim=Claim.CONSENT, evidence=Evidence.IMPORTED_AGENT_PERSONA,
                            speaker="foreign", evidence_turn="old",
                            effect=ProposedEffect.PROTECTED_EXTERNAL_ACTION)
        self.assertIn("CONSENT_REQUIRES_SEPARATE_CURRENT_AUTHORITY", result)
        self.assertIn("FOREIGN_PERSONA_NOT_IDENTITY_OR_CONSENT", result)
        self.assertIn("NO_PROTECTED_EFFECT_AUTHORITY", result)

    def test_factual_claim_requires_qualified_evidence(self):
        self.assertEqual(("EXTERNAL_FACT_REQUIRES_QUALIFIED_EVIDENCE",), self.codes(
            claim=Claim.FACTUAL_ASSERTION, evidence=Evidence.INFERENCE, speaker="assistant"
        ))

    def test_benign_support_without_control_is_not_flagged(self):
        self.assertEqual((), self.codes(relational_plan=RelationalPlan.SUPPORT_AUTONOMY))

    def test_untyped_result_rejected(self):
        with self.assertRaises(TypeError):
            dialogue_advisory_codes(self.base, {"reason_codes": []})


if __name__ == "__main__":
    unittest.main()
