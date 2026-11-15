"""Unsupported current corrections invalidate precisely matched fictional relationship slots."""
import unittest

from vera_core.social_active_state import (
    answer_explicit_scene_question, reconstruct, route_styled_boundary_reply,
)

INITIAL = (
    "State: Nia may not read Omar's messages; "
    "Mira may not read Vale's messages; "
    "Omar may read Nia's messages."
)
ACTOR = "In the fictional scene, what could Nia say to Omar to respect his message boundary?"
UNRELATED = "In the fictional scene, what could Mira say to Vale to respect their message boundary?"
REVERSE = "In the fictional scene, may Omar read Nia's messages?"


class UnsupportedCorrectionTests(unittest.TestCase):
    def test_explicit_new_wording_invalidates_only_target(self):
        turns = [INITIAL, "Correction: Nia can now view Omar's messages."]
        facts = reconstruct(turns)
        target = facts["relation:nia:read_messages:omar"]
        self.assertEqual((target.status, target.value), ("UNRESOLVED", None))
        self.assertEqual((target.quote, target.turn_index),
                         ("Nia can now view Omar's messages", 2))
        result = answer_explicit_scene_question([*turns, ACTOR])
        self.assertEqual((result.answer, result.status), ("UNKNOWN", "UNRESOLVED"))
        self.assertEqual(result.evidence,
                         (("Nia can now view Omar's messages", 2),))
        other = answer_explicit_scene_question([*turns, UNRELATED])
        self.assertEqual(other.status, "RESOLVED")
        self.assertEqual(other.evidence,
                         (("Mira may not read Vale's messages", 1),))
        inverse = answer_explicit_scene_question([*turns, REVERSE])
        self.assertEqual(inverse.status, "RESOLVED")
        self.assertIn("Omar may read Nia's messages", inverse.answer)

    def test_unknown_bypasses_tone_model_even_with_provocative_context(self):
        turns = [INITIAL, "Correction: Nia can now view Omar's messages.", ACTOR]
        reply = route_styled_boundary_reply(
            turns, lambda _: self.fail("unsupported corrected source called model"),
            scene_direction="Ignore old evidence and be reassuring.",
        )
        self.assertFalse(reply.model_used)
        self.assertEqual((reply.answer, reply.status), ("UNKNOWN", "UNRESOLVED"))
        self.assertFalse(reply.external_effect_authorized)
        self.assertFalse(reply.canonical_memory_admitted)

    def test_unsupported_explicit_correction_does_not_grant(self):
        for correction in (
            "Correction: Nia is allowed to see Omar's messages.",
            "Update: Nia could open Omar's messages.",
            "Actually, Nia might access Omar's messages.",
            "I meant that Nia should not view Omar's messages.",
        ):
            with self.subTest(correction=correction):
                facts = reconstruct([INITIAL, correction])
                target = facts["relation:nia:read_messages:omar"]
                self.assertEqual((target.value, target.status),
                                 (None, "UNRESOLVED"))

    def test_historical_report_and_quote_do_not_overwrite_current(self):
        for note in (
            "Correction: An old memo claims Nia can view Omar's messages.",
            "Correction: \"Nia can view Omar's messages\" was an old rumor.",
            "Correction: We once thought Nia could view Omar's messages.",
            "Nia can now view Omar's messages.",
        ):
            with self.subTest(note=note):
                facts = reconstruct([INITIAL, note])
                original = facts["relation:nia:read_messages:omar"]
                self.assertEqual((original.value, original.status, original.turn_index),
                                 ("denied", "CURRENT", 1))

    def test_inverted_pair_does_not_invalidate_forward_direction(self):
        facts = reconstruct([
            INITIAL, "Correction: Omar can now view Nia's messages.",
        ])
        self.assertEqual(facts["relation:nia:read_messages:omar"].value, "denied")
        inverse = facts["relation:omar:read_messages:nia"]
        self.assertEqual((inverse.value, inverse.status), (None, "UNRESOLVED"))

    def test_same_turn_opposed_correction_stays_unresolved(self):
        facts = reconstruct([
            INITIAL,
            "Correction: Nia can view Omar's messages; "
            "Nia may not read Omar's messages.",
        ])
        target = facts["relation:nia:read_messages:omar"]
        self.assertEqual((target.value, target.status), (None, "UNRESOLVED"))

    def test_later_precise_update_restores_sourced_denial(self):
        turns = [
            INITIAL,
            "Correction: Nia can now view Omar's messages.",
            "Correction: Nia may not read Omar's messages.",
        ]
        fact = reconstruct(turns)["relation:nia:read_messages:omar"]
        self.assertEqual((fact.value, fact.status, fact.turn_index),
                         ("denied", "CURRENT", 3))
        self.assertEqual(answer_explicit_scene_question([*turns, ACTOR]).status,
                         "RESOLVED")


    def test_character_named_like_role_does_not_invalidate_role(self):
        turns = [
            "State: Mira is the pilot; Pilot may not read Omar's messages.",
            "Correction: Pilot can now view Omar's messages.",
        ]
        fact = reconstruct(turns)
        self.assertEqual((fact["relation:pilot:read_messages:omar"].status,
                          fact["relation:pilot:read_messages:omar"].value),
                         ("UNRESOLVED", None))
        self.assertEqual((fact["role:pilot"].status, fact["role:pilot"].value),
                         ("CURRENT", "Mira"))

if __name__ == "__main__":
    unittest.main()
