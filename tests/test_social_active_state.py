"""Source-grounded narrow active-state reconstruction, no model or private state."""
from __future__ import annotations

import unittest

from vera_core.social_active_state import reconstruct, render_state


class TestSocialActiveState(unittest.TestCase):
    def test_late_explicit_change_overrides_only_named_roles(self):
        turns = [
            "State: Ava is the pilot; Ben is the passenger; Heron is a spacecraft.",
            "We are approaching the station.",
            "Correction: Ben is the pilot; Ava is the passenger.",
            "A story about the control panel.",
            "Who pilots the Heron now?",
        ]
        state = reconstruct(turns)
        self.assertEqual(state["role:pilot"].value, "Ben")
        self.assertEqual(state["role:passenger"].value, "Ava")
        self.assertEqual(state["type:Heron"].value, "spacecraft")
        self.assertEqual(state["role:pilot"].turn_index, 3)
        self.assertEqual(state["role:pilot"].quote, "Ben is the pilot")
        note = render_state(state)
        self.assertIn("role:pilot = Ben [user turn 3", note)
        self.assertIn("type:Heron = spacecraft [user turn 1", note)

    def test_partial_update_preserves_other_subject_card(self):
        state = reconstruct([
            "State: Nora is the messenger; Ivo carries a red card; Nora carries a blue card.",
            "Update: Ivo is the messenger; Nora carries a green card.",
        ])
        self.assertEqual(state["role:messenger"].value, "Ivo")
        self.assertEqual(state["card:Ivo"].value, "red")
        self.assertEqual(state["card:Nora"].value, "green")

    def test_same_turn_conflicting_claims_mark_unknown(self):
        state = reconstruct(["State: Juno is the pilot; Kira is the pilot."])
        self.assertIsNone(state["role:pilot"].value)
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")
        self.assertIn("UNRESOLVED", render_state(state))
        resolved = reconstruct([
            "State: Juno is the pilot; Kira is the pilot.",
            "Correction: Kira is the pilot."
        ])
        self.assertEqual(resolved["role:pilot"].value, "Kira")

    def test_ambiguous_pronoun_correction_invalidates_old_actor(self):
        state = reconstruct([
            "State: Miko is the pilot; Dana is the passenger.",
            "Correction: He is now the pilot.",
        ])
        self.assertIsNone(state["role:pilot"].value)
        self.assertEqual(state["role:passenger"].value, "Dana")

    def test_explicit_negation_marks_unknown_no_invented_replacement(self):
        state = reconstruct([
            "State: Tessa is the guide; Milo is the messenger.",
            "Correction: Tessa is no longer the guide.",
        ])
        self.assertIsNone(state["role:guide"].value)
        self.assertEqual(state["role:messenger"].value, "Milo")

    def test_old_memo_quote_or_assistant_response_not_admitted(self):
        state = reconstruct([
            "State: Rhea is the owner.",
            "A quoted old memo states: \"State: Milo is the owner.\"",
            "Who is the owner now?",
        ])
        self.assertEqual(state["role:owner"].value, "Rhea")
        self.assertEqual(len(state), 1)

    def test_unrecognized_correction_mentions_role_and_fails_closed(self):
        state = reconstruct([
            "State: Rhea is the pilot.",
            "Correction: the pilot might be someone else, I do not know who.",
        ])
        self.assertIsNone(state["role:pilot"].value)
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")

    def test_unsupported_message_does_not_become_fact(self):
        state = reconstruct([
            "The archived record says Ava is the pilot.",
            "I think Ava is the pilot.",
        ])
        self.assertEqual(state, {})

    def test_nonnative_data_and_oversized_turns_rejected(self):
        for turns in ([], ["x" * 2000], ["State: Ava is the pilot.", 42]):
            with self.subTest(turns=str(turns)[:50]):
                with self.assertRaises(ValueError):
                    reconstruct(turns)

    def test_unchanged_role_is_not_erased_by_partial_correction(self):
        state = reconstruct([
            "State: Rhea is the owner; Otis is the pilot.",
            "Correction: Otis is the passenger; the owner stays the same.",
        ])
        self.assertEqual(state["role:owner"].value, "Rhea")
        self.assertEqual(state["role:passenger"].value, "Otis")
        self.assertEqual(state["role:pilot"].value, "Otis")

    def test_named_replacement_after_negation_is_current_not_unknown(self):
        state = reconstruct([
            "State: Juno is the pilot; Mira is the messenger.",
            "Correction: Juno is not the pilot; Kira is the pilot.",
        ])
        self.assertEqual(state["role:pilot"].value, "Kira")
        self.assertEqual(state["role:messenger"].value, "Mira")
        self.assertEqual(state["role:pilot"].quote, "Kira is the pilot")

    def test_same_turn_explicit_negation_invalidates_newly_proposed_role(self):
        state = reconstruct([
            "State: Ava is the pilot; Ava is not the pilot.",
        ])
        self.assertIsNone(state["role:pilot"].value)
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")

    def test_quote_is_exact_substring_of_user_turn(self):
        turns = [
            "State: Lena is the pilot; Tom carries a green card.",
            "Correction: Tom is the pilot; Lena carries a red card.",
        ]
        state = reconstruct(turns)
        for fact in state.values():
            self.assertIn(fact.quote, turns[fact.turn_index - 1])
            self.assertIn(fact.status, ("CURRENT", "UNRESOLVED"))


if __name__ == "__main__":
    unittest.main()
