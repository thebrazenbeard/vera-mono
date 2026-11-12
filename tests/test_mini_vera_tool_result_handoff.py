"""Host-controlled source-observation handoff to neural inference, no model tool authority."""
from __future__ import annotations
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch
import io
import json
import hashlib
import unittest

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import host_read_probe, local_session, loopback, compose, ollama_preflight


def args(url, *extra):
    return ["--endpoint", url, "--model", "vera:local",
            "--model-digest", "b"*64, "--execute", "--host-idle-confirmed",
            "--structured-output", "--host-read-probe", "--prompt",
            "What precise local code did the host inspect? Give the source SHA-256.",
            *extra]


class ToolResultHandoffTests(unittest.TestCase):
    def test_explicit_delivery_produces_one_bounded_neural_call_and_separate_receipt(self):
        with FakeLocal(answer=response(model="vera:local", text="Read-only code observed.")) as server:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = local_session.main(args(server.url, "--deliver-host-observation"))
            self.assertEqual(status, 0)
            self.assertEqual(1, len(server.requests))
        sent = server.requests[0][1]
        self.assertEqual([m["role"] for m in sent["messages"]], ["system", "user"])
        user = json.loads(sent["messages"][-1]["content"])
        observed = user["host_tool_observation"]
        self.assertEqual(observed["schema"], "MINI_VERA_HOST_SOURCE_OBSERVATION_V1")
        self.assertEqual(observed["trust"], "LOCALLY_OBSERVED_UNSIGNED_DATA")
        self.assertEqual(observed["authority_effect"], "NONE")
        self.assertEqual(observed["source_name"], "tools/mini_vera/compose.py")
        self.assertEqual(observed["source_sha256"], hashlib.sha256(
            Path(local_session.__file__).with_name("compose.py").read_bytes()).hexdigest())
        envelope = json.loads(stdout.getvalue().strip())
        self.assertEqual(envelope["model"]["trust"], "UNVERIFIED_GENERATIVE_TEXT")
        self.assertEqual(envelope["client"]["tool_actions_executed"], 1)
        self.assertEqual(envelope["client"]["host_attestation"], "NOT_PROVIDED")
        self.assertTrue(envelope["client"]["host_observation_delivered"])
        receipt = envelope["client"]["tool_receipts"][0]
        self.assertEqual(receipt["request_sha256"], observed["base_request_sha256"])
        self.assertEqual(receipt["source_sha256"], observed["source_sha256"])

    def test_client_source_answer_remains_exact_when_model_invents_other_digest(self):
        fake = "The observed SHA is " + ("0" * 64)
        with FakeLocal(answer=response(model="vera:local", text=fake)) as server:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, local_session.main(
                    args(server.url, "--deliver-host-observation")))
        envelope = json.loads(output.getvalue())
        answer = envelope["client"]["source_answer"]
        receipt = envelope["client"]["tool_receipts"][0]
        self.assertEqual("MINI_VERA_LOCAL_SOURCE_ANSWER_V1", answer["schema"])
        self.assertEqual(receipt["source_sha256"], answer["source_sha256"])
        self.assertEqual(receipt["source_name"], answer["source_name"])
        self.assertEqual("CLIENT_SOURCE_RECEIPT_NOT_MODEL", answer["origin"])
        self.assertEqual("LOCAL_UNSIGNED_CONSISTENCY_NOT_HOST_ATTESTATION",
                         answer["trust"])
        self.assertEqual(fake, envelope["model"]["text"])
        self.assertNotEqual(answer["source_sha256"], "0" * 64)

    def test_unapproved_delivery_refused_before_http(self):
        for extra in (
            ["--deliver-host-observation"],
            ["--host-read-probe", "--deliver-host-observation"]
        ):
            with FakeLocal(answer=response(model="vera:local")) as server:
                controls = ["--endpoint", server.url, "--model", "vera:local",
                            "--model-digest", "b"*64, "--execute",
                            "--host-idle-confirmed", "--prompt", "hello", *extra]
                with redirect_stderr(io.StringIO()) as errors:
                    with self.assertRaises(SystemExit) as ctx:
                        local_session.main(controls)
                self.assertEqual(2, ctx.exception.code)
                self.assertIn("--deliver-host-observation requires", errors.getvalue())
                self.assertEqual([], server.requests)

    def test_tampered_projected_source_cannot_be_rehashed_to_bypass_validator(self):
        identity, ir = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, br = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        request = local_session.compose_local_turn(
            text="Give source checksum", turn_id="synthetic-tool-test",
            history=[], identity=identity, identity_raw=ir,
            behavior=behavior, behavior_raw=br, state=state, key=key,
            revision=0, model="vera:local", model_digest="b"*64)
        receipt = host_read_probe.observe_source(request["request_sha256"])
        request = local_session.attach_host_source_observation(request, receipt)
        loopback.validate_candidate(request)
        inner = json.loads(request["inference"]["messages"][-1]["content"])
        inner["host_tool_observation"]["source_sha256"] = "0"*64
        request["inference"]["messages"][-1]["content"] = compose.canonical(inner).decode()
        request["request_sha256"] = compose.sha256(compose.canonical(request["inference"]))
        with self.assertRaises(loopback.LoopbackRejected):
            loopback.validate_candidate(request)

    def test_replayed_observation_from_previous_turn_is_rejected(self):
        identity, ir = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, br = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        def one(turn_id):
            return local_session.compose_local_turn(
                text="Inspect only compose.py", turn_id=turn_id, history=[],
                identity=identity, identity_raw=ir, behavior=behavior,
                behavior_raw=br, state=state, key=key, revision=0,
                model="vera:local", model_digest="b"*64)
        prior = one("synthetic-first-turn")
        prior_receipt = host_read_probe.observe_source(prior["request_sha256"])
        prior = local_session.attach_host_source_observation(prior, prior_receipt)
        fresh = one("synthetic-next-turn")
        previous_envelope = json.loads(prior["inference"]["messages"][-1]["content"])
        fresh["inference"]["messages"][-1]["content"] = compose.canonical(
            previous_envelope).decode()
        fresh["request_sha256"] = compose.sha256(compose.canonical(
            fresh["inference"]))
        with self.assertRaises(loopback.LoopbackRejected):
            loopback.validate_candidate(fresh)

    def test_probe_failure_prevents_model_call_and_output(self):
        with FakeLocal(answer=response(model="vera:local", text="never display")) as server:
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(host_read_probe, "SOURCE_PATH", Path("Z:/missing/source.py")), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(local_session.main(
                    args(server.url, "--deliver-host-observation")), 2)
            self.assertEqual([], server.requests)
            self.assertNotIn("never display", output.getvalue())
            self.assertIn("source bytes unavailable", errors.getvalue())

    def test_postinference_revocation_withholds_both_model_and_client_receipt(self):
        state, key = local_session.empty_public_state()
        calls = 0
        def provider():
            nonlocal calls
            calls += 1
            if calls == 1: return state, key, 0
            raise ValueError("permission revoked")
        with FakeLocal(answer=response(model="vera:local", text="not for output")) as server:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                status = local_session.main(args(server.url, "--deliver-host-observation"),
                                            live_public_provider=provider)
            self.assertEqual(status, 2)
            self.assertEqual(1, len(server.requests))
            self.assertNotIn("not for output", out.getvalue())
            self.assertNotIn("MINI_VERA_LOCAL_OUTPUT_V1", out.getvalue())

    def test_preflight_rejects_delivery_without_execution(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as x:
            ollama_preflight.main(["--deliver-host-observation"])
        self.assertEqual(x.exception.code, 2)
        self.assertIn("--deliver-host-observation requires", err.getvalue())


if __name__ == "__main__":
    unittest.main()
