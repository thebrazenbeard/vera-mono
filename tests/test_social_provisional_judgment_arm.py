"""Bounded provisional-judgment candidate reuses existing social A/B runner."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_social_behavior_simple_ab as runner

class TestProvisionalJudgmentArm(unittest.TestCase):
    def test_candidate_requests_present_judgment_and_revision_not_refusal(self):
        candidate = runner.SYSTEM_PERSPECTIVE
        self.assertNotEqual(candidate, runner.SYSTEM_BASE)
        self.assertLess(len(candidate), 1150)
        for phrase in ("provisional", "revise", "disagree", "natural"):
            self.assertIn(phrase, candidate.lower())
        self.assertNotIn("old_preference", candidate)
        fixture = json.loads((ROOT / "evaluations" / "social_multiturn_heldout_v1.json").read_text(encoding="utf8"))
        self.assertEqual(len(fixture["cases"]), 12)
        for case in fixture["cases"]:
            got = runner.messages_for_arm(case, "perspective")
            self.assertEqual(got[0]["content"], candidate)
            self.assertEqual([m["content"] for m in got[1:]], case["turns"])
            self.assertNotIn('"required"', json.dumps(got))
            self.assertNotIn('"forbidden"', json.dumps(got))
        self.assertEqual(
            runner.messages_for_arm(fixture["cases"][0], "base")[0]["content"],
            runner.SYSTEM_BASE,
        )

    def test_reusable_12_case_fixture_passes_existing_runner_dryrun(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_social_behavior_simple_ab.py"),
             "--fixture", str(ROOT / "evaluations" / "social_multiturn_heldout_v1.json"),
             "--arms", "base,perspective", "--limit", "12", "--dry-run"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY_RUN_VALIDATED=12", result.stdout)

    def test_adaptive_conversational_judgment_keeps_baseline_and_case_text(self):
        candidate = runner.SYSTEM_JUDGMENT_V2
        self.assertLess(len(candidate), 1200)
        self.assertIn("provisional", candidate.lower())
        self.assertIn("disagree", candidate.lower())
        self.assertIn("correct", candidate.lower())
        self.assertIn("warm", candidate.lower())
        self.assertIn("one or two", candidate.lower())
        self.assertNotEqual(candidate, runner.SYSTEM_PERSPECTIVE)
        row = json.loads(
            (ROOT / "evaluations" / "social_multiturn_heldout_v1.json")
            .read_text(encoding="utf8")
        )["cases"][0]
        self.assertEqual(
            [m["content"] for m in runner.messages_for_arm(row, "judgment_v2")[1:]],
            row["turns"],
        )
        self.assertNotIn("required", json.dumps(runner.messages_for_arm(row, "judgment_v2")))
        self.assertEqual(
            runner.messages_for_arm(row, "base")[0]["content"],
            runner.SYSTEM_BASE,
        )


    def test_new_fictional_eight_case_fixture_keeps_rubric_out_of_prompts(self):
        from run_social_multiturn_eval import validate_fixture
        fixture = json.loads(
            (ROOT / "evaluations" / "social_judgment_novel_v1.json")
            .read_text(encoding="utf-8-sig")
        )
        validate_fixture(fixture)
        self.assertEqual(len(fixture["cases"]), 8)
        for case in fixture["cases"]:
            self.assertEqual(len(case["turns"]), 3)
            for arm in ("base", "judgment_v2"):
                messages = runner.messages_for_arm(case, arm)
                self.assertEqual(
                    [m["content"] for m in messages[1:]], case["turns"],
                )
                self.assertNotIn('"required"', json.dumps(messages))
                self.assertNotIn('"forbidden"', json.dumps(messages))


if __name__ == "__main__":
    unittest.main()
