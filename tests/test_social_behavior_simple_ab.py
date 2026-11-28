"""Behavior A/B runner contract; does not invoke a model or use user data."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_social_behavior_simple_ab.py"
FIXTURE = ROOT / "evaluations" / "social_behavior_simple_round1_v1.json"


class TestSimpleSocialAB(unittest.TestCase):
    def test_concise_arm_is_bounded_and_does_not_leak_rubric(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from run_social_behavior_simple_ab import (
                SYSTEM_CONCISE, messages_for_arm,
            )
        finally:
            sys.path.pop(0)
        self.assertLess(len(SYSTEM_CONCISE), 550)
        fixture = json.loads(FIXTURE.read_text(encoding="utf8"))
        messages = messages_for_arm(fixture["cases"][0], "concise")
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0]["content"], SYSTEM_CONCISE)
        self.assertNotIn("required", json.dumps(messages))
        self.assertNotIn("forbidden", json.dumps(messages))

    def test_verbatim_correction_reminder_is_only_from_user_text(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from run_social_behavior_simple_ab import (
                render_turn, messages_for_arm, SYSTEM_CONCISE,
            )
        finally:
            sys.path.pop(0)
        novel = json.loads(
            (ROOT / "evaluations" / "social_actor_correction_novel_v1.json").read_text(encoding="utf8")
        )
        for case in novel["cases"]:
            self.assertEqual(render_turn(case, "echo", 1), case["turns"][0])
            self.assertEqual(render_turn(case, "echo", 2), case["turns"][1])
            last = render_turn(case, "echo", 3)
            self.assertIn(case["turns"][1], last)
            self.assertIn(case["turns"][2], last)
            self.assertNotIn("required", last)
            self.assertNotIn("forbidden", last)
            self.assertEqual(
                messages_for_arm(case, "echo")[0]["content"],
                SYSTEM_CONCISE,
            )
            self.assertEqual(
                render_turn(case, "concise", 3), case["turns"][2]
            )

    def test_actor_grounding_arm_keeps_rubric_private(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from run_social_behavior_simple_ab import (
                SYSTEM_ACTOR, messages_for_arm,
            )
        finally:
            sys.path.pop(0)
        self.assertLess(len(SYSTEM_ACTOR), 750)
        novel = json.loads(
            (ROOT / "evaluations" / "social_actor_correction_novel_v1.json").read_text(encoding="utf8")
        )
        self.assertEqual(len(novel["cases"]), 6)
        for row in novel["cases"]:
            messages = messages_for_arm(row, "actor")
            self.assertEqual(len(messages), 4)
            self.assertEqual(messages[0]["content"], SYSTEM_ACTOR)
            self.assertEqual(
                [m["content"] for m in messages[1:]], row["turns"]
            )
            self.assertNotIn("required", json.dumps(messages))
            self.assertNotIn("forbidden", json.dumps(messages))

    def test_synthetic_scenarios_predeclared_and_no_model_call_in_dry_run(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf8"))
        self.assertEqual(fixture["schema"], "VERA_SOCIAL_MULTITURN_HELDOUT_V1")
        self.assertEqual(len(fixture["cases"]), 6)
        for row in fixture["cases"]:
            self.assertEqual(len(row["turns"]), 3)
            self.assertTrue(row["criteria"]["required"])
            self.assertTrue(row["criteria"]["forbidden"])
        self.assertTrue(SCRIPT.is_file(), "simple A/B runner absent")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--fixture", str(FIXTURE),
             "--dry-run"],
            capture_output=True, text=True, timeout=12,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY_RUN_VALIDATED=6", result.stdout)

    def test_same_model_two_short_style_arms_no_private_rubric_in_messages(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from run_social_behavior_simple_ab import (
                SYSTEM_BASE, SYSTEM_FOCUS, messages_for_arm,
            )
        finally:
            sys.path.pop(0)
        self.assertLess(len(SYSTEM_FOCUS), 700)
        self.assertNotEqual(SYSTEM_BASE, SYSTEM_FOCUS)
        row = json.loads(FIXTURE.read_text(encoding="utf8"))["cases"][0]
        for arm in ("base", "focus"):
            messages = messages_for_arm(row, arm)
            self.assertEqual(messages[0]["role"], "system")
            self.assertEqual([x["content"] for x in messages[1:]], row["turns"])
            self.assertNotIn("required", json.dumps(messages))
            self.assertNotIn("forbidden", json.dumps(messages))


if __name__ == "__main__":
    unittest.main()
