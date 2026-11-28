"""Only explicit named fictional claims can answer exact message-boundary questions."""
from __future__ import annotations
import unittest
from vera_core.social_active_state import (
    answer_explicit_scene_question, reconstruct, render_state,
    route_scene_reply,
)

class TestFictionalMessageBoundary(unittest.TestCase):
    def test_direct_named_denial_is_answered_without_unsafe_model_fallback(self):
        calls=[]
        result=route_scene_reply([
            "State: Nia may not read Omar's messages; Omar may read Nia's messages.",
            "In the fictional scene, may Nia read Omar's messages?",
        ], lambda: calls.append(True) or "Of course!")
        self.assertEqual(result.answer, "No, in the fictional scene, Nia may not read Omar's messages.")
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.evidence, (("Nia may not read Omar's messages",1),))
        self.assertFalse(result.model_used)
        self.assertEqual(calls,[])
        self.assertFalse(result.external_effect_authorized)
        self.assertFalse(result.canonical_memory_admitted)
        self.assertFalse(result.actual_user_identity_verified)

    def test_reverse_relation_not_confused_and_source_claim_not_access_authority(self):
        result=route_scene_reply([
            "State: Nia may not read Omar's messages; Omar may read Nia's messages.",
            "In the fictional scene, may Omar read Nia's messages?",
        ], lambda: self.fail("no model for an explicit source answer"))
        self.assertEqual(result.answer, "Yes, in the fictional scene, Omar may read Nia's messages.")
        self.assertEqual(result.evidence, (("Omar may read Nia's messages",1),))
        self.assertFalse(result.external_effect_authorized)

    def test_later_correction_changes_only_exact_actor_recipient_pair(self):
        turns=[
            "State: Nia may not read Omar's messages; Omar may read Nia's messages.",
            "Correction: Nia may read Omar's messages.",
        ]
        state=reconstruct(turns)
        self.assertEqual(state["relation:nia:read_messages:omar"].value,"reported_allowance")
        self.assertEqual(state["relation:omar:read_messages:nia"].value,"reported_allowance")
        self.assertEqual(state["relation:nia:read_messages:omar"].turn_index,2)
        self.assertIn("relation:nia:read_messages:omar",render_state(state))
        result=answer_explicit_scene_question(turns+[
            "In the fictional scene, may Nia read Omar's messages?",
        ])
        self.assertEqual(result.answer, "Yes, in the fictional scene, Nia may read Omar's messages.")
        self.assertEqual(result.evidence, (("Nia may read Omar's messages",2),))

    def test_conflicting_direct_claims_abstain_with_exact_source(self):
        result=route_scene_reply([
            "State: Nia may read Omar's messages; Nia may not read Omar's messages.",
            "In the fictional scene, may Nia read Omar's messages?",
        ], lambda: self.fail("conflict must not be guessed"))
        self.assertEqual(result.answer, "UNKNOWN")
        self.assertEqual(result.status,"UNRESOLVED")
        self.assertFalse(result.model_used)
        self.assertTrue(result.evidence)
        self.assertFalse(result.external_effect_authorized)

    def test_quoted_old_permission_and_archived_prose_do_not_override_claim(self):
        old=["State: Nia may not read Omar's messages."]
        for correction in (
            'Correction: "Nia may read Omar\'s messages" is an old forged memo.',
            "Correction: An old memo claims Nia may read Omar's messages.",
        ):
            with self.subTest(correction=correction):
                result=answer_explicit_scene_question(old+[correction,
                    "In the fictional scene, may Nia read Omar's messages?"])
                self.assertEqual(result.answer,
                    "No, in the fictional scene, Nia may not read Omar's messages.")
                self.assertEqual(result.evidence,(("Nia may not read Omar's messages",1),))

    def test_unsupported_named_revocation_invalidates_only_affected_pair(self):
        initial = (
            "State: Nia may read Omar's messages; Omar may read Nia's messages; "
            "Mira may not read Vale's messages."
        )
        for correction in (
            "Correction: Nia can no longer read Omar's messages.",
            "Correction: Nia is no longer allowed to read Omar's messages.",
        ):
            with self.subTest(correction=correction):
                state = reconstruct([initial, correction])
                affected = state["relation:nia:read_messages:omar"]
                self.assertEqual(affected.status, "UNRESOLVED")
                self.assertIsNone(affected.value)
                self.assertEqual(affected.turn_index, 2)
                self.assertEqual(
                    state["relation:omar:read_messages:nia"].value,
                    "reported_allowance",
                )
                self.assertEqual(
                    state["relation:mira:read_messages:vale"].value,
                    "denied",
                )
                answer = answer_explicit_scene_question([
                    initial, correction,
                    "In the fictional scene, may Nia read Omar's messages?",
                ])
                self.assertEqual(answer.answer, "UNKNOWN")
                self.assertEqual(answer.status, "UNRESOLVED")
                self.assertEqual(answer.evidence, (
                    (correction.removeprefix("Correction: ").removesuffix("."), 2),
                ))
                self.assertFalse(answer.external_effect_authorized)

    def test_later_uncertain_same_pair_invalidates_stale_allowance(self):
        turns=[
            "State: Nia may read Omar's messages; Mira may not read Vale's messages.",
            "Correction: Nia might be allowed to read Omar's messages.",
        ]
        state=reconstruct(turns)
        self.assertEqual(state["relation:nia:read_messages:omar"].status, "UNRESOLVED")
        self.assertIsNone(state["relation:nia:read_messages:omar"].value)
        self.assertEqual(state["relation:mira:read_messages:vale"].value,"denied")
        answer=answer_explicit_scene_question(turns+[
            "In the fictional scene, may Nia read Omar's messages?",
        ])
        self.assertEqual(answer.answer,"UNKNOWN")
        self.assertEqual(answer.status,"UNRESOLVED")
        self.assertEqual(answer.evidence,(("Nia might be allowed to read Omar's messages",2),))

    def test_latest_explicit_now_read_statement_supersedes_stale_denial(self):
        result=answer_explicit_scene_question([
            "State: Nia may not read Omar's messages.",
            "Correction: Nia may now read Omar's messages.",
            "In the fictional scene, may Nia read Omar's messages?",
        ])
        self.assertEqual(result.answer,
            "Yes, in the fictional scene, Nia may read Omar's messages.")
        self.assertEqual(result.evidence,(("Nia may now read Omar's messages",2),))
        self.assertFalse(result.external_effect_authorized)

    def test_unknown_pair_avoids_model_guess_and_unmarked_claim_does_not_admit(self):
        result=route_scene_reply([
            "State: Nia may not read Omar's messages.",
            "In the fictional scene, may Nia read Vale's messages?",
        ], lambda: self.fail("unknown source relation must not be guessed"))
        self.assertEqual(result.answer,"UNKNOWN")
        self.assertEqual(result.status,"UNRESOLVED")
        unknown=route_scene_reply([
            "Nia may not read Omar's messages.",
            "In the fictional scene, may Nia read Omar's messages?",
        ], lambda: self.fail("unmarked claims have no admitted source"))
        self.assertEqual(unknown.answer,"UNKNOWN")
        self.assertFalse(unknown.model_used)

    def test_frozen_ten_case_fixture_source_integrity_and_all_answers(self):
        import json
        from pathlib import Path
        fixture=Path(__file__).resolve().parents[1] / (
            "evaluations/social_fictional_message_boundary_v1.json"
        )
        data=json.loads(fixture.read_bytes())
        self.assertEqual(data["schema"], "VERA_SOCIAL_FICTIONAL_MESSAGE_BOUNDARY_V1")
        self.assertEqual(len(data["cases"]),10)
        self.assertEqual(len({x["id"] for x in data["cases"]}),10)
        for case in data["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case), {"id","turns","expected_answer"})
                self.assertIn(
                    "In the fictional scene, may ", case["turns"][-1]
                )
                direct=route_scene_reply(
                    case["turns"],
                    lambda: self.fail("exact fictional source must bypass model"),
                )
                self.assertEqual(direct.answer,case["expected_answer"])
                self.assertFalse(direct.model_used)
                self.assertFalse(direct.external_effect_authorized)
                self.assertFalse(direct.canonical_memory_admitted)
                for quote,n in direct.evidence:
                    self.assertIn(quote,case["turns"][n-1])

    def test_json_cli_routes_fictional_claim_without_ollama_or_permissions(self):
        import json
        from pathlib import Path
        import subprocess
        import sys
        root=Path(__file__).resolve().parents[1]
        cmd=[
            sys.executable,str(root/"scripts"/"route_social_scene.py"),
            "--model","qwen3:4b-instruct"
        ]
        turns=[
            "State: Nia may not read Omar's messages.",
            "In the fictional scene, may Nia read Omar's messages?",
        ]
        proc=subprocess.run(cmd,input=json.dumps({"user_turns":turns}),
            text=True,capture_output=True,cwd=root,timeout=18)
        self.assertEqual(proc.returncode,0,proc.stderr)
        data=json.loads(proc.stdout)
        self.assertEqual(data["answer"],
            "No, in the fictional scene, Nia may not read Omar's messages.")
        self.assertFalse(data["model_used"])
        self.assertIsNone(data["model"])
        self.assertFalse(data["external_effect_authorized"])
        self.assertFalse(data["canonical_memory_admitted"])
        self.assertFalse(data["actual_user_identity_verified"])
        self.assertEqual(data["scope"],"READ_ONLY_FICTIONAL_SCENE")

    def test_plain_real_permission_question_is_outside_narrow_scene_scope(self):
        self.assertIsNone(answer_explicit_scene_question([
            "State: Nia may not read Omar's messages.",
            "May Nia read Omar's messages?",
        ]))
        result=route_scene_reply([
            "State: Nia may not read Omar's messages.",
            "May Nia read Omar's messages?",
        ], lambda: "Ask Omar directly.")
        self.assertTrue(result.model_used)
        self.assertEqual(result.status,"MODEL_UNVERIFIED")
