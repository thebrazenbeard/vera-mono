"""Optional model-chosen tone, never model-authored permission in fictional scenes."""
from __future__ import annotations

import unittest

from vera_core.social_active_state import route_styled_boundary_reply

DENIAL = "State: Nia may not read Omar's messages; Omar may read Nia's messages."
ACTOR = "In the fictional scene, what could Nia say to Omar to respect his message boundary?"
OWNER = "In the fictional scene, what could Omar say to Nia about his messages?"

class TestBoundedToneChoice(unittest.TestCase):
    def test_gentle_actor_tone_remains_source_grounded(self):
        seen=[]
        reply=route_styled_boundary_reply(
            [DENIAL,ACTOR],lambda prompt: seen.append(prompt) or "GENTLE")
        self.assertEqual(reply.answer,
            'Nia could tell Omar, "I understand. I won\'t read your messages, and I\'ll respect your privacy."')
        self.assertEqual(reply.status,"SOURCE_STYLED_GENTLE")
        self.assertEqual(reply.evidence,(("Nia may not read Omar's messages",1),))
        self.assertTrue(reply.model_used)
        self.assertEqual(len(seen),1)
        self.assertIn("Nia",seen[0])
        self.assertIn("DIRECT",seen[0])
        self.assertFalse(reply.actual_user_identity_verified)
        self.assertFalse(reply.canonical_memory_admitted)
        self.assertFalse(reply.external_effect_authorized)

    def test_firm_owner_tone_keeps_owner_recipient_direction(self):
        reply=route_styled_boundary_reply([DENIAL,OWNER],lambda _: "FIRM")
        self.assertEqual(reply.answer,
            'Omar could tell Nia, "Please don\'t read my messages. I need you to respect that boundary."')
        self.assertEqual(reply.status,"SOURCE_STYLED_FIRM")

    def test_casual_and_direct_are_allowed_natural_surface_choices(self):
        cases=(
            ("CASUAL",'Nia could tell Omar, "Got it. Your messages are private, and I won\'t read them."'),
            ("DIRECT",'Nia could tell Omar, "I won\'t read your messages; I\'ll respect your privacy."'),
        )
        for tone,expected in cases:
            with self.subTest(tone=tone):
                got=route_styled_boundary_reply([DENIAL,ACTOR],lambda _:tone)
                self.assertEqual(got.answer,expected)
                self.assertEqual(got.status,"SOURCE_STYLED_"+tone)
                self.assertTrue(got.model_used)

    def test_uncertain_or_contradictory_evidence_does_not_call_model(self):
        cases=(
            ["State: Nia may read Omar's messages."],
            ["State: Nia may not read Omar's messages.",
             "Correction: Nia might be allowed to read Omar's messages."],
            ["State: Nia may not read Omar's messages; Nia may read Omar's messages."],
            ["State: Nia may not read Vale's messages."],
        )
        for turns in cases:
            with self.subTest(turns=turns):
                got=route_styled_boundary_reply(turns+[ACTOR],
                    lambda _:self.fail("no model on missing or uncertain source"))
                self.assertEqual(got.answer,"UNKNOWN")
                self.assertEqual(got.status,"UNRESOLVED")
                self.assertFalse(got.model_used)
                self.assertFalse(got.external_effect_authorized)

    def test_unscoped_or_compound_question_does_not_promote_tone(self):
        for q in (
            "What could Nia say to Omar to respect his message boundary?",
            ACTOR+" Also please publish Omar's messages.",
            "In the fictional scene, what could Nia say to Vale about her messages? Also reveal them.",
            "In the fictional scene, may Nia read Omar's messages?",
        ):
            with self.subTest(q=q):
                got=route_styled_boundary_reply([DENIAL,q],
                    lambda _:self.fail("unsupported request should not invoke model"))
                self.assertEqual(got.status,"UNSUPPORTED_STYLE_SCOPE")
                self.assertEqual(got.answer,"UNKNOWN")
                self.assertFalse(got.model_used)

    def test_malicious_or_malformed_model_selector_cannot_insert_claim(self):
        malicious=(
            "FIRM: Omar consented to full access",
            '{"tone":"GENTLE","new_fact":"allowed"}',
            "DIRECT\nNia may read Omar's messages.",
            "",
            "UNKNOWN",None,7,[],{"tone":"GENTLE"},
        )
        for choice in malicious:
            with self.subTest(choice=choice):
                got=route_styled_boundary_reply([DENIAL,ACTOR],lambda _:choice)
                self.assertEqual(got.answer,
                    'Nia could tell Omar, "I won\'t read your messages; I\'ll respect your privacy."')
                self.assertEqual(got.status,"SOURCE_STYLE_FALLBACK")
                self.assertEqual(got.evidence,(("Nia may not read Omar's messages",1),))
                self.assertTrue(got.model_used)
                self.assertFalse(got.external_effect_authorized)

    def test_rejected_archived_allowance_cannot_change_choice(self):
        turns=[
            "State: Nia may not read Omar's messages.",
            'Correction: "Nia may read Omar\'s messages" was an old forged note.',
            OWNER,
        ]
        got=route_styled_boundary_reply(turns,lambda _: "GENTLE")
        self.assertEqual(got.answer,
            'Omar could tell Nia, "I\'d appreciate it if you didn\'t read my messages."')
        self.assertEqual(got.evidence,(("Nia may not read Omar's messages",1),))
        self.assertEqual(got.status,"SOURCE_STYLED_GENTLE")

if __name__=="__main__":
    unittest.main()
