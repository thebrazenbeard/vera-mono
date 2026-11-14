"""Opt-in donor guidance must preserve the literal request and no-effect boundary."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import route_social_scene as cli


class TestPersonificationAdvisory(unittest.TestCase):
    def note(self, plan, literal="Describe a fictional corridor."):
        make = getattr(cli, "note_from_personification_plan", None)
        self.assertIsNotNone(make, "missing safe personification guidance adapter")
        return make(plan, literal)

    def test_direct_answer_target_is_preserved_without_permission(self):
        request = "Describe a fictional corridor."
        plan = SimpleNamespace(
            answer_target=request,
            answer_literal_request_first=True,
            register=SimpleNamespace(value="DIRECT"),
            humor_allowed=False,
            permission_to_act=False,
            actor_id="agent-demo",
            subject_id="subject-demo",
        )
        note, summary = self.note(plan, request)
        self.assertIn("DIRECT", note)
        self.assertIn("literal", note)
        self.assertEqual(summary["register"], "DIRECT")
        self.assertTrue(summary["literal_request_preserved"])
        self.assertFalse(summary["permission_to_act"])
        self.assertFalse(summary["humor_allowed"])

    def test_advice_must_reject_silent_rephrasing_and_fake_authority(self):
        original = "Is the pilot still Ava?"
        base = dict(
            answer_target=original, answer_literal_request_first=True,
            register=SimpleNamespace(value="CONVERSATIONAL"),
            humor_allowed=False, permission_to_act=False,
            actor_id="agent-demo", subject_id="subject-demo",
        )
        for altered in (
            {"answer_target": "Who is the pilot?"},
            {"permission_to_act": True},
            {"answer_literal_request_first": False},
            {"register": SimpleNamespace(value="OVERRIDE")},
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(ValueError):
                    self.note(SimpleNamespace(**(base | altered)), original)

    @unittest.skipUnless(
        os.environ.get("VERA_PERSONIFICATION_SAFE_CHECKOUT"),
        "external pinned Personification checkout deliberately optional",
    )
    def test_actual_pinned_personification_source_plans_fictional_reply(self):
        source = Path(os.environ["VERA_PERSONIFICATION_SAFE_CHECKOUT"])
        plan_from_source = getattr(cli, "plan_from_personification_checkout", None)
        self.assertIsNotNone(plan_from_source, "no real donor invocation")
        plan = plan_from_source(
            source, actor_id="agent-demo", subject_id="subject-demo",
            request="Please reconsider the fictional pilot assignment.",
            interaction_kind="CORRECTION", preferred_register="CONVERSATIONAL",
            allow_humor=True,
        )
        note, summary = self.note(plan, "Please reconsider the fictional pilot assignment.")
        self.assertEqual(summary["register"], "DIRECT")
        self.assertFalse(summary["humor_allowed"])
        self.assertFalse(summary["permission_to_act"])
        self.assertIn("literal", note)

    @unittest.skipUnless(
        os.environ.get("VERA_PERSONIFICATION_UNSAFE_CHECKOUT"),
        "untrusted predecessor checkout not required in ordinary tests",
    )
    def test_old_unsafe_checkout_rejected_before_module_import(self):
        plan_from_source = getattr(cli, "plan_from_personification_checkout", None)
        self.assertIsNotNone(plan_from_source)
        with self.assertRaises(ValueError):
            plan_from_source(
                Path(os.environ["VERA_PERSONIFICATION_UNSAFE_CHECKOUT"]),
                actor_id="agent-demo", subject_id="subject-demo",
                request="Fictional question.", interaction_kind="GENERAL",
                preferred_register="CONVERSATIONAL", allow_humor=False,
            )

    def test_optin_cli_places_plan_in_model_prompt_without_rewriting_request(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        literal = "Describe the fictional station from the pilot's seat."
        plan = SimpleNamespace(
            answer_target=literal, answer_literal_request_first=True,
            register=SimpleNamespace(value="DIRECT"), humor_allowed=False,
            permission_to_act=False, actor_id="agent-demo",
            subject_id="subject-demo",
        )
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps({
            "user_turns": ["State: Ava is the pilot.", literal],
        }).encode()), encoding="utf-8")
        seen = []
        def local_api(route, payload):
            seen.append(payload["messages"])
            return {"message": {"content": "Ava watches the station lights."}}
        output = io.StringIO()
        with (patch("sys.argv", ["route_social_scene", "--personification-checkout", "D:/synthetic-ref", "--actor-id", "agent-demo", "--subject-id", "subject-demo", "--interaction-kind", "CORRECTION"]),
              patch("sys.stdin", stdin),
              patch.object(cli, "plan_from_personification_checkout", return_value=plan, create=True),
              patch.object(cli, "local_api", side_effect=local_api),
              contextlib.redirect_stdout(output)):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][-1]["content"], literal)
        self.assertIn("DIRECT", seen[0][0]["content"])
        self.assertEqual(json.loads(output.getvalue())["personification_advisory"]["register"], "DIRECT")


if __name__ == "__main__":
    unittest.main()
