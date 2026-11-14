"""A single-turn CLI exit status must never attest a truncated neural reply."""
from __future__ import annotations

import io
from contextlib import redirect_stdout, redirect_stderr
from unittest import TestCase
from unittest.mock import patch

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import conversation_console, local_session


def reply(text="The answer is four.", *, finish="stop"):
    obj = response(model="vera:test", text=text)
    obj["choices"][0]["finish_reason"] = finish
    return obj


class TruncatedOneShotExitTests(TestCase):
    def args(self, endpoint):
        return ["--endpoint", endpoint, "--model", "vera:test",
                "--model-digest", "b"*64, "--execute",
                "--host-idle-confirmed", "--prompt", "Give a completed answer"]

    def test_one_shot_truncation_returns_nonzero_after_exactly_one_real_http(self):
        with FakeLocal(answer=reply("I did not finish", finish="length")) as server:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = local_session.main(self.args(server.url))
        self.assertEqual(2, code)
        self.assertEqual(1, len(server.requests))
        self.assertIn("Vera [incomplete reply]>", out.getvalue())
        self.assertIn("truncated", err.getvalue())
        self.assertNotIn("Vera> I did not finish", out.getvalue())

    def test_complete_single_turn_keeps_zero_exit(self):
        with FakeLocal(answer=reply()) as server:
            with redirect_stdout(io.StringIO()):
                code = local_session.main(self.args(server.url))
        self.assertEqual(0, code)
        self.assertEqual(1, len(server.requests))

    def test_interactive_truncation_clears_history_and_can_continue(self):
        with FakeLocal(answer=reply("unfinished", finish="length")) as server:
            with patch("builtins.input", side_effect=["first", "second", "/quit"]), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = local_session.main(self.args(server.url)[:-2])
        self.assertEqual(0, code)
        self.assertEqual(2, len(server.requests))
        self.assertEqual([2, 2],
                         [len(payload["messages"]) for _, payload, _ in server.requests])

    def test_chat_launcher_one_shot_propagates_truncated_failure(self):
        with FakeLocal(answer=reply("This is unfinished", finish="length")) as server:
            probe = {"status":"RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                     "model":"vera:test", "ollama_tag_digest":"b"*64}
            with patch.object(conversation_console.ollama_preflight,
                              "probe", return_value=probe), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = conversation_console.main([
                    "--endpoint", server.url, "--model", "vera:test",
                    "--confirm-host-idle", "--prompt", "hi"])
        self.assertEqual(2, code)
        self.assertEqual(1, len(server.requests))


if __name__ == "__main__":
    import unittest
    unittest.main()
