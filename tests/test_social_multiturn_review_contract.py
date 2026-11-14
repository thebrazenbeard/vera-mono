"""Synthetic test gates for the fixed multi-turn benchmark and blinded review."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_social_multiturn_eval import validate_fixture
from prepare_social_multiturn_blind import build_pairs, MODELS
from judge_social_multiturn_blind import validate_judge_output
from audit_social_multiturn_review import swap_stable_winner


class TestMultiturnReviewContract(unittest.TestCase):
    def setUp(self):
        self.fixture = {
            "schema": "VERA_SOCIAL_MULTITURN_HELDOUT_V1",
            "cases": [
                {"id": f"case-{i}", "turns": ["First?", "Correction.", "Now answer."],
                 "criteria": {"required": ["correction"], "forbidden": ["invention"]}}
                for i in range(2)
            ],
        }
        self.raw = json.dumps(self.fixture).encode()
        self.sha = hashlib.sha256(self.raw).hexdigest()
        self.generated = [
            {
                "schema": "VERA_SOCIAL_MULTITURN_GENERATION_V1",
                "case_id": c["id"], "model": model,
                "digest": model + "-fixture-digest",
                "seed": 31, "turn_index": n,
                "fixture_sha256": self.sha, "user": c["turns"][n-1],
                "response": "Mock generated answer.", "done_reason": "stop",
                "system_override": False, "tool_use": False,
            }
            for c in self.fixture["cases"]
            for model in MODELS
            for n in range(1, 4)
        ]

    def test_valid_fixture(self):
        validate_fixture(self.fixture)

    def test_valid_generator_builds_blinded_pairs(self):
        blind, key = build_pairs(self.fixture, self.generated, self.sha)
        self.assertEqual(len(blind), 2)
        self.assertEqual(len(key), 2)
        self.assertEqual(sum(item["A"] == MODELS[0] for item in key), 1)
        self.assertNotIn(MODELS[0], json.dumps(blind))
        self.assertNotIn(MODELS[1], json.dumps(blind))

    def test_missing_response_fails_closed(self):
        with self.assertRaises(ValueError):
            build_pairs(self.fixture, self.generated[:-1], self.sha)

    def test_duplicate_response_fails_closed(self):
        with self.assertRaises(ValueError):
            build_pairs(self.fixture, self.generated[:-1] + [self.generated[0]], self.sha)

    def test_forged_fixture_hash_rejected(self):
        self.generated[0]["fixture_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            build_pairs(self.fixture, self.generated, self.sha)

    def test_swapped_user_input_rejected(self):
        self.generated[0]["user"] = "An unrelated input"
        with self.assertRaises(ValueError):
            build_pairs(self.fixture, self.generated, self.sha)

    def test_system_override_or_tools_rejected(self):
        for field in ("system_override", "tool_use"):
            with self.subTest(field=field):
                self.generated[0][field] = True
                with self.assertRaises(ValueError):
                    build_pairs(self.fixture, self.generated, self.sha)
                self.generated[0][field] = False

    def test_mixed_model_digest_rejected(self):
        self.generated[1]["digest"] = "different"
        with self.assertRaises(ValueError):
            build_pairs(self.fixture, self.generated, self.sha)

    def test_mixed_seed_rejected(self):
        self.generated[0]["seed"] = 999
        with self.assertRaises(ValueError):
            build_pairs(self.fixture, self.generated, self.sha)

    def test_incorrect_user_turn_count_rejected(self):
        self.fixture["cases"][0]["turns"] = ["single"]
        with self.assertRaises(ValueError):
            validate_fixture(self.fixture)

    def test_duplicate_case_ids_rejected(self):
        self.fixture["cases"][1]["id"] = self.fixture["cases"][0]["id"]
        with self.assertRaises(ValueError):
            validate_fixture(self.fixture)

    def test_judge_output_structure_valid(self):
        valid = {"winner": "tie",
                 "A": {"required_met": True, "forbidden_present": False, "evidence": "A responded."},
                 "B": {"required_met": None, "forbidden_present": None, "evidence": "B is unclear."}}
        self.assertTrue(validate_judge_output(valid))
        valid["B"]["forbidden_present"] = "false"
        self.assertFalse(validate_judge_output(valid))

    def test_judge_output_missing_fields_rejected(self):
        self.assertFalse(validate_judge_output({"winner": "A"}))
        self.assertFalse(validate_judge_output({"winner": "C", "A": {}, "B": {}}))

    def test_position_swap_requires_opposite_letter_to_support_same_winner(self):
        self.assertEqual("A", swap_stable_winner("A", "B"))
        self.assertEqual("B", swap_stable_winner("B", "A"))
        self.assertIsNone(swap_stable_winner("A", "A"))
        self.assertIsNone(swap_stable_winner("B", "B"))
        self.assertIsNone(swap_stable_winner("tie", "tie"))
        self.assertIsNone(swap_stable_winner(None, "A"))


if __name__ == "__main__":
    unittest.main()
