"""Checks source-backed state card, shared-prefix comparison and strict scoring."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class TestActiveStateLongEval(unittest.TestCase):
    def test_long_fixture_is_fixed_and_source_cards_are_anchored(self):
        from run_social_active_state_eval import validate_fixture, final_messages
        from vera_core.social_active_state import reconstruct
        rows = json.loads(
            (ROOT / "evaluations" / "social_active_state_long_v1.json").read_text(encoding="utf8")
        )
        validate_fixture(rows)
        self.assertEqual(len(rows["cases"]), 8)
        for case in rows["cases"]:
            self.assertIn(len(case["turns"]), (5, 6))
            self.assertTrue(case["expected"])
            state = reconstruct(case["turns"][:-1])
            self.assertEqual(set(state), set(case["tracked_keys"]))
            for entry in state.values():
                self.assertIn(entry.quote, case["turns"][entry.turn_index - 1])
            prior = [{"role":"system","content":"baseline"}]
            basic, basic_note = final_messages(case, "baseline", prior)
            stateful, state_note = final_messages(case, "state", prior)
            self.assertEqual(basic[-1], stateful[-1])
            self.assertEqual(basic[-1]["content"], case["turns"][-1])
            self.assertEqual(basic_note, "")
            self.assertTrue(state_note)
            self.assertIn("user turn", state_note)
            self.assertNotIn("tracked_keys", state_note)
            self.assertNotIn("expected", state_note)
            self.assertNotIn(case["expected"]+" [answer]", state_note)

    def test_raw_local_model_records_are_source_bound_and_scored(self):
        import hashlib
        from run_social_active_state_eval import score_answer
        from vera_core.social_active_state import reconstruct, render_state
        root = ROOT / "evaluations"
        fixture_path = root / "social_active_state_long_v1.json"
        raw = fixture_path.read_bytes()
        fixture_hash = hashlib.sha256(raw).hexdigest()
        cases = {
            c["id"]: c for c in json.loads(raw)["cases"]
        }
        for filename, expected in (
            ("social_active_state_long_qwen08_seed41_20261114.jsonl",
             {"baseline": 3, "state": 5}),
            ("social_active_state_long_qwen4b_seed41_20261114.jsonl",
             {"baseline": 7, "state": 7}),
        ):
            with self.subTest(filename=filename):
                rows = [
                    json.loads(s) for s in
                    (root / filename).read_text(encoding="utf8").splitlines()
                ]
                self.assertEqual(len(rows), 49)
                self.assertEqual(len({r["model_digest"] for r in rows}), 1)
                self.assertTrue(all(
                    r["fixture_sha256"] == fixture_hash
                    and r["tool_use"] is False
                    for r in rows
                ))
                observed = {"baseline": 0, "state": 0}
                for case_id, case in cases.items():
                    shared = [
                        r for r in rows
                        if r["case_id"] == case_id and r["arm"] == "shared"
                    ]
                    self.assertEqual(len(shared), len(case["turns"])-1)
                    for row in shared:
                        self.assertEqual(
                            row["user"], case["turns"][row["turn_index"]-1]
                        )
                    finals = [
                        r for r in rows
                        if r["case_id"] == case_id
                        and r["arm"] in ("baseline", "state")
                    ]
                    self.assertEqual({r["arm"] for r in finals},
                                     {"baseline", "state"})
                    for row in finals:
                        score = score_answer(case["expected"], row["response"])
                        self.assertIs(score, row["answer_correct"])
                        observed[row["arm"]] += int(score)
                        if row["arm"] == "state":
                            note = render_state(
                                reconstruct(case["turns"][:-1])
                            )
                            self.assertEqual(
                                row["source_card_sha256"],
                                hashlib.sha256(note.encode()).hexdigest()
                            )
                self.assertEqual(observed, expected)

    def test_source_only_cli_exposes_verified_answers_not_inferred_story(self):
        import subprocess
        fixture = ROOT / "evaluations" / "social_active_state_long_v1.json"
        cli = ROOT / "scripts" / "answer_social_active_state.py"
        process = subprocess.run(
            [sys.executable, str(cli), "--fixture", str(fixture)],
            capture_output=True, text=True, timeout=14,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = [json.loads(s) for s in process.stdout.splitlines()]
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[-1]["correct"], 8)
        self.assertFalse(rows[-1]["live_memory_admission"])
        self.assertTrue(all(row["correct"] for row in rows[:-1]))
        self.assertTrue(all(not row["external_effect_authorized"]
                            for row in rows[:-1]))

    def test_only_one_name_or_exact_typed_answer_scores(self):
        from run_social_active_state_eval import score_answer
        self.assertTrue(score_answer("Kira", "Kira."))
        self.assertTrue(score_answer("UNKNOWN", "unknown"))
        self.assertTrue(score_answer("spacecraft, green", "spacecraft, green."))
        self.assertFalse(score_answer("UNKNOWN", "Probably Tessa"))
        self.assertFalse(score_answer("Ben", "Ava"))
        self.assertFalse(score_answer("Ivo, red", "Ivo, blue"))
        self.assertFalse(score_answer("Ben", "Ben or Ava"))


if __name__ == "__main__":
    unittest.main()
