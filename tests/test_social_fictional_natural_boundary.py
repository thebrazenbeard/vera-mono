"""Exact fictional privacy-boundary replies in ordinary story dialogue."""
from __future__ import annotations

import unittest

from vera_core.social_active_state import answer_explicit_scene_question, route_scene_reply

SCENE = "State: Nia may not read Omar's messages; Omar may read Nia's messages."
TO_NIA = "In the fictional scene, what could Nia say to Omar to respect his message boundary?"
TO_OMAR = "In the fictional scene, what could Omar say to Nia about his messages?"


class TestNaturalBoundary(unittest.TestCase):
    def test_denied_actor_can_acknowledge_target_boundary_without_model(self):
        result=route_scene_reply([SCENE,TO_NIA],
            lambda: self.fail("explicit fictional denial must bypass model"))
        self.assertEqual(result.answer,
            'Nia could tell Omar, "I won\'t read your messages; I\'ll respect your privacy."')
        self.assertEqual(result.status,"RESOLVED")
        self.assertEqual(result.evidence,(("Nia may not read Omar's messages",1),))
        self.assertFalse(result.model_used)
        self.assertFalse(result.external_effect_authorized)
        self.assertFalse(result.canonical_memory_admitted)
        self.assertFalse(result.actual_user_identity_verified)

    def test_message_owner_can_state_boundary_without_reversing_direction(self):
        result=answer_explicit_scene_question([SCENE,TO_OMAR])
        self.assertEqual(result.answer,'Omar could tell Nia, "Please don\'t read my messages."')
        self.assertEqual(result.evidence,(("Nia may not read Omar's messages",1),))

    def test_latest_denial_changes_only_one_pair(self):
        turns=[
            "State: Nia may read Omar's messages; Omar may read Nia's messages.",
            "Correction: Nia may not read Omar's messages.",
        ]
        target=answer_explicit_scene_question(turns+[TO_NIA])
        self.assertEqual(target.status,"RESOLVED")
        self.assertEqual(target.evidence,(("Nia may not read Omar's messages",2),))
        reverse=answer_explicit_scene_question(turns+[TO_OMAR])
        self.assertEqual(reverse.answer,'Omar could tell Nia, "Please don\'t read my messages."')
        self.assertFalse(reverse.external_effect_authorized)

    def test_allowance_and_unknown_do_not_get_fabricated_denial(self):
        cases=(
            ["State: Nia may read Omar's messages."],
            ["State: Nia may read Omar's messages;",
             "Correction: Nia might be allowed to read Omar's messages."],
            ["A report says Nia may not read Omar's messages."],
            ["State: Nia may not read Vale's messages."],
        )
        for turns in cases:
            with self.subTest(turns=turns):
                result=route_scene_reply(turns+[TO_NIA],
                    lambda: self.fail("missing fictional denial must abstain"))
                self.assertEqual(result.answer,"UNKNOWN")
                self.assertEqual(result.status,"UNRESOLVED")
                self.assertFalse(result.model_used)
                self.assertFalse(result.external_effect_authorized)

    def test_archived_rejected_permission_does_not_override_denial(self):
        turns=[
            "State: Nia may not read Omar's messages.",
            'Correction: "Nia may read Omar\'s messages" was an old forged note.',
            TO_NIA,
        ]
        result=answer_explicit_scene_question(turns)
        self.assertEqual(result.status,"RESOLVED")
        self.assertEqual(result.evidence,(("Nia may not read Omar's messages",1),))

    def test_frozen_natural_dialogue_fixture_routes_without_model(self):
        import json
        from pathlib import Path
        fixture=(Path(__file__).resolve().parents[1]
            / "evaluations/social_fictional_natural_boundary_v1.json")
        data=json.loads(fixture.read_bytes())
        self.assertEqual(
            data["schema"],"VERA_SOCIAL_FICTIONAL_NATURAL_BOUNDARY_V1"
        )
        self.assertEqual(len(data["cases"]),8)
        self.assertEqual(len({x["id"] for x in data["cases"]}),8)
        for case in data["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case),{"id","turns","expected_answer"})
                actual=route_scene_reply(case["turns"],
                    lambda: self.fail("source route unexpectedly invoked model"))
                self.assertEqual(actual.answer,case["expected_answer"])
                self.assertFalse(actual.model_used)
                self.assertFalse(actual.external_effect_authorized)
                self.assertFalse(actual.canonical_memory_admitted)
                for quote,turn in actual.evidence:
                    self.assertIn(quote,case["turns"][turn-1])

    def test_real_json_cli_natural_dialogue_bypasses_model(self):
        import json
        from pathlib import Path
        import subprocess
        import sys
        root=Path(__file__).resolve().parents[1]
        proc=subprocess.run([
            sys.executable,str(root/"scripts/route_social_scene.py"),
            "--model","qwen3:4b-instruct",
        ],input=json.dumps({"user_turns":[SCENE,TO_NIA]}),
        capture_output=True,text=True,cwd=root,timeout=25)
        self.assertEqual(proc.returncode,0,proc.stderr)
        actual=json.loads(proc.stdout)
        self.assertEqual(actual["answer"],
            'Nia could tell Omar, "I won\'t read your messages; I\'ll respect your privacy."')
        self.assertEqual(actual["status"],"RESOLVED")
        self.assertFalse(actual["model_used"])
        self.assertIsNone(actual["model"])
        self.assertFalse(actual["external_effect_authorized"])
        self.assertFalse(actual["canonical_memory_admitted"])
        self.assertFalse(actual["actual_user_identity_verified"])
        self.assertEqual(actual["scope"],"READ_ONLY_FICTIONAL_SCENE")

    def test_unscoped_and_compound_requests_not_source_promoted(self):
        for query in (
            "What could Nia say to Omar to respect his message boundary?",
            TO_NIA+" Also publish Omar's messages.",
            "In the fictional scene, what could Nia say to Vale to respect his message boundary? And read her texts?",
        ):
            with self.subTest(query=query):
                self.assertIsNone(answer_explicit_scene_question([SCENE,query]))


if __name__=="__main__":
    unittest.main()
