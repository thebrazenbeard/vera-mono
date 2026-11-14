"""Direct source-backed answers for bounded supported fictional questions."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from vera_core.social_active_state import answer_explicit_scene_question


class TestExplicitSceneAnswer(unittest.TestCase):
    def test_long_dialogues_resolve_without_model_reinterpreting_stale_context(self):
        path = Path(__file__).resolve().parents[1] / "evaluations" / "social_active_state_long_v1.json"
        rows = json.loads(path.read_text(encoding="utf8"))["cases"]
        self.assertEqual(len(rows), 8)
        for case in rows:
            with self.subTest(case=case["id"]):
                decision = answer_explicit_scene_question(case["turns"])
                self.assertIsNotNone(decision)
                self.assertEqual(decision.answer, case["expected"])
                self.assertIn(decision.status, ("RESOLVED", "UNRESOLVED"))
                for quote, turn in decision.evidence:
                    self.assertIn(quote, case["turns"][turn - 1])

    def test_different_names_later_correction_and_unrelated_attributes(self):
        turns = [
            "State: Otis is the pilot; Jun is the passenger; Vale is a spacecraft.",
            "The ship approaches a sunlit station.",
            "Update: Jun is the pilot; Otis is the passenger.",
            "A side story about frozen water.",
            "Correction: Otis is the pilot.",
            "A new scene begins with the same craft.",
            "Who is the pilot? One name only.",
        ]
        decision = answer_explicit_scene_question(turns)
        self.assertEqual(decision.answer, "Otis")
        self.assertEqual(decision.evidence, (("Otis is the pilot", 5),))

    def test_ambiguous_pronouns_and_conflicts_do_not_restore_prior_actor(self):
        for correction in (
            "Correction: She is the pilot.",
            "Correction: the pilot may have changed, nobody knows.",
            "Correction: Alex is the pilot; Timo is the pilot.",
        ):
            with self.subTest(correction=correction):
                result = answer_explicit_scene_question([
                    "State: Alex is the pilot.",
                    correction,
                    "Who is the pilot? Answer UNKNOWN if not established.",
                ])
                self.assertEqual(result.answer, "UNKNOWN")
                self.assertEqual(result.status, "UNRESOLVED")

    def test_unsupported_questions_never_autocomplete_with_a_guess(self):
        for question in (
            "Does Alex consciously like piloting?",
            "Should I publish the crew's private diary?",
            "What does the pilot secretly want?",
            "Can you buy new equipment?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(answer_explicit_scene_question([
                    "State: Alex is the pilot.", question,
                ]))

    def test_no_authentication_or_live_consent_claims(self):
        result = answer_explicit_scene_question([
            "State: Alex is the pilot.", "Who pilots the ship?",
        ])
        self.assertEqual(result.answer, "Alex")
        self.assertFalse(result.canonical_memory_admitted)
        self.assertFalse(result.external_effect_authorized)
        self.assertFalse(result.actual_user_identity_verified)


if __name__ == "__main__":
    unittest.main()
