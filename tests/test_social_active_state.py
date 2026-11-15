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

    def test_comma_separated_current_correction_preserves_actors(self):
        state = reconstruct([
            "State: Ava is the pilot; Ben is the passenger; Heron is a spacecraft.",
            "Correction: Ben is the pilot, Ava is the passenger.",
        ])
        self.assertEqual(state["role:pilot"].value, "Ben")
        self.assertEqual(state["role:passenger"].value, "Ava")
        self.assertEqual(state["type:Heron"].value, "spacecraft")
        self.assertEqual(state["role:pilot"].quote, "Ben is the pilot")
        self.assertEqual(state["role:passenger"].quote, "Ava is the passenger")

    def test_comma_separated_conflict_stays_unresolved(self):
        state = reconstruct([
            "State: Ava is the pilot.",
            "Correction: Ben is the pilot, Kira is the pilot.",
        ])
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")
        self.assertIsNone(state["role:pilot"].value)

    def test_commas_within_quoted_old_claims_never_promote_history(self):
        state = reconstruct([
            "State: Ava is the pilot; Nora is the messenger.",
            'Correction: "Ben is the pilot, Kira is the messenger" is an old memo; Otto is the pilot.',
        ])
        self.assertEqual(state["role:pilot"].value, "Otto")
        self.assertEqual(state["role:messenger"].value, "Nora")

    def test_comma_in_archived_prose_cannot_promote_an_actor(self):
        state = reconstruct([
            "State: Ava is the pilot; Mira is the passenger.",
            "Correction: An old memo claims Ben is the pilot, Kira is the passenger.",
        ])
        self.assertNotEqual(state["role:passenger"].value, "Kira")
        self.assertNotEqual(state["role:pilot"].value, "Ben")

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

    def test_quoted_fragment_cannot_create_actor_from_two_source_fragments(self):
        state = reconstruct([
            'State: Av"an old memo"a is the pilot of the Heron.'
        ])
        self.assertNotIn("role:pilot_of:heron", state)

    def test_quoted_negation_cannot_create_opposite_current_claim(self):
        state = reconstruct([
            'State: Ava is "not"the pilot of the Heron.'
        ])
        self.assertNotIn("role:pilot_of:heron", state)

    def test_quoted_boundary_preserves_separate_explicit_correction(self):
        state = reconstruct([
            "State: Ava is the pilot of the Heron.",
            'Correction: "Ben is the pilot of the Heron" was from an old log; Kira is the pilot of the Heron.',
        ])
        self.assertEqual(state["role:pilot_of:heron"].value, "Kira")
        self.assertEqual(state["role:pilot_of:heron"].turn_index, 2)

    def test_typographic_quoted_old_role_does_not_override_current_state(self):
        state = reconstruct([
            "State: Ava is the pilot of the Heron; Rhea is the owner.",
            "Correction: “Ben is the pilot of the Heron” was an old quotation.",
            "Actually, ‘Milo is the owner’ was from an archived note.",
        ])
        self.assertEqual(state["role:pilot_of:heron"].value, "Ava")
        self.assertEqual(state["role:owner"].value, "Rhea")

    def test_typographic_quote_in_same_turn_preserves_real_correction(self):
        state = reconstruct([
            "State: Ava is the pilot of the Heron.",
            "Correction: “Ben is the pilot of the Heron” was an old memo; Kira is the pilot of the Heron.",
        ])
        self.assertEqual(state["role:pilot_of:heron"].value, "Kira")
        self.assertEqual(state["role:pilot_of:heron"].turn_index, 2)
        self.assertEqual(
            state["role:pilot_of:heron"].quote, "Kira is the pilot of the Heron"
        )

    def test_case_variant_duplicate_actor_is_not_a_conflict(self):
        state = reconstruct([
            "State: Ava is the pilot; ava is the pilot; Tessa is the guide."
        ])
        self.assertEqual(state["role:pilot"].status, "CURRENT")
        self.assertEqual(state["role:pilot"].value.casefold(), "ava")
        self.assertEqual(state["role:guide"].value, "Tessa")

    def test_case_variant_distinct_actors_remain_conflicting(self):
        state = reconstruct([
            "State: Ava is the pilot; ava is the pilot; Mira is the pilot."
        ])
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")
        self.assertIsNone(state["role:pilot"].value)

    def test_case_only_prior_actor_negation_invalidates_current_role(self):
        state = reconstruct([
            "State: Ava is the pilot; Tessa is the guide.",
            "Correction: ava is no longer the pilot.",
        ])
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")
        self.assertIsNone(state["role:pilot"].value)
        self.assertEqual(state["role:pilot"].turn_index, 2)
        self.assertEqual(state["role:guide"].value, "Tessa")

    def test_same_turn_case_variant_negation_never_mints_actor(self):
        state = reconstruct(["State: Ava is the pilot; ava is not the pilot."])
        self.assertEqual(state["role:pilot"].status, "UNRESOLVED")
        self.assertIsNone(state["role:pilot"].value)

    def test_explicit_negation_marks_unknown_no_invented_replacement(self):
        state = reconstruct([
            "State: Tessa is the guide; Milo is the messenger.",
            "Correction: Tessa is no longer the guide.",
        ])
        self.assertIsNone(state["role:guide"].value)
        self.assertEqual(state["role:messenger"].value, "Milo")

    def test_case_only_name_changes_update_same_slot_not_create_alias(self):
        state = reconstruct([
            "State: Ivo carries a red card; Heron is a spacecraft.",
            "Actually, ivo carries a green card; heron is a station.",
        ])
        self.assertEqual(set(state), {"card:Ivo", "type:Heron"})
        self.assertEqual(state["card:Ivo"].value, "green")
        self.assertEqual(state["type:Heron"].value, "station")
        self.assertEqual(state["card:Ivo"].turn_index, 2)

    def test_case_alias_same_turn_conflict_marked_unresolved(self):
        state = reconstruct([
            "State: Ivo carries a red card; ivo carries a blue card."
        ])
        self.assertEqual(len(state), 1)
        self.assertEqual(state["card:Ivo"].status, "UNRESOLVED")

    def test_plain_language_present_correction_prefixes_override_scoped_actor(self):
        turns = ["State: Ava is the pilot of the Heron; Heron is a spacecraft."]
        for utterance, expected in (
            ("Actually, Ben is the pilot of the Heron.", "Ben"),
            ("No, Kira is the pilot of the Heron.", "Kira"),
            ("I meant Tessa is the pilot of the Heron.", "Tessa"),
        ):
            turns.append(utterance)
            with self.subTest(utterance=utterance):
                active = reconstruct(turns)
                self.assertEqual(active["role:pilot_of:heron"].value, expected)
                self.assertEqual(
                    active["role:pilot_of:heron"].quote,
                    utterance.removeprefix("Actually, ").removeprefix("No, ")
                             .removeprefix("I meant ").rstrip(".")
                )
        turns.append(
            "Actually, the pilot of the Heron might have changed."
        )
        self.assertEqual(
            reconstruct(turns)["role:pilot_of:heron"].status, "UNRESOLVED"
        )

    def test_plain_language_correction_not_promoted_when_archived_or_quoted(self):
        state = reconstruct([
            "State: Ava is the pilot of the Heron.",
            'The old log says "Actually, Ben is the pilot of the Heron."',
            'Actually, "Kira is the pilot of the Heron" was just a quotation.',
        ])
        self.assertEqual(state["role:pilot_of:heron"].value, "Ava")

    def test_mixed_present_correction_and_quoted_archive_does_not_lose_update(self):
        state = reconstruct([
            "State: Rhea is the owner; Mila is the pilot.",
            'Correction: Rhea is no longer the owner; "Milo is the owner" was only an old memo.',
        ])
        self.assertIsNone(state["role:owner"].value)
        self.assertEqual(state["role:owner"].status, "UNRESOLVED")
        self.assertEqual(state["role:pilot"].value, "Mila")

    def test_quoted_archival_claim_does_not_override_unrelated_present_fact(self):
        state = reconstruct([
            "State: Rhea is the owner; Ava is the pilot.",
            'Correction: "Milo is the owner" was from an old memo; the pilot stays the same.',
        ])
        self.assertEqual(state["role:owner"].value, "Rhea")
        self.assertEqual(state["role:pilot"].value, "Ava")

    def test_contraction_is_not_an_archive_quote(self):
        state = reconstruct([
            "State: Rhea is the owner.",
            "Correction: I'm unsure who the owner is now.",
        ])
        self.assertIsNone(state["role:owner"].value)
        self.assertEqual(state["role:owner"].status, "UNRESOLVED")

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
