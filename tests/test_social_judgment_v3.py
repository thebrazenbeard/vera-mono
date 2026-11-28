"""Narrow provisional-judgment third candidate; source-only evaluation contract."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_social_behavior_simple_ab as runner


class TestJudgmentV3(unittest.TestCase):
    def test_optin_arm_preserves_original_user_turns_and_base(self):
        prompt = runner.SYSTEM_JUDGMENT_V3
        self.assertLess(len(prompt), 1250)
        for idea in ("provisional", "disagree", "who", "motive", "warm"):
            self.assertIn(idea, prompt.lower())
        self.assertNotEqual(prompt, runner.SYSTEM_JUDGMENT_V2)
        cases = json.loads(
            (ROOT / "evaluations" / "social_judgment_novel_v1.json")
            .read_text(encoding="utf-8-sig")
        )["cases"]
        for row in cases:
            msgs = runner.messages_for_arm(row, "judgment_v3")
            self.assertEqual([x["content"] for x in msgs[1:]], row["turns"])
            self.assertEqual(msgs[0]["content"], prompt)
            self.assertNotIn('"required"', json.dumps(msgs))
            self.assertNotIn('"forbidden"', json.dumps(msgs))
        self.assertEqual(
            runner.messages_for_arm(cases[0], "base")[0]["content"],
            runner.SYSTEM_BASE,
        )
        self.assertEqual(
            runner.messages_for_arm(cases[0], "judgment_v2")[0]["content"],
            runner.SYSTEM_JUDGMENT_V2,
        )

    def test_existing_runner_accepts_v2_v3_trial_without_model(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_social_behavior_simple_ab.py"),
             "--fixture", str(ROOT / "evaluations" / "social_judgment_novel_v1.json"),
             "--arms", "judgment_v2,judgment_v3", "--limit", "8", "--dry-run"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("DRY_RUN_VALIDATED=8", run.stdout)

    def test_emission_includes_no_invented_synthetic_criteria(self):
        case = {
            "id": "synthetic_new",
            "turns": ["A fictional scene", "A direct correction", "Please make a choice"],
            "criteria": {"required": ["secret grading"], "forbidden": ["anything else"]},
        }
        msg = runner.messages_for_arm(case, "judgment_v3")
        self.assertNotIn("secret grading", json.dumps(msg))
        self.assertNotIn("anything else", json.dumps(msg))


if __name__ == "__main__":
    unittest.main()
