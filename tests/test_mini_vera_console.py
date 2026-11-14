"""Offline tests for the opt-in local Mini-Vera conversational launcher."""
import contextlib
import io
import json
import unittest
from unittest import mock

from tools.mini_vera import conversation_console as console


def report(status="RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE", digest="a" * 64):
    return {"schema": "MINI_VERA_08B_PREFLIGHT_V1", "status": status,
            "model": "qwen3.5:0.8b", "ollama_tag_digest": digest,
            "model_resident": False, "model_inference_calls": 0,
            "digest_evidence": "SERVER_DECLARED_NOT_WEIGHT_ATTESTATION"}


class ConversationConsoleTests(unittest.TestCase):
    def invoke(self, args, preflight=None):
        with mock.patch.object(console.ollama_preflight, "probe",
                               return_value=preflight or report()) as check, \
             mock.patch.object(console.local_session, "main", return_value=0) as session, \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = console.main(args)
        return result, check, session, stdout.getvalue(), stderr.getvalue()

    def test_no_host_consent_never_probes_or_runs(self):
        result, check, session, _, _ = self.invoke(["--prompt", "hello"])
        self.assertEqual(2, result)
        check.assert_not_called()
        session.assert_not_called()

    def test_dry_run_is_read_only_even_for_cold_model(self):
        result, check, session, stdout, _ = self.invoke(["--check"])
        self.assertEqual(0, result)
        check.assert_called_once()
        session.assert_not_called()
        self.assertEqual("RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                         json.loads(stdout)["status"])

    def test_cold_model_without_opt_in_stops(self):
        result, _, session, _, _ = self.invoke(
            ["--confirm-host-idle"],
            report("COLD_MODEL_NOT_AUTHORIZED_TO_LOAD"))
        self.assertEqual(2, result)
        session.assert_not_called()

    def test_interactive_launch_keeps_local_history_in_existing_shell(self):
        result, check, session, _, _ = self.invoke(
            ["--endpoint", "http://127.0.0.1:11521/v1", "--model", "qwen3.5:0.8b",
             "--allow-cold-load", "--confirm-host-idle"])
        self.assertEqual(0, result)
        self.assertTrue(check.call_args.kwargs["allow_cold_load"])
        argv = session.call_args.args[0]
        self.assertEqual("a"*64, argv[argv.index("--model-digest")+1])
        self.assertIn("--execute", argv)
        self.assertIn("--host-idle-confirmed", argv)
        self.assertIn("--ollama-disable-thinking", argv)
        self.assertNotIn("--prompt", argv)
        self.assertNotIn("--public-state", argv)
        self.assertNotIn("--synthetic-source-first", argv)

    def test_one_turn_passes_prompt_and_reports_local_exit(self):
        result, _, session, _, _ = self.invoke(
            ["--confirm-host-idle", "--prompt", "who are you?"])
        self.assertEqual(0, result)
        self.assertEqual("who are you?", session.call_args.args[0][-1])
        self.assertEqual("--prompt", session.call_args.args[0][-2])

    def test_digest_mismatch_refuses_before_session(self):
        with mock.patch.object(console.ollama_preflight, "probe",
                               side_effect=console.ollama_preflight.PreflightRefused("digest changed")), \
             mock.patch.object(console.local_session, "main") as session, \
             contextlib.redirect_stderr(io.StringIO()):
            result = console.main(["--confirm-host-idle", "--expected-tag-digest", "b"*64])
        self.assertEqual(2, result)
        session.assert_not_called()

    def test_unexpected_preflight_model_fails_closed(self):
        invalid = report()
        invalid["model"] = "other:model"
        result, _, session, _, _ = self.invoke(["--confirm-host-idle"], invalid)
        self.assertEqual(2, result)
        session.assert_not_called()

    def test_underlying_shell_exit_propagates(self):
        with mock.patch.object(console.ollama_preflight, "probe", return_value=report()), \
             mock.patch.object(console.local_session, "main", return_value=2):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, console.main(["--confirm-host-idle"]))


if __name__ == "__main__":
    unittest.main()
