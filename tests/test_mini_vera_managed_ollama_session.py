"""Bounded host-owning Mini-Vera session: tests assert effects and cleanup."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.mini_vera import managed_ollama_session as managed
from tools.mini_vera import ollama_preflight
from tools.mini_vera.windows_owned_job import JobRefused

MODEL = "mini-vera-hauhau-q4:source-probe-20261114"
DIGEST = "3a2ecd5655f349d1f817a8eee531153bdd7bcf64c63080a0c954e02a0be48265"


def open_unused_port():
    with socket.socket() as conn:
        conn.bind(("127.0.0.1", 0))
        return conn.getsockname()[1]


class ManagedOllamaSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.exe = folder / "ollama.exe"
        self.exe.write_bytes(b"fake-local-exe")
        self.models = folder / "preexisting-model-registry"
        self.models.mkdir()
        self.port = open_unused_port()
        self.job_factory = mock.patch.object(managed, "KillOnCloseJob")
        self.job = self.job_factory.start().return_value
        self.addCleanup(self.job_factory.stop)
        self.args = [
            "--ollama-exe", str(self.exe),
            "--models-root", str(self.models),
            "--port", str(self.port),
            "--model", MODEL,
            "--expected-tag-digest", DIGEST,
            "--start-owned-server", "--confirm-host-idle",
            "--allow-cold-load", "--compact-dialogue",
            "--prompt", "What is the fictional vessel called?",
        ]

    def call(self, args=None):
        # Exercise simulated Windows-owned processing on any CI OS without
        # changing global sys.platform (which can affect unrelated imports).
        with contextlib.redirect_stderr(io.StringIO()) as err, \
             mock.patch.object(managed, "sys", SimpleNamespace(
                 platform="win32", stderr=err)):
            code = managed.main(self.args if args is None else args)
        return code, err.getvalue()

    def test_explicit_small_model_uses_existing_small_model_preflight(self):
        args = list(self.args)
        args[args.index("--model") + 1] = "qwen3.5:0.8b"
        args.append("--small-08b")
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0) as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            try:
                code, _ = self.call(args)
            except SystemExit as exc:
                code = exc.code  # Missing CLI support is the expected RED.
        self.assertEqual(0, code)
        forwarded = console.call_args.args[0]
        self.assertNotIn("--candidate-4b", forwarded)
        self.assertEqual("qwen3.5:0.8b", forwarded[forwarded.index("--model") + 1])
        self.assertIn("--expected-tag-digest", forwarded)
        self.assertIn("--confirm-host-idle", forwarded)
        self.assertIn("--allow-cold-load", forwarded)
        self.assertIn("--compact-dialogue", forwarded)
        self.job.bind.assert_called_once_with(proc.pid)
        proc.terminate.assert_called_once()
        self.job.close.assert_called_once()

    def test_optin_session_runs_guarded_console_and_terminates_only_owned_child(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc) as spawned, \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0) as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call()
        self.assertEqual(0, code)
        spawned.assert_called_once()
        self.assertEqual(2, len(spawned.call_args.args[0]))
        self.assertTrue(os.path.samefile(self.exe, spawned.call_args.args[0][0]))
        self.assertEqual("serve", spawned.call_args.args[0][1])
        environment = spawned.call_args.kwargs["env"]
        self.assertEqual(f"127.0.0.1:{self.port}", environment["OLLAMA_HOST"])
        self.assertTrue(os.path.samefile(self.models, environment["OLLAMA_MODELS"]))
        self.assertEqual("true", environment["OLLAMA_NO_CLOUD"])
        self.assertEqual("-1", environment["CUDA_VISIBLE_DEVICES"])
        self.assertEqual("1", environment["OLLAMA_MAX_LOADED_MODELS"])
        argv = console.call_args.args[0]
        self.assertIn("--candidate-4b", argv)
        self.assertIn("--expected-tag-digest", argv)
        self.assertIn("--allow-cold-load", argv)
        self.assertIn("--confirm-host-idle", argv)
        self.assertIn("--compact-dialogue", argv)
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()
        self.job.bind.assert_called_once_with(proc.pid)
        self.job.close.assert_called_once()

    def test_managed_disable_thinking_flag_is_not_forwarded_to_console(self):
        # A real 4B smoke exposed that the managed CLI accepts this option
        # but the nested conversation_console parser rejects it.
        # The console already enables this setting in local_session.
        args = [*self.args, "--ollama-disable-thinking"]
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0) as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call(args)
        self.assertEqual(0, code)
        self.assertNotIn("--ollama-disable-thinking", console.call_args.args[0])
        self.assertIn("--compact-dialogue", console.call_args.args[0])
        proc.terminate.assert_called_once()

    def test_non_windows_platform_refuses_before_owned_process(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, \
             mock.patch.object(managed, "sys", SimpleNamespace(
                 platform="linux", stderr=err)), \
             mock.patch.object(managed.subprocess, "Popen") as spawned, \
             mock.patch.object(managed.ollama_preflight,
                               "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code = managed.main(self.args)
        self.assertEqual(2, code)
        self.assertIn("Windows only", err.getvalue())
        spawned.assert_not_called()

    def test_missing_explicit_owned_server_consent_refuses_without_process(self):
        args = [a for a in self.args if a != "--start-owned-server"]
        with mock.patch.object(managed.subprocess, "Popen") as spawned:
            code, _ = self.call(args)
        self.assertEqual(2, code)
        spawned.assert_not_called()

    def test_low_ram_refuses_before_process(self):
        with mock.patch.object(managed.subprocess, "Popen") as spawned, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=7 * ollama_preflight.GIB):
            code, _ = self.call()
        self.assertEqual(2, code)
        spawned.assert_not_called()

    def test_listener_already_present_refuses_before_process(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            args = list(self.args)
            args[args.index("--port") + 1] = str(port)
            with mock.patch.object(managed.subprocess, "Popen") as spawned, \
                 mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                                   return_value=16 * ollama_preflight.GIB):
                code, _ = self.call(args)
        self.assertEqual(2, code)
        spawned.assert_not_called()

    def test_job_assignment_refusal_cannot_reach_inference_and_stops_child(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        self.job.bind.side_effect = JobRefused("synthetic bind denial")
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main") as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call()
        self.assertEqual(2, code)
        console.assert_not_called()
        proc.terminate.assert_called_once()
        self.job.close.assert_called_once()

    def test_server_not_ready_refuses_inference_and_terminates_child(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=False), \
             mock.patch.object(managed.conversation_console, "main") as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call()
        self.assertEqual(2, code)
        console.assert_not_called()
        proc.terminate.assert_called_once()

    def test_session_refusal_still_stops_owned_server(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=2), \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call()
        self.assertEqual(2, code)
        proc.terminate.assert_called_once()

    def test_held_server_never_modifies_parent_process_environment(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        before = dict(os.environ)
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0), \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            self.call()
        self.assertEqual(before, dict(os.environ))

    def test_lingering_listener_after_child_shutdown_is_not_reported_as_success(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed, "_port_open", side_effect=[False, True]), \
             mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0), \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, message = self.call()
        self.assertEqual(2, code)
        self.assertIn("remains occupied", message)
        proc.terminate.assert_called_once()

    def test_managed_4b_defaults_to_compact_when_unspecified(self):
        args = [arg for arg in self.args if arg != "--compact-dialogue"]
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0) as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call(args)
        self.assertEqual(0, code)
        self.assertIn("--compact-dialogue", console.call_args.args[0])
        self.job.bind.assert_called_once_with(proc.pid)
        proc.terminate.assert_called_once()

    def test_explicit_full_governed_mode_keeps_diagnostic_alternative(self):
        args = [arg for arg in self.args if arg != "--compact-dialogue"]
        args.append("--full-governed-dialogue")
        proc = mock.Mock()
        proc.poll.return_value = None
        with mock.patch.object(managed.subprocess, "Popen", return_value=proc), \
             mock.patch.object(managed, "wait_ready", return_value=True), \
             mock.patch.object(managed.conversation_console, "main", return_value=0) as console, \
             mock.patch.object(managed.ollama_preflight, "windows_free_physical_bytes",
                               return_value=16 * ollama_preflight.GIB):
            code, _ = self.call(args)
        self.assertEqual(0, code)
        self.assertNotIn("--compact-dialogue", console.call_args.args[0])
        self.assertNotIn("--full-governed-dialogue", console.call_args.args[0])
        proc.terminate.assert_called_once()

    def test_conflicting_dialogue_modes_refuse_before_owning_server(self):
        args = [*self.args, "--full-governed-dialogue"]
        with mock.patch.object(managed.subprocess, "Popen") as spawned:
            code, error = self.call(args)
        self.assertEqual(2, code)
        self.assertIn("conflicting dialogue modes", error)
        spawned.assert_not_called()

    def test_bad_digest_is_refused_without_child(self):
        args = list(self.args)
        args[args.index("--expected-tag-digest") + 1] = "not-a-digest"
        with mock.patch.object(managed.subprocess, "Popen") as spawned:
            code, _ = self.call(args)
        self.assertEqual(2, code)
        spawned.assert_not_called()

if __name__ == "__main__":
    unittest.main()
