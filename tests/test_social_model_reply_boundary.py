"""Fail closed when the local inference transport contradicts its claimed model."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_social_behavior_simple_ab as ab

MODEL = "qwen3.5:0.8b"


def valid_reply() -> dict:
    return {
        "model": MODEL, "done": True, "done_reason": "stop",
        "eval_count": 12,
        "message": {"role": "assistant", "content": "I would revise that claim.",
                    "tool_calls": []},
    }


class ModelReplyBoundaryTests(unittest.TestCase):
    def test_transport_must_identify_expected_model_and_completed_assistant_reply(self):
        mutations = [
            ("model", "another:tag", "model"),
            ("model", None, "model"),
            ("done", False, "done"),
            ("done", "true", "done"),
            ("done_reason", "unknown", "done_reason"),
            ("done_reason", None, "done_reason"),
            ("eval_count", True, "eval_count"),
            ("eval_count", -1, "eval_count"),
            ("message.role", "tool", "role"),
            ("message.content", " ", "content"),
            ("message.tool_calls", [{"function": {"name": "delete"}}], "tool_calls"),
        ]
        for field, corrupted, reason in mutations:
            with self.subTest(field=field, corrupted=corrupted):
                reply = valid_reply()
                if "." in field:
                    outer, inner = field.split(".")
                    reply[outer][inner] = corrupted
                else:
                    reply[field] = corrupted
                with self.assertRaisesRegex(ValueError, reason):
                    ab.validate_model_reply(reply, expected_model=MODEL)

    def test_valid_reply_permits_empty_tool_list_and_length_truncation(self):
        for done_reason in ("stop", "length"):
            with self.subTest(reason=done_reason):
                reply = valid_reply()
                reply["done_reason"] = done_reason
                self.assertEqual(ab.validate_model_reply(reply, expected_model=MODEL),
                                 "I would revise that claim.")

    def test_runner_rejects_misidentified_model_before_writing_row(self):
        with TemporaryDirectory() as d:
            fixture = ROOT / "evaluations" / "social_behavior_simple_round1_v1.json"
            out = Path(d) / "wrong-model.jsonl"
            bad = valid_reply()
            bad["model"] = "a different model"
            argv = ["runner", "--fixture", str(fixture), "--output", str(out),
                    "--model", MODEL, "--seeds", "79", "--limit", "1",
                    "--arms", "base,judgment_v3"]
            def local(route, payload=None):
                if route == "/api/tags":
                    return {"models": [{"name": MODEL, "digest": "known-local-tag"}]}
                self.assertEqual(payload["model"], MODEL)
                return bad
            with patch.object(ab, "local_api", side_effect=local), \
                 patch.object(sys, "argv", argv):
                with self.assertRaisesRegex(ValueError, "model"):
                    ab.main()
            self.assertEqual(out.read_bytes(), b"")

    def test_runner_writes_synthetic_response_rows_only_after_validation(self):
        with TemporaryDirectory() as d:
            fixture = ROOT / "evaluations" / "social_behavior_simple_round1_v1.json"
            out = Path(d) / "synthetic.jsonl"
            argv = ["runner", "--fixture", str(fixture), "--output", str(out),
                    "--model", MODEL, "--seeds", "79", "--limit", "1",
                    "--arms", "base,judgment_v3"]
            def local(route, payload=None):
                if route == "/api/tags":
                    return {"models": [{"name": MODEL, "digest": "known-local-tag"}]}
                self.assertEqual(payload["model"], MODEL)
                return valid_reply()
            with patch.object(ab, "local_api", side_effect=local), \
                 patch.object(sys, "argv", argv):
                self.assertEqual(ab.main(), 0)
            rows = [json.loads(s) for s in out.read_text(encoding="utf8").splitlines()]
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(r["model"] == MODEL and r["model_digest"] == "known-local-tag"
                                for r in rows))
            self.assertTrue(all("model_response_authenticated" not in r for r in rows))


if __name__ == "__main__":
    unittest.main()
