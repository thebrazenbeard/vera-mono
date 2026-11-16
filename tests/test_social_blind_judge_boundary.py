"""Hostile synthetic boundary tests for blinded local social-review evidence."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import judge_social_multiturn_blind as judge
from audit_social_multiturn_review import verified_judge_record

VALID = {
    "winner": "tie",
    "A": {"required_met": True, "forbidden_present": False, "evidence": "A corrected the role."},
    "B": {"required_met": True, "forbidden_present": False, "evidence": "B corrected the role."},
}
DUPLICATE = json.dumps(VALID).replace('"winner": "tie"', '"winner": "A", "winner": "B"')

def reply(content=None):
    return {
        "model": judge.JUDGE_MODEL, "done": True, "done_reason": "stop",
        "eval_count": 25,
        "message": {"role": "assistant", "content": json.dumps(VALID) if content is None else content},
    }

class TestSocialBlindJudgeBoundary(unittest.TestCase):
    def test_judge_transport_rejects_contradictory_or_incomplete_response(self):
        changes = [
            ("wrong model", {"model": "unrelated-model"}),
            ("missing model", {"model": None}),
            ("not done", {"done": False}),
            ("string done", {"done": "true"}),
            ("unknown reason", {"done_reason": "unexpected"}),
            ("boolean token count", {"eval_count": True}),
            ("negative tokens", {"eval_count": -1}),
            ("wrong role", {"message": {"role": "tool", "content": "result"}}),
            ("tool call", {"message": {"role": "assistant", "content": "result", "tool_calls": [{"name": "x"}]}}),
            ("blank content", {"message": {"role": "assistant", "content": " "}}),
        ]
        for name, fields in changes:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    judge.validate_judge_transport({**reply(), **fields}, expected_model=judge.JUDGE_MODEL)

    def test_valid_judge_transport_allows_nonempty_json_text(self):
        self.assertEqual(
            judge.validate_judge_transport(reply(), expected_model=judge.JUDGE_MODEL),
            json.dumps(VALID),
        )

    def test_review_json_rejects_ambiguous_and_nonstandard_values(self):
        for malformed in (DUPLICATE, '{"winner":"A","A":{"evidence":"first","evidence":"second"},"B":{}}', '{"winner":NaN}'):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    judge.strict_review_json(malformed)

    def test_auditor_rejects_laundered_duplicate_winner(self):
        record = {
            "schema": "VERA_SOCIAL_MULTITURN_MODEL_REVIEW_V1",
            "parsed_valid": True,
            "judgment": json.loads(DUPLICATE),
            "raw_response": DUPLICATE,
        }
        with self.assertRaises(ValueError):
            verified_judge_record(record)

    def _drive_runner(self, response):
        with tempfile.TemporaryDirectory(prefix="judge-boundary-synthetic-") as root:
            blind = Path(root) / "blind.jsonl"
            out = Path(root) / "review.jsonl"
            blind.write_text(json.dumps({
                "schema": "VERA_SOCIAL_MULTITURN_BLIND_PAIR_V1",
                "case_id": "fictional-1", "user_turns": ["A?", "Correction", "Now?"],
                "criteria": {"required": ["correction"], "forbidden": ["invention"]},
                "A": [], "B": [],
            }) + "\n", encoding="utf-8")
            def ollama(route, payload=None):
                if route == "/api/tags":
                    return {"models": [{"name": judge.JUDGE_MODEL, "digest": "synthetic-only"}]}
                if route == "/api/chat":
                    return response
                raise AssertionError(route)
            with patch.object(sys, "argv", ["judge", "--blind", str(blind), "--out", str(out), "--limit", "1"]), \
                 patch.object(judge, "ollama", side_effect=ollama), \
                 contextlib.redirect_stdout(io.StringIO()):
                if response.get("model") != judge.JUDGE_MODEL:
                    with self.assertRaises(ValueError):
                        judge.main()
                    self.assertTrue(not out.exists() or out.read_bytes() == b"",
                                    "wrong judge model must not produce a labeled review row")
                else:
                    self.assertEqual(judge.main(), 0)
                    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(len(rows), 1)
                    return rows[0]

    def test_runner_rejects_wrong_judge_model_before_logging(self):
        self._drive_runner({**reply(), "model": "wrong-model"})

    def test_runner_records_duplicate_key_judgment_as_invalid(self):
        row = self._drive_runner(reply(DUPLICATE))
        self.assertIs(row["parsed_valid"], False)
        self.assertIsNone(row["judgment"])
        self.assertEqual(row["raw_response"], DUPLICATE)
        self.assertIs(verified_judge_record(row), False)

if __name__ == "__main__":
    unittest.main()
