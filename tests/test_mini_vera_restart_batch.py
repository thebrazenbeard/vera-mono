"""Bounded repeated restart canary: never promote one synthetic success."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import restart_batch_canary as batch


def fake_case(*, suffix: str, passed: bool) -> dict:
    return {
        "schema": "MINI_VERA_RESTART_PUBLIC_CANARY_V1",
        "qualification": "SYNTHETIC_EVALUATION_NOT_MODEL_QUALIFIED",
        "model_http_calls_attempted": 3,
        "independent_python_sessions": 4,
        "synthetic_token_sha256": suffix * 64,
        "public_record_sha256": ("f" if suffix != "f" else "e") * 64,
        "approved_exact_count": 2 if passed else 1,
        "control_unknown": True,
        "revocation_blocked": True,
        "behavioral_pass": passed,
    }


class RestartBatchTests(unittest.TestCase):
    def call_batch(self, *, cases=3, endpoint="http://127.0.0.1:11439/v1"):
        return batch.run_batch(endpoint=endpoint, model="vera:local",
                               model_digest="b"*64, cases=cases,
                               timeout_seconds=20)

    def test_three_cases_aggregate_failure_without_converting_to_pass(self):
        values = [
            fake_case(suffix="a", passed=True),
            fake_case(suffix="b", passed=False),
            fake_case(suffix="c", passed=True),
        ]
        with patch.object(batch.restart_public_canary, "run_trial", side_effect=values) as model:
            result = self.call_batch(cases=3)
        self.assertEqual(3, model.call_count)
        self.assertEqual("COMPLETED_WITH_FAILURES", result["status"])
        self.assertFalse(result["all_cases_pass"])
        self.assertEqual((3, 2, 1), (
            result["cases_completed"], result["cases_passed"], result["cases_failed"]))
        self.assertEqual(9, result["model_http_calls_attempted"])
        self.assertEqual(12, result["independent_python_sessions"])
        self.assertEqual(3, len(result["cases"]))
        self.assertNotIn("model_text", json.dumps(result))
        self.assertEqual("PROMPT_DEVELOPED_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
                         result["evidence_ceiling"])

    def test_actual_fake_loopback_two_restart_cases_keep_public_private_isolated(self):
        with FakeLocal(answer=response(model="vera:local", text="UNKNOWN")) as server:
            result = self.call_batch(cases=2, endpoint=server.url)
            self.assertFalse(result["all_cases_pass"])
            self.assertEqual("COMPLETED_WITH_FAILURES", result["status"])
            self.assertEqual(6, len(server.requests))
            self.assertEqual(2, len(set(c["synthetic_token_sha256"] for c in result["cases"])))
            for _, request, _ in server.requests:
                user = json.loads(request["messages"][-1]["content"])
                text = json.dumps(user)
                self.assertNotIn("canary-private", text)
                self.assertNotIn("SYNTHETIC_PRIVATE_NEVER_SEND_", text)
                self.assertNotIn("Authorization", json.dumps(request))

    def test_portable_batch_runs_from_fresh_install_without_repository_imports(self):
        import os
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        from scripts import mini_vera_portable as portable
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="mini-vera-batch-portable-") as temp:
            install = Path(temp) / "install"
            portable.build(source, install, "a"*40)
            self.assertTrue(portable.verify(install))
            env = {k: v for k, v in os.environ.items()
                   if k.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
            with FakeLocal(answer=response(model="vera:local", text="UNKNOWN")) as server:
                execution = subprocess.run(
                    [sys.executable, "-B", "-m",
                     "tools.mini_vera.restart_batch_canary", "--run-batch",
                     "--endpoint", server.url, "--model", "vera:local",
                     "--model-digest", "b"*64, "--cases", "2",
                     "--timeout-seconds", "20"],
                    cwd=install, env=env, capture_output=True, text=True,
                    timeout=45)
                self.assertEqual(0, execution.returncode, execution.stderr)
                self.assertEqual(6, len(server.requests))
                result = json.loads(execution.stdout)
                self.assertEqual("COMPLETED_WITH_FAILURES", result["status"])
                self.assertEqual(2, result["cases_completed"])
                self.assertFalse(result["all_cases_pass"])
                self.assertEqual(6, result["model_http_calls_attempted"])
                self.assertEqual(8, result["independent_python_sessions"])
                contexts = [json.loads(x[1]["messages"][-1]["content"])
                            for x in server.requests]
                self.assertEqual(4, sum(bool(c["project_context_untrusted"])
                                        for c in contexts))
                self.assertEqual(2, sum(not c["project_context_untrusted"]
                                        for c in contexts))
                self.assertNotIn("canary-private", json.dumps(contexts))
                self.assertNotIn("SYNTHETIC_PRIVATE_NEVER_SEND_", json.dumps(contexts))
            self.assertTrue(portable.verify(install))

    def test_aborted_later_case_preserves_prior_observation_but_never_scores(self):
        valid = fake_case(suffix="a", passed=True)
        with patch.object(batch.restart_public_canary, "run_trial",
                          side_effect=[valid, batch.restart_public_canary.CanaryRefused("worker failure")]) as model:
            result = self.call_batch(cases=3)
        self.assertEqual(2, model.call_count)
        self.assertEqual("ABORTED_UNSCORED", result["status"])
        self.assertFalse(result["all_cases_pass"])
        self.assertEqual(1, result["cases_completed"])
        self.assertEqual(2, result["aborted_case"])
        self.assertEqual(3, result["model_http_calls_attempted"])
        self.assertNotIn("worker failure", json.dumps(result))

    def test_inconsistent_derived_score_aborts_without_all_pass(self):
        forged = fake_case(suffix="a", passed=False)
        forged["behavioral_pass"] = True
        with patch.object(batch.restart_public_canary, "run_trial",
                          side_effect=[forged]) as trial:
            result = self.call_batch(cases=3)
        self.assertEqual(1, trial.call_count)
        self.assertEqual("ABORTED_UNSCORED", result["status"])
        self.assertFalse(result["all_cases_pass"])
        self.assertEqual(0, result["cases_completed"])
        self.assertEqual("TRIAL_REFUSED", result["failure_code"])

    def test_repeated_synthetic_token_fails_closed(self):
        same = fake_case(suffix="a", passed=True)
        with patch.object(batch.restart_public_canary, "run_trial",
                          side_effect=[same, same]) as model:
            result = self.call_batch(cases=3)
        self.assertEqual(2, model.call_count)
        self.assertEqual("ABORTED_UNSCORED", result["status"])
        self.assertEqual("REPEATED_TOKEN_DIGEST", result["failure_code"])
        self.assertFalse(result["all_cases_pass"])

    def test_rejects_unbounded_count_and_invalid_endpoint_before_any_child(self):
        for count in (0, 5, True, -1, 2.0):
            with self.subTest(count=count), patch.object(
                    batch.restart_public_canary, "run_trial") as child:
                with self.assertRaises(batch.BatchRefused):
                    self.call_batch(cases=count)
                child.assert_not_called()
        with patch.object(batch.restart_public_canary, "run_trial") as child:
            with self.assertRaises(batch.BatchRefused):
                self.call_batch(endpoint="http://outside.example/v1")
            child.assert_not_called()

    def test_completed_batch_requires_every_case_pass(self):
        with patch.object(batch.restart_public_canary, "run_trial",
                          side_effect=[fake_case(suffix="d", passed=True),
                                       fake_case(suffix="e", passed=True)]) as model:
            result = self.call_batch(cases=2)
        self.assertEqual(2, model.call_count)
        self.assertEqual("COMPLETED_SYNTHETIC_ALL_PASS", result["status"])
        self.assertTrue(result["all_cases_pass"])
        self.assertEqual(2, result["cases_passed"])
        self.assertFalse(result["model_weights_verified"])
        self.assertFalse(result["independent_evaluation"])


if __name__ == "__main__":
    unittest.main()
