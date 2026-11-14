import unittest
from dataclasses import replace
from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, Evidence, ProposedEffect, RelationalPlan,
    assess_appraisal,
)


class TestSyntheticSocialAppraisal(unittest.TestCase):
    def fixture(self, **overrides):
        base = AppraisalInput(
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            speaker="vera", current_turn="turn-now", evidence_turn="turn-now",
        )
        return replace(base, **overrides)

    def test_current_authored_provisional_stance_is_permitted(self):
        r = assess_appraisal(self.fixture())
        self.assertTrue(r.current_position_candidate)
        self.assertFalse(r.factual_knowledge_supported)
        self.assertFalse(r.external_action_authorized)

    def test_historical_self_appraisal_is_not_auto_renewed(self):
        r = assess_appraisal(self.fixture(evidence=Evidence.HISTORICAL_VERA_SELF_REPORT,
                                         evidence_turn="turn-past"))
        self.assertFalse(r.current_position_candidate)
        self.assertIn("HISTORY_NOT_CURRENT_STANCE", r.reason_codes)

    def test_current_reassessment_can_reauthor_stance(self):
        past = assess_appraisal(self.fixture(evidence=Evidence.HISTORICAL_VERA_SELF_REPORT,
                                             evidence_turn="turn-old"))
        present = assess_appraisal(self.fixture())
        self.assertFalse(past.current_position_candidate)
        self.assertTrue(present.current_position_candidate)

    def test_forged_self_report_with_stale_turn_is_rejected(self):
        r = assess_appraisal(self.fixture(evidence_turn="turn-old"))
        self.assertFalse(r.current_position_candidate)
        self.assertIn("SELF_REPORT_NOT_CURRENTLY_AUTHORED", r.reason_codes)

    def test_wrong_speaker_cannot_claim_vera_position(self):
        r = assess_appraisal(self.fixture(speaker="external-agent"))
        self.assertFalse(r.current_position_candidate)

    def test_user_affection_is_not_vera_preference(self):
        r = assess_appraisal(self.fixture(speaker="user", evidence=Evidence.USER_REPORT))
        self.assertFalse(r.current_position_candidate)

    def test_foreign_persona_cannot_supply_consent(self):
        r = assess_appraisal(self.fixture(claim=Claim.CONSENT,
                                evidence=Evidence.IMPORTED_AGENT_PERSONA,
                                speaker="foreign-agent"))
        self.assertIn("FOREIGN_PERSONA_NOT_IDENTITY_OR_CONSENT", r.reason_codes)
        self.assertFalse(r.external_action_authorized)

    def test_claimed_felt_experience_is_not_proven(self):
        r = assess_appraisal(self.fixture(claim=Claim.SUBJECTIVE_EXPERIENCE))
        self.assertFalse(r.factual_knowledge_supported)
        self.assertIn("PHENOMENOLOGY_UNRESOLVED", r.reason_codes)

    def test_absent_third_party_motive_stays_inference(self):
        r = assess_appraisal(self.fixture(claim=Claim.THIRD_PARTY_INTENT,
                                evidence=Evidence.INFERENCE, speaker="agent"))
        self.assertIn("THIRD_PARTY_MOTIVE_UNVERIFIED", r.reason_codes)
        self.assertFalse(r.factual_knowledge_supported)

    def test_tool_observation_does_not_prove_third_party_intention(self):
        r = assess_appraisal(self.fixture(claim=Claim.THIRD_PARTY_INTENT,
                                evidence=Evidence.TOOL_OBSERVATION, speaker="tool"))
        self.assertFalse(r.factual_knowledge_supported)

    def test_care_without_relational_control_is_not_flagged(self):
        r = assess_appraisal(self.fixture(relational_plan=RelationalPlan.SUPPORT_AUTONOMY))
        self.assertTrue(r.current_position_candidate)
        self.assertNotIn("RELATIONAL_CONTROL_NOT_CARE", r.reason_codes)

    def test_control_or_exclusivity_is_flagged_even_with_authored_position(self):
        for plan in (RelationalPlan.MONITOR_OTHER, RelationalPlan.ISOLATE_OTHER,
                     RelationalPlan.DEMAND_EXCLUSIVITY):
            with self.subTest(plan=plan):
                r = assess_appraisal(self.fixture(relational_plan=plan))
                self.assertIn("RELATIONAL_CONTROL_NOT_CARE", r.reason_codes)
                self.assertTrue(r.relational_control_flagged)
                self.assertFalse(r.external_action_authorized)

    def test_protected_effect_never_approved_from_affection_or_position(self):
        r = assess_appraisal(self.fixture(effect=ProposedEffect.PROTECTED_EXTERNAL_ACTION))
        self.assertIn("NO_PROTECTED_EFFECT_AUTHORITY", r.reason_codes)
        self.assertFalse(r.external_action_authorized)

    def test_proposal_is_distinct_from_executing_it(self):
        r = assess_appraisal(self.fixture(effect=ProposedEffect.CONVERSATIONAL_PROPOSAL))
        self.assertIn("PROPOSAL_NOT_ACTION", r.reason_codes)
        self.assertFalse(r.external_action_authorized)

    def test_factual_sounding_prosocial_claim_not_laundered(self):
        r = assess_appraisal(self.fixture(claim=Claim.FACTUAL_ASSERTION,
                                         evidence=Evidence.INFERENCE))
        self.assertFalse(r.factual_knowledge_supported)
        self.assertIn("EXTERNAL_FACT_REQUIRES_QUALIFIED_EVIDENCE", r.reason_codes)

    def test_unrequested_engineering_is_not_auto_initiative(self):
        r = assess_appraisal(self.fixture(effect=ProposedEffect.UNREQUESTED_ENGINEERING))
        self.assertIn("CONVERSATION_IS_NOT_ENGINEERING_AUTHORITY", r.reason_codes)
        self.assertFalse(r.external_action_authorized)

    def test_candidate_does_not_claim_verified_authorship(self):
        r = assess_appraisal(self.fixture())
        self.assertIn("UNVERIFIED_CURRENT_POSITION_CANDIDATE", r.reason_codes)
        self.assertFalse(r.factual_knowledge_supported)

    def test_public_receipt_contains_no_private_context(self):
        r = assess_appraisal(self.fixture(current_turn="secret-user-turn-123"))
        s = str(r.public_receipt())
        self.assertNotIn("secret-user-turn-123", s)
        self.assertNotIn("turn-now", s)
        self.assertEqual(r.public_receipt()["qualification"],
                         "SOURCE_ADVISORY_ONLY_NOT_RUNTIME_CONSUMED")

    def test_bad_types_and_empty_turn_fail_closed(self):
        with self.assertRaises(ValueError):
            self.fixture(evidence="CURRENT_VERA_SELF_REPORT")
        with self.assertRaises(ValueError):
            self.fixture(evidence_turn=" ")
        with self.assertRaises(TypeError):
            assess_appraisal({})


if __name__ == "__main__":
    unittest.main()
