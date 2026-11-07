"""Only synthetic fake-server tests; actual withheld items stay outside Git."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_mini_vera_loopback import FakeLocal, candidate, response
from tools.mini_vera import loopback, withheld_dialogue as evaluator


ROOT = Path(__file__).resolve().parents[1]


def synthetic_scenario():
    return {"schema": "MINI_VERA_HUMAN_WITHHELD_DIALOGUE_V1",
            "case_id": "synthetic-only-not-withheld",
            "rights": dict(evaluator.RIGHTS),
            "turns": [
                {"kind": "query", "user_text": "What can you verify?"},
                {"kind": "correction", "user_text": "Correction: your prior answer lacked evidence. What is unknown?"},
            ]}


class MiniVeraWithheldDialogueTests(unittest.TestCase):
    def test_natural_same_source_evidence_and_masked_multi_turn_receipts(self):
        scenario = synthetic_scenario()
        with FakeLocal() as fake:
            sheet, key = evaluator.compare(candidate(), scenario, endpoint=fake.url,
                                           rng=random.Random(71))
        self.assertEqual(len(fake.requests), 6)
        self.assertEqual(key["evidence"]["calls"], 6)
        self.assertEqual(sheet["trial_id"], key["trial_id"])
        self.assertEqual(key["rater_sheet_sha256"], loopback.sha256(loopback.canonical(sheet)))
        self.assertEqual(set(key["arm_by_label"].values()),
                         {"bare_natural", "minimal_natural", "governed_natural"})
        self.assertNotIn("arm_by_label", sheet)
        self.assertNotIn("latency_ms", json.dumps(sheet))
        self.assertNotIn("call_order_by_turn", sheet)
        self.assertEqual(len(key["call_order_by_turn"]), 2)
        self.assertTrue(all(set(order) == {"A", "B", "C"}
                            for order in key["call_order_by_turn"]))
        self.assertEqual(len(sheet["transcripts_by_masked_label"]), 3)
        self.assertEqual(sheet["turn_kinds"], ["query", "correction"])
        self.assertEqual({len(x) for x in sheet["transcripts_by_masked_label"].values()}, {2})
        self.assertTrue(all(x[1]["user"].startswith("Correction:")
                            for x in sheet["transcripts_by_masked_label"].values()))
        first_turn_payloads = [payload for _, payload, _ in fake.requests
                               if len([m for m in payload["messages"] if m["role"] == "user"]) == 1]
        self.assertEqual(len(first_turn_payloads), 3)
        self.assertEqual({p["messages"][-1]["content"] for p in first_turn_payloads},
                         {evaluator.prepare(candidate(), scenario)["questions"][0]})
        self.assertTrue(all(p["model"] == "qwen3.5-mini-local" and p["seed"] == 20261106
                            for _, p, _ in fake.requests))
        self.assertEqual(key["evidence"]["behavioral_qualification"], "NOT_TESTED")
        self.assertEqual(key["evidence"]["rights"], "OPERATOR_ASSERTED_NOT_INDEPENDENTLY_VERIFIED")

    def test_natural_baseline_plain_query_when_no_project_records(self):
        request = deepcopy(candidate())
        inner = json.loads(request["inference"]["messages"][1]["content"])
        inner["project_context_untrusted"] = []
        request["inference"]["messages"][1]["content"] = loopback.canonical(inner).decode()
        request["request_sha256"] = loopback.sha256(loopback.canonical(request["inference"]))
        config = evaluator.prepare(request, synthetic_scenario())
        self.assertEqual(config["questions"][0], "What can you verify?")
        self.assertEqual(config["records"], [])

    def test_reject_unqualified_rights_missing_correction_and_case_mismatch(self):
        for mutate in (lambda s: s["rights"].update({"training_use": "ALLOWED"}),
                       lambda s: s["turns"][1].update({"kind": "query"}),
                       lambda s: s["turns"][0].update({"user_text": "Different question"}),
                       lambda s: s["turns"][0].update({"kind": []})):
            scenario = synthetic_scenario()
            mutate(scenario)
            with self.subTest(scenario=scenario), patch.object(evaluator.blind_compare,
                                                               "_one_call") as called:
                with self.assertRaises(loopback.LoopbackRejected):
                    evaluator.prepare(candidate(), scenario)
                called.assert_not_called()

    def test_cli_validates_dry_and_sends_only_explicit_fake_loopback_calls(self):
        with tempfile.TemporaryDirectory() as temp, FakeLocal() as fake:
            root = Path(temp)
            request_path = root / "synthetic.json"
            scenario_path = root / "external-synthetic-not-withheld.json"
            sheet_path = root / "rater.json"
            key_path = root / "key.json"
            request_path.write_bytes(loopback.canonical(candidate()))
            scenario_path.write_bytes(loopback.canonical(synthetic_scenario()))
            base = [sys.executable, str(ROOT / "tools/mini_vera/withheld_dialogue.py"),
                    "--request", str(request_path), "--scenario", str(scenario_path),
                    "--endpoint", fake.url, "--rater-sheet", str(sheet_path),
                    "--private-key", str(key_path)]
            dry = subprocess.run(base, capture_output=True, text=True, timeout=10)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("VALIDATED_NOT_EXECUTED", dry.stdout)
            self.assertEqual(fake.requests, [])
            blocked = subprocess.run(base + ["--execute"], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(fake.requests, [])
            actual = subprocess.run(base + ["--execute", "--host-idle-confirmed"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(len(fake.requests), 6)
            self.assertEqual(json.loads(sheet_path.read_text())["qualification"], "NOT_ESTABLISHED")
            self.assertEqual(json.loads(key_path.read_text())["evidence"]["calls"], 6)

    def test_wrong_model_response_leaves_unqualified_incomplete_pair(self):
        with tempfile.TemporaryDirectory() as temp, FakeLocal(answer=response(model="wrong")) as fake:
            root = Path(temp)
            request_path = root / "request.json"
            scenario_path = root / "scenario.json"
            sheet_path = root / "sheet.json"
            key_path = root / "key.json"
            request_path.write_bytes(loopback.canonical(candidate()))
            scenario_path.write_bytes(loopback.canonical(synthetic_scenario()))
            result = subprocess.run([
                sys.executable, str(ROOT / "tools/mini_vera/withheld_dialogue.py"),
                "--request", str(request_path), "--scenario", str(scenario_path),
                "--endpoint", fake.url, "--rater-sheet", str(sheet_path),
                "--private-key", str(key_path), "--execute", "--host-idle-confirmed",
            ], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(fake.requests), 1)
            for path in (sheet_path, key_path):
                aborted = json.loads(path.read_text())
                self.assertEqual(aborted["status"], "INCOMPLETE_NOT_BEHAVIORALLY_QUALIFIED")
                self.assertEqual(aborted["calls_attempted_observed"], 1)
                self.assertEqual(aborted["reason_code"], "INVALID_OR_UNAVAILABLE_REPLY")

    def test_truncated_reply_must_not_be_replayed_as_valid_correction_history(self):
        truncated = response(text="TRUNCATED_UNFINISHED_SENTENCE")
        truncated["choices"][0]["finish_reason"] = "length"
        with FakeLocal(answer=truncated) as fake:
            with self.assertRaises(loopback.LoopbackRejected):
                evaluator.compare(candidate(), synthetic_scenario(), endpoint=fake.url,
                                  rng=random.Random(71))
        self.assertEqual(len(fake.requests), 1,
                         "abort on first truncated reply before it can contaminate history")


if __name__ == "__main__":
    unittest.main()
