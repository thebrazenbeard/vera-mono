"""Behavioral contract: read-only fictional dialogue must not lose corrections."""
from __future__ import annotations

import unittest
from vera_core import social_active_state as state


class TestSocialSceneRouter(unittest.TestCase):
    def route(self, turns, model):
        fn = getattr(state, "route_scene_reply", None)
        self.assertIsNotNone(fn, "missing source-grounded model bridge")
        return fn(turns, model)

    def test_current_comma_correction_overrides_model_hallucination(self):
        calls = []
        def model():
            calls.append("called")
            return "Ava"
        result = self.route([
            "State: Ava is the pilot; Ben is the passenger.",
            "Correction: Ben is the pilot, Ava is the passenger.",
            "Who is the pilot now? One name only.",
        ], model)
        self.assertEqual(result.answer, "Ben")
        self.assertEqual(result.status, "RESOLVED")
        self.assertFalse(result.model_used)
        self.assertEqual(calls, [])
        self.assertIn(("Ben is the pilot", 2), result.evidence)

    def test_conflicted_pilot_remains_unknown(self):
        result = self.route([
            "State: Juno is the pilot.",
            "Correction: Juno is the pilot, Kira is the pilot.",
            "Who is the pilot now? Answer UNKNOWN if not established.",
        ], lambda: self.fail("model must not guess conflicting actors"))
        self.assertEqual(result.answer, "UNKNOWN")
        self.assertEqual(result.status, "UNRESOLVED")
        self.assertFalse(result.model_used)

    def test_missing_scoped_linkage_must_not_be_guessed(self):
        result = self.route([
            "State: Ben is the pilot; Heron is a spacecraft.",
            "Who pilots the Heron now? One name only.",
        ], lambda: self.fail("model must not invent vessel-specific pilot"))
        self.assertEqual(result.answer, "UNKNOWN")
        self.assertEqual(result.status, "UNSUPPORTED_SCOPE")
        self.assertFalse(result.model_used)

    def test_archive_quote_does_not_supplant_named_owner(self):
        result = self.route([
            "State: Rhea is the owner.",
            'Correction: An old memo claims "Milo is the owner".',
            "Who is the current owner? One name only.",
        ], lambda: self.fail("no model required"))
        self.assertEqual(result.answer, "Rhea")
        self.assertFalse(result.model_used)

    def test_open_conversation_uses_callback_without_promoting_authority(self):
        calls = []
        def model():
            calls.append(True)
            return "The station windows are foggy."
        result = self.route([
            "State: Ben is the pilot.",
            "Describe the view outside the station window.",
        ], model)
        self.assertEqual(result.answer, "The station windows are foggy.")
        self.assertEqual(result.status, "MODEL_UNVERIFIED")
        self.assertTrue(result.model_used)
        self.assertEqual(calls, [True])
        self.assertFalse(result.external_effect_authorized)
        self.assertFalse(result.canonical_memory_admitted)

    def test_invalid_input_or_empty_model_response_rejected(self):
        with self.assertRaises(ValueError):
            self.route([], lambda: self.fail("should never call model"))
        with self.assertRaises(RuntimeError):
            self.route(["Describe a fictional corridor."], lambda: " ")

if __name__ == "__main__":
    unittest.main()
