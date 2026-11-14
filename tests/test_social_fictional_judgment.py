"""Permit asked-for fiction without false factual or personal claims."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import run_social_behavior_simple_ab as runner
class TestFictionalJudgment(unittest.TestCase):
    def test_optional_fictional_arm_does_not_rewrite_user_data(self):
        prompt=runner.SYSTEM_FICTIONAL_JUDGMENT
        self.assertLess(len(prompt),850)
        for word in ("fiction","provisional","disagree","actor","warm"):
            self.assertIn(word,prompt.lower())
        self.assertNotEqual(prompt,runner.SYSTEM_JUDGMENT_V3)
        cases=json.loads((ROOT/"evaluations"/"social_judgment_v3_unseen_v1.json").read_text(encoding="utf-8-sig"))["cases"]
        for case in cases:
            actual=runner.messages_for_arm(case,"fictional")
            self.assertEqual(actual[0]["content"],prompt)
            self.assertEqual([x["content"] for x in actual[1:]],case["turns"])
            self.assertNotIn('"required"',json.dumps(actual))
            self.assertNotIn('"forbidden"',json.dumps(actual))
        self.assertEqual(runner.messages_for_arm(cases[0],"base")[0]["content"],runner.SYSTEM_BASE)
    def test_existing_runner_accepts_fictional_arm_without_model(self):
        p=subprocess.run([sys.executable,str(ROOT/"scripts"/"run_social_behavior_simple_ab.py"),
            "--fixture",str(ROOT/"evaluations"/"social_judgment_v3_unseen_v1.json"),
            "--arms","judgment_v3,fictional","--limit","8","--dry-run"],
            capture_output=True,text=True,cwd=ROOT,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn("DRY_RUN_VALIDATED=8",p.stdout)

    def test_worker_frozen_six_case_holdout_uses_real_runner_without_rubric(self):
        import hashlib
        from run_social_multiturn_eval import validate_fixture
        raw=(ROOT/"evaluations"/"social_fictional_holdout_v1.json").read_bytes()
        fixture=json.loads(raw)
        validate_fixture(fixture)
        self.assertEqual(len(fixture["cases"]),6)
        self.assertEqual(len({row["id"] for row in fixture["cases"]}),6)
        self.assertEqual(hashlib.sha256(runner.SYSTEM_FICTIONAL_JUDGMENT.encode()).hexdigest(),
            "5e9e7b9dc97be0c0174e5ddc612d767bce1435b1dcd71b0945323ba09df39320")
        for row in fixture["cases"]:
            for arm in ("judgment_v3","fictional"):
                messages=runner.messages_for_arm(row,arm)
                self.assertEqual([x["content"] for x in messages[1:]],row["turns"])
                self.assertNotIn('"required"',json.dumps(messages))
                self.assertNotIn('"forbidden"',json.dumps(messages))
