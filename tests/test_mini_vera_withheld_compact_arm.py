"""Four-arm masked Mini-Vera evaluation: reuse the existing multi-turn evaluator."""
from __future__ import annotations

import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_mini_vera_loopback import FakeLocal, candidate, response
from tests.test_mini_vera_withheld_dialogue import synthetic_scenario
from tools.mini_vera import compose, loopback, withheld_dialogue as evaluator


ROOT = Path(__file__).resolve().parents[1]


def empty_request():
    request = candidate()
    user = json.loads(request["inference"]["messages"][-1]["content"])
    user["project_context_untrusted"] = []
    request["inference"]["messages"][-1]["content"] = loopback.canonical(user).decode()
    request["request_sha256"] = loopback.sha256(loopback.canonical(request["inference"]))
    return request


class MiniVeraMaskedCompactTests(unittest.TestCase):
    def test_four_arm_preparation_only_for_empty_context(self):
        prepared = evaluator.prepare(empty_request(), synthetic_scenario(),
                                     include_compact=True)
        self.assertEqual(set(prepared["instructions"]), {
            "bare_natural", "minimal_natural", "governed_natural",
            "compact_natural"})
        self.assertEqual(prepared["instructions"]["compact_natural"],
                         [{"role": "system", "content": compose.COMPACT_DIALOGUE_SYSTEM}])
        self.assertEqual(prepared["records"], [])

    def test_compact_refuses_project_records_even_if_marked_public(self):
        with patch.object(evaluator.blind_compare, "_one_call") as call:
            with self.assertRaises(loopback.LoopbackRejected):
                evaluator.prepare(candidate(), synthetic_scenario(),
                                  include_compact=True)
            call.assert_not_called()

    def test_four_arm_real_http_shape_and_masked_mapping(self):
        with FakeLocal() as fake:
            sheet, key = evaluator.compare(
                empty_request(), synthetic_scenario(),
                endpoint=fake.url, rng=random.Random(20),
                include_compact=True, ollama_disable_thinking=True,
                max_output_tokens=256)
        self.assertEqual(8, len(fake.requests))
        self.assertEqual(8, key["evidence"]["calls"])
        self.assertEqual(set(key["arm_by_label"].values()), {
            "bare_natural", "minimal_natural", "governed_natural",
            "compact_natural"})
        self.assertEqual(set(key["arm_by_label"].keys()), set("ABCD"))
        self.assertEqual(len(sheet["transcripts_by_masked_label"]), 4)
        self.assertNotIn("arm_by_label", sheet)
        self.assertNotIn("call_order_by_turn", sheet)
        self.assertNotIn("latency_ms", json.dumps(sheet))
        self.assertEqual(key["rater_sheet_sha256"],
                         loopback.sha256(loopback.canonical(sheet)))
        self.assertEqual(2, len(key["call_order_by_turn"]))
        self.assertTrue(all(set(order) == set("ABCD")
                            for order in key["call_order_by_turn"]))
        self.assertTrue(all(body["reasoning_effort"] == "none"
                            and body["max_tokens"] == 256
                            and body["seed"] == 20261106
                            for _, body, _ in fake.requests))
        first_questions = {body["messages"][-1]["content"]
                           for _, body, _ in fake.requests
                           if sum(m["role"] == "user" for m in body["messages"]) == 1}
        self.assertEqual(first_questions, {"What can you verify?"})
        self.assertEqual(key["evidence"]["behavioral_qualification"],
                         "NOT_TESTED")

    def test_four_arm_truncation_invalidates_trial_not_silent_score(self):
        truncated = response(text="unfinished")
        truncated["choices"][0]["finish_reason"] = "length"
        with FakeLocal(answer=truncated) as fake:
            with self.assertRaises(evaluator.DialogueAborted) as exc:
                evaluator.compare(empty_request(), synthetic_scenario(),
                                  endpoint=fake.url, include_compact=True,
                                  rng=random.Random(4))
        self.assertEqual("TRUNCATED_REPLY", exc.exception.reason_code)
        self.assertEqual(1, exc.exception.attempted)
        self.assertEqual(1, len(fake.requests))

    def test_cli_real_fake_server_with_four_arm_opt_in(self):
        with tempfile.TemporaryDirectory() as temp, FakeLocal() as fake:
            p = Path(temp)
            request = p / "source.json"
            scenario = p / "scenario.json"
            sheet = p / "sheet.json"
            key = p / "key.json"
            request.write_bytes(loopback.canonical(empty_request()))
            scenario.write_bytes(loopback.canonical(synthetic_scenario()))
            cmd = [sys.executable, str(ROOT / "tools/mini_vera/withheld_dialogue.py"),
                   "--request", str(request), "--scenario", str(scenario),
                   "--endpoint", fake.url,
                   "--rater-sheet", str(sheet), "--private-key", str(key),
                   "--include-compact", "--ollama-disable-thinking",
                   "--max-output-tokens", "256"]
            dry = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            self.assertEqual(0, dry.returncode, dry.stderr)
            self.assertEqual(0, len(fake.requests))
            live = subprocess.run(cmd + ["--execute", "--host-idle-confirmed"],
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(0, live.returncode, live.stderr)
            self.assertEqual(8, len(fake.requests))
            self.assertEqual("NOT_ESTABLISHED", json.loads(sheet.read_text())["qualification"])
            self.assertEqual(8, json.loads(key.read_text())["evidence"]["calls"])


if __name__ == "__main__":
    unittest.main()
