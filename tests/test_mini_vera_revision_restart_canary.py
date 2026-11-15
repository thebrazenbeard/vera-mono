"""Actual independent-process PUBLIC correction/supersession boundary tests; fake model."""
from __future__ import annotations

import json
import unittest

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import revision_restart_canary as trial


class RevisionRestartTests(unittest.TestCase):
    def test_correction_prompt_distinguishes_absent_record_from_present_data(self):
        # Neural A/B on verified 4B bytes exposed a present-record UNKNOWN failure
        # for the prior underspecified extraction instruction.
        self.assertIn("Find record_id revision-current.", trial.PROMPT)
        self.assertIn("Return the exact SYNTHETIC- code", trial.PROMPT)
        self.assertIn("Only return UNKNOWN when revision-current is absent.", trial.PROMPT)
        self.assertNotIn("Otherwise reply UNKNOWN.", trial.PROMPT)

    def test_corrected_only_visible_after_five_process_restarts(self):
        with FakeLocal(answer=response(model="vera:local", text="UNKNOWN")) as server:
            result = trial.run_trial(
                endpoint=server.url, model="vera:local",
                model_digest="b" * 64, timeout_seconds=20)
            self.assertEqual("MINI_VERA_REVISION_RESTART_CANARY_V1", result["schema"])
            self.assertEqual(5, result["independent_python_sessions"])
            self.assertEqual(3, result["model_http_calls_attempted"])
            self.assertTrue(result["stale_superseded_refused"])
            self.assertTrue(result["revoked_refused"])
            self.assertFalse(result["behavioral_pass"])
            self.assertEqual(64, len(result["synthetic_token_sha256"]))
            self.assertNotIn("current_record_sha256", result)
            self.assertEqual(3, len(server.requests))
            bodies = [json.loads(request[1]["messages"][-1]["content"])
                      for request in server.requests]
            selected = [body["project_context_untrusted"] for body in bodies]
            self.assertEqual([0, 1, 1], sorted(len(records) for records in selected))
            for records in selected:
                if records:
                    self.assertEqual("revision-current", records[0]["record_id"])
                    self.assertIn("synthetic corrected gate code", records[0]["text"])
                    self.assertNotIn("revision-old", json.dumps(records))
                self.assertNotIn("revision-private", json.dumps(records))
                self.assertNotIn("SYNTHETIC_PRIVATE_NEVER_SEND", json.dumps(records))
            self.assertNotIn("old_token", json.dumps(result))
            self.assertNotIn("current_token", json.dumps(result))
            self.assertNotIn("model_text", json.dumps(result))

    def test_invalid_endpoint_refuses_before_disposable_ledger(self):
        with self.assertRaises(trial.RevisionCanaryRefused):
            trial.run_trial(endpoint="https://external.example/v1",
                            model="vera:local", model_digest="b" * 64)

    def test_worker_refuses_arbitrary_ledger_path_before_open(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        with TemporaryDirectory(prefix="not-revision-fixture-") as temp:
            path = Path(temp) / "memory.sqlite"
            path.touch()
            with patch.object(trial.baseline, "MemoryLedger") as opened:
                with self.assertRaises(trial.RevisionCanaryRefused):
                    trial.worker(ledger_path=path, head="a" * 64,
                                 arm="current", endpoint="http://127.0.0.1:11439/v1",
                                 model="vera:local", model_digest="b" * 64)
                opened.assert_not_called()

    def test_score_does_not_treat_control_leak_as_success(self):
        self.assertFalse(trial.score(
            expected="SYNTHETIC-BBBB", output={
                "current-a": "SYNTHETIC-BBBB", "current-b": "SYNTHETIC-BBBB",
                "control": "SYNTHETIC-BBBB"},
            stale_blocked=True, revoked_blocked=True)["behavioral_pass"])


if __name__ == "__main__":
    unittest.main()
