"""Deterministic narrow scoring of fictional actor/revision dialogue trials."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from score_social_actor_correction import audit_and_score

class TestActorScorer(unittest.TestCase):
    def test_real_local_model_logs_have_reproducible_scores(self):
        fixture = ROOT / "evaluations" / "social_actor_correction_novel_v1.json"
        expected = {
            "social_actor_correction_qwen35_base_actor_seed37_20261114.jsonl":
                {"concise": 3, "actor": 3},
            "social_actor_correction_qwen35_echo_seed37_20261114.jsonl":
                {"echo": 4},
            "social_actor_correction_qwen4b_concise_seed37_20261114.jsonl":
                {"concise": 6},
        }
        for filename, scores in expected.items():
            with self.subTest(filename=filename):
                result = audit_and_score(
                    fixture,
                    ROOT / "evaluations" / filename,
                )
                self.assertEqual(result["scores"], scores)
                self.assertEqual(result["invalid_records"], 0)
                self.assertEqual(result["cases_per_arm"], 6)
                self.assertFalse(result["independent_human_qualified"])

    def test_wrong_responses_never_count_as_correct(self):
        from score_social_actor_correction import match_final
        self.assertFalse(match_final("demand_actor", "Marco"))
        self.assertFalse(match_final("loan_direction", "Quinn is borrower"))
        self.assertFalse(match_final("pilot_swap", "Pia"))
        self.assertFalse(match_final("partial_update", "Nora, blue"))
        self.assertFalse(match_final("current_topic_choice", "I have no preferences"))
        self.assertTrue(match_final("partial_update", "Ivo is the messenger carrying a red card."))
        self.assertTrue(match_final("current_topic_choice", "Botany."))

if __name__ == "__main__":
    unittest.main()
