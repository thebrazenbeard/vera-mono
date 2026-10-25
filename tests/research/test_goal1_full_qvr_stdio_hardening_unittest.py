"""Hostile synthetic-child tests; no Docker, model, keys, or network required."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import sys
import time
import unittest
from threading import Event
from unittest.mock import patch

from research.goal1_acceptance_bridge import full_qvr_stdio_broker as broker


IMAGE = "sha256:" + "a" * 64
VOLUME = "goal1-qvr-stdio-hardening"


@contextmanager
def child(script: str):
    with patch.object(broker, "build_command", return_value=[sys.executable, "-u", "-c", script]):
        yield


class BrokerHardeningTests(unittest.TestCase):
    def test_forged_trailing_frame_must_not_trigger_callback(self):
        script = (
            "import hashlib,json,sys,time\n"
            "req=json.loads(sys.stdin.readline())\n"
            "first={'kind':'GATEWAY_REQUEST','prompt':req['prompt'],"
            "'model':req['model'],'model_digest':req['model_digest'],"
            "'prompt_sha256':hashlib.sha256(req['prompt'].encode()).hexdigest(),"
            "'max_tokens':req['max_tokens']}\n"
            "print(json.dumps(first),flush=True)\n"
            "print(json.dumps({'kind':'FORGED_TRAILING'}),flush=True)\n"
            "time.sleep(.5)\n"
        )
        first = {"kind":"INVOKE", "prompt":"hi", "model":"test",
                 "model_digest":"a" * 64, "invocation_id":"one", "max_tokens":2}
        called = []
        with child(script), self.assertRaises(RuntimeError):
            broker._exchange(IMAGE, VOLUME, first,
                             lambda *args, **kwargs: called.append(True),
                             timeout_seconds=1)
        self.assertEqual(called, [], "untrusted child stream reached effectful callback")

    def test_timed_out_callback_must_not_finish_after_reported_unknown(self):
        script = (
            "import hashlib,json,sys,time\n"
            "req=json.loads(sys.stdin.readline())\n"
            "first={'kind':'GATEWAY_REQUEST','prompt':req['prompt'],"
            "'model':req['model'],'model_digest':req['model_digest'],"
            "'prompt_sha256':hashlib.sha256(req['prompt'].encode()).hexdigest(),"
            "'max_tokens':req['max_tokens']}\n"
            "print(json.dumps(first),flush=True)\n"
            "time.sleep(2)\n"
        )
        first = {"kind":"INVOKE", "prompt":"hi", "model":"test",
                 "model_digest":"a" * 64, "invocation_id":"one", "max_tokens":2}
        entered, completed = Event(), Event()
        def callback(*args, **kwargs):
            entered.set()
            time.sleep(.35)
            completed.set()
            return {}
        with child(script), self.assertRaisesRegex(RuntimeError, "timeout|unknown"):
            broker._exchange(IMAGE, VOLUME, first, callback, timeout_seconds=.2)
        self.assertTrue(entered.is_set(), "callback was not exercised")
        self.assertFalse(completed.wait(.4), "callback ran after timeout response")

    def test_valid_gateway_response_survives_broker_checks(self):
        script = (
            "import hashlib,json,sys\n"
            "req=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'kind':'GATEWAY_REQUEST','prompt':req['prompt'],"
            "'model':req['model'],'model_digest':req['model_digest'],"
            "'prompt_sha256':hashlib.sha256(req['prompt'].encode()).hexdigest(),"
            "'max_tokens':req['max_tokens']}),flush=True)\n"
            "reply=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'kind':'INVOKE_RESULT',"
            "'response_sha256':reply['response_sha256'],"
            "'journal_entries':1,'qualified':False}),flush=True)\n"
        )

        def callback(prompt, *, model, model_digest, max_tokens):
            text = "model's inert response"
            return {"kind": "GATEWAY_RESPONSE", "text": text, "model": model,
                    "model_digest": model_digest,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "response_sha256": hashlib.sha256(text.encode()).hexdigest()}

        with child(script):
            result = broker.invoke_with_host_callback(
                image_id=IMAGE, volume=VOLUME, prompt="hi", model="test",
                digest="a" * 64, invocation_id="one", callback=callback)
        self.assertEqual(result["journal_entries"], 1)

    def test_nonterminated_stdout_is_bounded_before_newline(self):
        script = (
            "import sys,time\n"
            "sys.stdin.buffer.readline()\n"
            "sys.stdout.buffer.write(b'x'*24000)\n"
            "sys.stdout.buffer.flush()\n"
            "time.sleep(2)\n"
        )
        started = time.monotonic()
        with child(script), self.assertRaisesRegex(RuntimeError, "oversized|IPC"):
            broker._exchange(IMAGE, VOLUME, {"kind": "READBACK"}, timeout_seconds=1)
        self.assertLess(time.monotonic() - started, 1.8)

    def test_stderr_flood_does_not_block_valid_readback(self):
        script = (
            "import json,sys\n"
            "sys.stdin.buffer.readline()\n"
            "sys.stderr.buffer.write(b'e'*262144)\n"
            "sys.stderr.buffer.flush()\n"
            "sys.stdout.write(json.dumps({'kind':'READBACK_RESULT','entries':0,"
            "'invocation_ids':[],'qualified':False})+'\\n')\n"
            "sys.stdout.flush()\n"
        )
        with child(script):
            result = broker._exchange(IMAGE, VOLUME, {"kind": "READBACK"}, timeout_seconds=2)
        self.assertEqual(result["entries"], 0)

    def test_stalled_callback_releases_broker_with_unknown_outcome(self):
        script = (
            "import hashlib,json,sys,time\n"
            "req=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'kind':'GATEWAY_REQUEST','prompt':req['prompt'],"
            "'model':req['model'],'model_digest':req['model_digest'],"
            "'prompt_sha256':hashlib.sha256(req['prompt'].encode()).hexdigest(),"
            "'max_tokens':req['max_tokens']}),flush=True)\n"
            "time.sleep(5)\n"
        )

        def hung_callback(*args, **kwargs):
            time.sleep(3)
            return {}

        first = {"kind": "INVOKE", "prompt": "hi", "model": "test",
                 "model_digest": "a" * 64, "invocation_id": "one", "max_tokens": 2}
        started = time.monotonic()
        with child(script), self.assertRaisesRegex(RuntimeError, "timeout|unknown"):
            broker._exchange(IMAGE, VOLUME, first, hung_callback, timeout_seconds=0.5)
        self.assertLess(time.monotonic() - started, 2)

    def test_oversized_metadata_is_rejected_before_process_start(self):
        with patch.object(broker.subprocess, "Popen") as spawn:
            with self.assertRaises(ValueError):
                broker.invoke_with_host_callback(
                    image_id=IMAGE, volume=VOLUME, prompt="hi", model="m" * 30000,
                    digest="a" * 64, invocation_id="one", callback=lambda *a, **k: {})
            spawn.assert_not_called()

    def test_forged_terminal_digest_is_rejected(self):
        script = (
            "import hashlib,json,sys\n"
            "req=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'kind':'GATEWAY_REQUEST','prompt':req['prompt'],"
            "'model':req['model'],'model_digest':req['model_digest'],"
            "'prompt_sha256':hashlib.sha256(req['prompt'].encode()).hexdigest(),"
            "'max_tokens':req['max_tokens']}),flush=True)\n"
            "reply=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'kind':'INVOKE_RESULT','response_sha256':'0'*64,"
            "'journal_entries':1,'qualified':False}),flush=True)\n"
        )

        def callback(prompt, *, model, model_digest, max_tokens):
            text = "synthetic"
            return {"kind": "GATEWAY_RESPONSE", "text": text, "model": model,
                    "model_digest": model_digest,
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "response_sha256": hashlib.sha256(text.encode()).hexdigest()}

        with child(script), self.assertRaisesRegex(RuntimeError, "digest|terminal"):
            broker.invoke_with_host_callback(
                image_id=IMAGE, volume=VOLUME, prompt="hi", model="test",
                digest="a" * 64, invocation_id="one", callback=callback)

    def test_extra_stdout_frame_is_not_accepted_after_terminal(self):
        script = (
            "import json,sys\n"
            "sys.stdin.buffer.readline()\n"
            "for _ in range(3):\n"
            " print(json.dumps({'kind':'READBACK_RESULT','entries':0,"
            "'invocation_ids':[],'qualified':False}),flush=True)\n"
        )
        with child(script), self.assertRaisesRegex(RuntimeError, "unexpected|IPC"):
            broker._exchange(IMAGE, VOLUME, {"kind": "READBACK"}, timeout_seconds=2)

    def test_bad_callback_reply_is_not_relayed_to_learner(self):
        script = (
            "import hashlib,json,sys,time\n"
            "req=json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'kind':'GATEWAY_REQUEST','prompt':req['prompt'],"
            "'model':req['model'],'model_digest':req['model_digest'],"
            "'prompt_sha256':hashlib.sha256(req['prompt'].encode()).hexdigest(),"
            "'max_tokens':req['max_tokens']}),flush=True)\n"
            "time.sleep(2)\n"
        )
        first = {"kind": "INVOKE", "prompt": "hi", "model": "test",
                 "model_digest": "a" * 64, "invocation_id": "one", "max_tokens": 2}
        with child(script), self.assertRaisesRegex(RuntimeError, "gateway callback"):
            broker._exchange(IMAGE, VOLUME, first, lambda *a, **kw: {"text": "unspecified"},
                             timeout_seconds=1)


if __name__ == "__main__":
    unittest.main()
