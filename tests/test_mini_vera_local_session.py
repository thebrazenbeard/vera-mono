"""Local session integration: live-turn shape, volatile history, bounded HTTP."""

from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
import io
import hmac
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_mini_vera_source_bindings import (
    KEY, ledger_fixture, model_fixture, synthetic_approval, synthetic_composer_args,
)
from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import artifact_binding, compose, ledger_bridge, local_session, loopback


class LocalSessionIntegrationTests(unittest.TestCase):
    def test_actual_console_two_turns_keep_history_in_ram(self):
        with FakeLocal(answer=response(model="vera:local", text="First distinct server reply.")) as server:
            output = io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--execute", "--host-idle-confirmed"]
            inputs = iter(["What do you know?", "And now?", "/quit"])

            def next_input(_prompt):
                value = next(inputs)
                if value == "And now?":
                    server.answer = response(model="vera:local", text="Second distinct server reply.")
                return value

            with patch("builtins.input", side_effect=next_input), \
                    redirect_stdout(output):
                self.assertEqual(0, local_session.main(args))
            self.assertEqual(2, len(server.requests))
            first = server.requests[0][1]["messages"]
            second = server.requests[1][1]["messages"]
            self.assertEqual(["system", "user"], [x["role"] for x in first])
            self.assertEqual(["system", "user", "assistant", "user"],
                             [x["role"] for x in second])
            self.assertEqual("First distinct server reply.", second[2]["content"])
            self.assertNotEqual(loopback.sha256(loopback.canonical(server.requests[0][1])),
                                loopback.sha256(loopback.canonical(server.requests[1][1])))
            self.assertIn("Vera> First distinct server reply.", output.getvalue())
            self.assertIn("Vera> Second distinct server reply.", output.getvalue())
            self.assertNotIn("Authorization", server.requests[0][2])

    def test_two_new_processes_do_not_inherit_volatile_chat_history(self):
        with FakeLocal(answer=response(model="vera:local")) as server:
            command = [sys.executable, "-m", "tools.mini_vera.local_session",
                       "--endpoint", server.url, "--model", "vera:local",
                       "--model-digest", "b" * 64, "--execute", "--host-idle-confirmed"]
            for utterance in ("First process", "Independent second process"):
                run = subprocess.run(command + ["--prompt", utterance], cwd=Path(__file__).parents[1],
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(0, run.returncode, run.stderr)
            self.assertEqual(2, len(server.requests))
            self.assertEqual([2, 2], [len(item[1]["messages"]) for item in server.requests])
            self.assertNotIn("First process", json.dumps(server.requests[1][1]))

    def test_oversized_model_reply_clears_history_and_session_continues(self):
        # The transport accepts a bounded 8,193-byte reply, while the context
        # history limit is 8,192. This must not crash the next local turn.
        with FakeLocal(answer=response(model="vera:local", text="X" * 8193)) as server:
            errors = io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--execute", "--host-idle-confirmed"]
            with patch("builtins.input", side_effect=["First question", "Second question", "/quit"]), \
                    redirect_stdout(io.StringIO()), redirect_stderr(errors):
                self.assertEqual(0, local_session.main(args))
            self.assertEqual(2, len(server.requests))
            self.assertEqual([2, 2], [len(r[1]["messages"]) for r in server.requests])
            self.assertIn("Session history cleared", errors.getvalue())

    def test_truncated_response_is_labeled_and_not_replayed(self):
        truncated = response(model="vera:local", text="This answer is unfinished")
        truncated["choices"][0]["finish_reason"] = "length"
        with FakeLocal(answer=truncated) as server:
            output, errors = io.StringIO(), io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--execute", "--host-idle-confirmed"]
            with patch("builtins.input", side_effect=["First question", "Second question", "/quit"]), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(0, local_session.main(args))
            self.assertEqual([2, 2], [len(r[1]["messages"]) for r in server.requests])
            self.assertIn("Vera [incomplete reply]>", output.getvalue())
            self.assertIn("model output was truncated", errors.getvalue())

    def test_console_validation_does_not_contact_server(self):
        with FakeLocal(answer=response(model="vera:local")) as server:
            output = io.StringIO()
            args = ["--endpoint", server.url, "--model", "vera:local",
                    "--model-digest", "b" * 64, "--prompt", "A test turn"]
            with redirect_stdout(output):
                self.assertEqual(0, local_session.main(args))
            self.assertEqual([], server.requests)
            self.assertIn("VALIDATED_NOT_EXECUTED", output.getvalue())
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                local_session.main(args + ["--execute"])
            self.assertEqual(2, caught.exception.code)
            self.assertEqual([], server.requests)

    def test_two_real_loopback_calls_with_local_in_memory_history(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            root, manifest, manifest_sha, _ = model_fixture(folder)
            ledger, head = ledger_fixture(folder)
            state, _ = ledger_bridge.project_existing_ledger(
                ledger, record_ids=["work-1"], expected_head=head, expected_revision=1,
                integrity_key=KEY, host_public_project_approval=synthetic_approval,
            )
            args = synthetic_composer_args(state, 1)
            args["turn"] = {"schema": "MINI_VERA_LOCAL_TURN_V1", "scope": "LOCAL_LOOPBACK_ONLY",
                            "turn_id": "local-1", "user_text": "What is verified?"}
            first = artifact_binding.compose_with_local_manifest(
                model_root=root, model_manifest=manifest,
                expected_manifest_sha256=manifest_sha, **args,
            )
            self.assertEqual("MINI_VERA_COMPOSED_LOCAL_ARTIFACT_BOUND_REQUEST_V1", first["schema"])
            with FakeLocal(answer=response(model="mini-vera:synthetic", text="Only a source claim.")) as server:
                reply = loopback.execute(first, endpoint=server.url)
                self.assertEqual(1, len(server.requests))
            self.assertEqual("Only a source claim.", reply["response"]["text"])

            history = [deepcopy(first["inference"]["messages"][-1]),
                       {"role": "assistant", "content": reply["response"]["text"]}]
            args["turn"] = {"schema": "MINI_VERA_LOCAL_TURN_V1", "scope": "LOCAL_LOOPBACK_ONLY",
                            "turn_id": "local-2", "user_text": "Are you sure you ran a model?"}
            second = artifact_binding.compose_with_local_manifest(
                model_root=root, model_manifest=manifest, expected_manifest_sha256=manifest_sha,
                session_history=history, **args,
            )
            payload, _ = loopback.validate_candidate(second)
            self.assertEqual(["system", "user", "assistant", "user"],
                             [item["role"] for item in payload["messages"]])
            self.assertEqual("Are you sure you ran a model?",
                             json.loads(payload["messages"][-1]["content"])["local_user_turn"])
            with FakeLocal(answer=response(model="mini-vera:synthetic", text="One local HTTP response.")) as server:
                loopback.execute(second, endpoint=server.url)
                self.assertEqual(payload, server.requests[0][1])
            tampered = deepcopy(second)
            tampered["inference"]["messages"][1]["role"] = "assistant"
            tampered["request_sha256"] = loopback.sha256(loopback.canonical(tampered["inference"]))
            with self.assertRaisesRegex(loopback.LoopbackRejected, "conversation order"):
                loopback.validate_candidate(tampered)
            oversized = deepcopy(second)
            oversized["inference"]["messages"][0]["content"] += "x" * loopback.MAX_REQUEST_FILE
            oversized["request_sha256"] = loopback.sha256(loopback.canonical(oversized["inference"]))
            with self.assertRaisesRegex(loopback.LoopbackRejected, "bounded input size"):
                loopback.validate_candidate(oversized)

    def test_rejects_forged_history_mismatched_scope_or_schema(self):
        args = synthetic_composer_args(*self._ephemeral_state())
        args["turn"] = {"schema": "MINI_VERA_LOCAL_TURN_V1", "scope": "LOCAL_LOOPBACK_ONLY",
                        "turn_id": "local-3", "user_text": "Continue"}
        args["model"] = "vera:local"
        args["model_digest"] = "a" * 64
        with self.assertRaisesRegex(compose.CompositionRejected, "history role"):
            compose.compose(session_history=[{"role": "assistant", "content": "Fake"},
                                                    {"role": "user", "content": "Fake"}], **args)
        args["turn"]["scope"] = "REMOTE_ALLOW_ALL"
        with self.assertRaisesRegex(compose.CompositionRejected, "explicit local"):
            compose.compose(**args)

    @staticmethod
    def _ephemeral_state():
        state = {"schema": "MINI_VERA_OPERATOR_STATE_V1", "revision": 1,
                 "source_id": "local-test", "records": []}
        state["hmac_sha256"] = hmac.new(KEY, compose.canonical(state), "sha256").hexdigest()
        return state, 1


if __name__ == "__main__":
    unittest.main()
