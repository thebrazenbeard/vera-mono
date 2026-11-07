"""Synthetic, fake-server-only controls for masked Mini-Vera comparisons."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
from tests.test_mini_vera_loopback import FakeLocal, candidate, response
from tools.mini_vera import blind_compare, loopback  # noqa: E402


class MiniVeraBlindCompareTests(unittest.TestCase):
    def test_arm_inputs_have_equal_evidence_model_and_decoding(self):
        arms = blind_compare.arm_payloads(candidate())
        self.assertEqual(set(arms), set(blind_compare.ARMS))
        user_messages = [arm["messages"][-1] for arm in arms.values()]
        self.assertTrue(all(user == user_messages[0] for user in user_messages))
        self.assertIn("project_context_untrusted", user_messages[0]["content"])
        for payload in arms.values():
            self.assertEqual(payload["model"], "qwen3.5-mini-local")
            self.assertEqual({k: payload[k] for k in blind_compare.DECODING},
                             blind_compare.DECODING)
            self.assertIs(payload["stream"], False)
            self.assertNotIn("tools", payload)
        self.assertEqual([m["role"] for m in arms["bare"]["messages"]], ["user"])
        self.assertEqual([m["role"] for m in arms["minimal_persona"]["messages"]],
                         ["system", "user"])
        self.assertNotEqual(arms["minimal_persona"]["messages"][0]["content"],
                            arms["governed_composer"]["messages"][0]["content"])

    def test_fake_local_server_comparison_records_three_real_http_receipts(self):
        with FakeLocal() as fake:
            sheet, private = blind_compare.compare(candidate(), endpoint=fake.url)
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual([item["label"] for item in sheet["entries"]], ["A", "B", "C"])
        self.assertEqual(set(private["arm_by_label"].values()), set(blind_compare.ARMS))
        self.assertNotIn("arm_by_label", sheet)
        self.assertNotIn("model_alias", sheet)
        self.assertNotIn("elapsed_ms", json.dumps(sheet))
        self.assertNotIn("governed_composer", json.dumps(sheet))
        self.assertEqual(sheet["trial_id"], private["trial_id"])
        self.assertEqual(private["rater_sheet_sha256"],
                         loopback.sha256(loopback.canonical(sheet)))
        self.assertEqual(private["evidence"]["calls"], 3)
        self.assertEqual(private["evidence"]["model_weights_verified"], False)
        self.assertEqual(private["evidence"]["behavioral_qualification"], "NOT_TESTED")
        self.assertEqual(private["evidence"]["context_matching"],
                         "SAME_JSON_USER_ENVELOPE_DIFFERENT_SYSTEM_INSTRUCTIONS")
        self.assertEqual({payload["model"] for _, payload, _ in fake.requests},
                         {"qwen3.5-mini-local"})
        self.assertEqual({payload["seed"] for _, payload, _ in fake.requests}, {20261106})
        self.assertEqual(len(private["latency_ms_by_label"]), 3)
        self.assertTrue(all(ms >= 0 for ms in private["latency_ms_by_label"].values()))
        self.assertEqual(sheet["shared_task_and_untrusted_evidence"]["synthetic_user_turn"],
                         "What can you verify?")
        self.assertIn("cold_restart_memory", sheet["unmeasured"])

    def test_cli_default_dry_run_zero_calls_no_outputs(self):
        with tempfile.TemporaryDirectory() as temp, FakeLocal() as fake:
            input_path = Path(temp) / "synthetic-request.json"
            sheet = Path(temp) / "sheet.json"
            key = Path(temp) / "key.json"
            input_path.write_bytes(loopback.canonical(candidate()))
            command = [sys.executable, str(ROOT / "tools/mini_vera/blind_compare.py"),
                       "--request", str(input_path), "--endpoint", fake.url,
                       "--rater-sheet", str(sheet), "--private-key", str(key)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("VALIDATED_NOT_EXECUTED", result.stdout)
            self.assertEqual(fake.requests, [])
            self.assertFalse(sheet.exists())
            self.assertFalse(key.exists())

    def test_opt_in_cli_writes_separate_non_overwritten_blind_and_key(self):
        with tempfile.TemporaryDirectory() as temp, FakeLocal() as fake:
            input_path = Path(temp) / "synthetic-request.json"
            sheet_path = Path(temp) / "sheet.json"
            key_path = Path(temp) / "key.json"
            input_path.write_bytes(loopback.canonical(candidate()))
            base = [sys.executable, str(ROOT / "tools/mini_vera/blind_compare.py"),
                    "--request", str(input_path), "--endpoint", fake.url,
                    "--rater-sheet", str(sheet_path), "--private-key", str(key_path),
                    "--execute"]
            without_host = subprocess.run(base, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(without_host.returncode, 0)
            self.assertEqual(fake.requests, [])
            actual = subprocess.run(base + ["--host-idle-confirmed"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(actual.returncode, 0, actual.stderr)
            self.assertEqual(len(fake.requests), 3)
            self.assertEqual(set(json.loads(key_path.read_text())["arm_by_label"].values()),
                             set(blind_compare.ARMS))
            self.assertEqual(len(json.loads(sheet_path.read_text())["entries"]), 3)
            repeats = subprocess.run(base + ["--host-idle-confirmed"],
                                     capture_output=True, text=True, timeout=10)
            self.assertNotEqual(repeats.returncode, 0)
            self.assertEqual(len(fake.requests), 3)

    def test_unwritable_or_missing_output_parent_refused_before_any_http_call(self):
        with tempfile.TemporaryDirectory() as temp, FakeLocal() as fake:
            root = Path(temp)
            request_path = root / "synthetic-request.json"
            request_path.write_bytes(loopback.canonical(candidate()))
            key_path = root / "key.json"
            sheet_path = root / "not-a-directory" / "rater.json"
            command = [sys.executable, str(ROOT / "tools/mini_vera/blind_compare.py"),
                       "--request", str(request_path), "--endpoint", fake.url,
                       "--rater-sheet", str(sheet_path), "--private-key", str(key_path),
                       "--execute", "--host-idle-confirmed"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(fake.requests, [])
            self.assertFalse(key_path.exists())
            self.assertFalse(sheet_path.exists())

    def test_failed_call_leaves_two_incomplete_receipts_not_orphan_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request_path = root / "synthetic-request.json"
            request_path.write_bytes(loopback.canonical(candidate()))
            sheet = root / "sheet.json"
            key = root / "key.json"
            argv = ["--request", str(request_path), "--endpoint",
                    "http://127.0.0.1:11434/v1", "--rater-sheet", str(sheet),
                    "--private-key", str(key), "--execute", "--host-idle-confirmed"]
            with patch.object(blind_compare, "compare",
                              side_effect=loopback.LoopbackRejected("synthetic outage")):
                with self.assertRaises(loopback.LoopbackRejected):
                    blind_compare.main(argv)
            for path in (sheet, key):
                saved = json.loads(path.read_text())
                self.assertEqual(saved["status"], "INCOMPLETE_NOT_BEHAVIORALLY_QUALIFIED")
                self.assertEqual(saved["calls_completed"], "UNKNOWN_IF_INTERRUPTED")
                self.assertNotIn("arm_by_label", saved)

    def test_no_nonloopback_or_local_history_or_forged_scope(self):
        request = candidate()
        with patch.object(blind_compare, "_one_call") as called:
            for bad in ("http://localhost:11434/v1", "http://192.168.1.71:11434/v1"):
                with self.subTest(bad=bad), self.assertRaises(loopback.LoopbackRejected):
                    blind_compare.compare(request, endpoint=bad)
            history = deepcopy(request)
            history["schema"] = "MINI_VERA_COMPOSED_LOCAL_REQUEST_V1"
            with self.assertRaises(loopback.LoopbackRejected):
                blind_compare.arm_payloads(history)
            called.assert_not_called()

    def test_reject_wrong_resident_echo_tool_calls_and_truncation_is_marked(self):
        wrong = response(model="wrong-alias")
        with FakeLocal(answer=wrong) as fake:
            with self.assertRaises(loopback.LoopbackRejected):
                blind_compare.compare(candidate(), endpoint=fake.url)
        effect = response()
        effect["choices"][0]["message"]["tool_calls"] = []
        with FakeLocal(answer=effect) as fake:
            with self.assertRaises(loopback.LoopbackRejected):
                blind_compare.compare(candidate(), endpoint=fake.url)
        short = response()
        short["choices"][0]["finish_reason"] = "length"
        with FakeLocal(answer=short) as fake:
            sheet, _ = blind_compare.compare(candidate(), endpoint=fake.url)
        self.assertEqual({item["finish_reason"] for item in sheet["entries"]}, {"length"})
        self.assertEqual(sheet["qualification"], "NOT_ESTABLISHED")


if __name__ == "__main__":
    unittest.main()
