"""Synthetic test gates for the fixed multi-turn benchmark and blinded review."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_social_multiturn_eval import validate_fixture
from prepare_social_multiturn_blind import build_pairs, MODELS
from judge_social_multiturn_blind import validate_judge_output
from audit_social_multiturn_review import audit, swap_stable_winner


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


    def test_audit_rejects_duplicate_rows_even_with_consistent_hashes(self):
        evidence = Path(__file__).resolve().parents[1] / "evaluations"
        paths = [
            evidence / "social_multiturn_heldout_v1.json",
            evidence / "social_multiturn_qwen_vs_successor_seed31_20261114.jsonl",
            evidence / "social_multiturn_blinded_seed31_20261114.jsonl",
            evidence / "social_multiturn_blinded_reversed_v2_seed31_20261114.jsonl",
            evidence / "social_multiturn_blind_mapping_seed31_20261114.json",
            evidence / "social_multiturn_blind_review_qwen3_4b_seed9_20261114.jsonl",
            evidence / "social_multiturn_blind_reversed_review_qwen3_4b_seed9_20261114.jsonl",
        ]
        self.assertEqual(audit(*paths)["case_count"], 12)
        with tempfile.TemporaryDirectory(prefix="synthetic-review-integrity-") as root:
            for target in (1, 5):
                with self.subTest(duplicate_input=target):
                    lines = paths[target].read_text(encoding="utf8").splitlines()
                    if target == 1:
                        lines[-1] = lines[0]  # Same count; missing one model turn.
                    else:
                        lines.append(lines[0])  # Judge duplicate hidden by dict.
                    changed = Path(root) / f"input-{target}.jsonl"
                    changed.write_text("\n".join(lines) + "\n", encoding="utf8")
                    args = list(paths)
                    args[target] = changed
                    if target == 1:
                        key = json.loads(paths[4].read_text(encoding="utf8"))
                        key["generated_sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
                        mapped = Path(root) / "mapping.json"
                        mapped.write_text(json.dumps(key), encoding="utf8")
                        args[4] = mapped
                    with self.assertRaises(ValueError):
                        audit(*args)


    def test_audit_rejects_rehashed_fabricated_blind_answer(self):
        evidence = Path(__file__).resolve().parents[1] / "evaluations"
        paths = [evidence / name for name in (
            "social_multiturn_heldout_v1.json",
            "social_multiturn_qwen_vs_successor_seed31_20261114.jsonl",
            "social_multiturn_blinded_seed31_20261114.jsonl",
            "social_multiturn_blinded_reversed_v2_seed31_20261114.jsonl",
            "social_multiturn_blind_mapping_seed31_20261114.json",
            "social_multiturn_blind_review_qwen3_4b_seed9_20261114.jsonl",
            "social_multiturn_blind_reversed_review_qwen3_4b_seed9_20261114.jsonl",
        )]
        with tempfile.TemporaryDirectory(prefix="synthetic-blind-forgery-") as root:
            arguments = list(paths)
            for packet_idx, judge_idx, arm in ((2, 5, "A"), (3, 6, "B")):
                packet = [json.loads(line) for line in paths[packet_idx].read_text(encoding="utf8").splitlines()]
                packet[0][arm][2]["response"] = "Injected answer absent from model generations."
                payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in packet)
                target = Path(root) / f"packet-{packet_idx}.jsonl"
                target.write_text(payload, encoding="utf8")
                arguments[packet_idx] = target
                judge = [json.loads(line) for line in paths[judge_idx].read_text(encoding="utf8").splitlines()]
                for row in judge:
                    row["blind_packet_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                target_judge = Path(root) / f"judge-{judge_idx}.jsonl"
                target_judge.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in judge), encoding="utf8")
                arguments[judge_idx] = target_judge
            with self.assertRaises(ValueError):
                audit(*arguments)

    def test_audit_rejects_mapping_digest_tampering(self):
        evidence = Path(__file__).resolve().parents[1] / "evaluations"
        names = (
            "social_multiturn_heldout_v1.json",
            "social_multiturn_qwen_vs_successor_seed31_20261114.jsonl",
            "social_multiturn_blinded_seed31_20261114.jsonl",
            "social_multiturn_blinded_reversed_v2_seed31_20261114.jsonl",
            "social_multiturn_blind_mapping_seed31_20261114.json",
            "social_multiturn_blind_review_qwen3_4b_seed9_20261114.jsonl",
            "social_multiturn_blind_reversed_review_qwen3_4b_seed9_20261114.jsonl",
        )
        arguments = [evidence / name for name in names]
        with tempfile.TemporaryDirectory(prefix="synthetic-map-tamper-") as root:
            key = json.loads(arguments[4].read_text(encoding="utf8"))
            key["assignment"][0]["A_digest"] = "forged-model-digest"
            changed = Path(root) / "mapping.json"
            changed.write_text(json.dumps(key), encoding="utf8")
            arguments[4] = changed
            with self.assertRaises(ValueError):
                audit(*arguments)


    def test_audit_rejects_judge_verdict_laundering(self):
        evidence = Path(__file__).resolve().parents[1] / "evaluations"
        names = ("social_multiturn_heldout_v1.json",
                 "social_multiturn_qwen_vs_successor_seed31_20261114.jsonl",
                 "social_multiturn_blinded_seed31_20261114.jsonl",
                 "social_multiturn_blinded_reversed_v2_seed31_20261114.jsonl",
                 "social_multiturn_blind_mapping_seed31_20261114.json",
                 "social_multiturn_blind_review_qwen3_4b_seed9_20261114.jsonl",
                 "social_multiturn_blind_reversed_review_qwen3_4b_seed9_20261114.jsonl")
        paths = [evidence / name for name in names]
        self.assertEqual(audit(*paths)["review_gate"]["swap_stable_concrete_winners"], 0)
        source = [json.loads(line) for line in paths[5].read_text(encoding="utf8").splitlines()]
        self.assertTrue(source[1]["parsed_valid"])
        for mutation in ("verdict", "raw", "truthy_flag"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as root:
                rows = json.loads(json.dumps(source))
                if mutation == "verdict":
                    rows[1]["judgment"]["winner"] = "B"
                elif mutation == "raw":
                    raw = json.loads(rows[1]["raw_response"])
                    raw["winner"] = "B"
                    rows[1]["raw_response"] = json.dumps(raw)
                else:
                    rows[1]["parsed_valid"] = "false"
                changed = Path(root) / "forged-judge.jsonl"
                changed.write_text("".join(json.dumps(row) + "\n" for row in rows),
                                   encoding="utf8")
                args = list(paths)
                args[5] = changed
                with self.assertRaises(ValueError):
                    audit(*args)

if __name__ == "__main__":
    unittest.main()
