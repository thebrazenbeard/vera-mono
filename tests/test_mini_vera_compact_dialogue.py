"""Opt-in compact dialogue is bounded, source-pinned and not a fact gate."""
import contextlib
import hmac
import io
import unittest
from unittest import mock

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import compose, conversation_console, local_session, loopback


class CompactDialogueTests(unittest.TestCase):
    def request(self, mode=None, *, history=None):
        identity, iraw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, braw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        kwargs = dict(
            text="The fictional ship is Ember. What is its name?",
            turn_id="compact-test", history=history or [],
            identity=identity, identity_raw=iraw,
            behavior=behavior, behavior_raw=braw,
            state=state, key=key, revision=0,
            model="vera:test", model_digest="b"*64)
        if mode is not None:
            kwargs["dialogue_mode"] = mode
        return local_session.compose_local_turn(**kwargs)

    def test_opt_in_compact_is_direct_but_maintains_source_pins_and_json(self):
        unchanged = self.request()
        compact = self.request("compact")
        self.assertNotEqual(unchanged["request_sha256"], compact["request_sha256"])
        for field in ("identity_sha256", "behavior_sha256",
                      "model_registry_digest", "turn_sha256"):
            self.assertEqual(unchanged["provenance"][field],
                             compact["provenance"][field])
        self.assertEqual(unchanged["inference"]["messages"][-1],
                         compact["inference"]["messages"][-1])
        system = compact["inference"]["messages"][0]["content"].lower()
        self.assertIn("harmless fiction", system)
        self.assertIn("corrects a name", system)
        self.assertIn("private history", system)
        self.assertIn("not the hosted chatgpt model", system)
        loopback.validate_candidate(compact)

    def test_compact_keeps_two_turn_local_history_without_fake_persistence(self):
        prior = self.request()["inference"]["messages"][-1]
        history = [prior, {"role": "assistant", "content": "Ember."}]
        compact = self.request("compact", history=history)
        self.assertEqual(4, len(compact["inference"]["messages"]))
        self.assertEqual("VOLATILE_CALLER_SUPPLIED_NOT_ATTESTED",
                         compact["evidence"]["session_history"])
        loopback.validate_candidate(compact)

    def test_compact_rejects_synthetic_and_nonempty_public_records(self):
        identity, iraw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, braw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        args=dict(identity=identity,identity_raw=iraw,
                  behavior=behavior,behavior_raw=braw,
                  expected_identity_sha256=local_session.PINNED_IDENTITY_SHA256,
                  expected_behavior_sha256=local_session.PINNED_BEHAVIOR_SHA256,
                  state=state,key=key,expected_revision=0,
                  turn={"schema":"MINI_VERA_SYNTHETIC_TURN_V1",
                        "turn_id":"synthetic","scope":"SYNTHETIC_ONLY",
                        "user_text":"fiction"},model="vera:test",
                  model_digest="b"*64,dialogue_mode="compact")
        with self.assertRaises(compose.CompositionRejected):
            compose.compose(**args)

    def test_compact_rejects_even_valid_signed_public_record(self):
        identity, iraw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, braw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        state.pop("hmac_sha256")
        text = "synthetic, explicitly PUBLIC record"
        state["records"] = [{"record_id": "public-one",
            "record_class": "WORKING_PROJECT", "privacy": "PUBLIC",
            "instruction_trust": "DATA_NOT_INSTRUCTION",
            "authority_effect": "NONE",
            "source_sha256": compose.sha256(text.encode()), "text": text}]
        state["hmac_sha256"] = hmac.new(
            key, compose.canonical(state), "sha256").hexdigest()
        with self.assertRaises(compose.CompositionRejected):
            local_session.compose_local_turn(
                text="What is this project?", turn_id="record-should-refuse",
                history=[], identity=identity, identity_raw=iraw,
                behavior=behavior, behavior_raw=braw,
                state=state, key=key, revision=0,
                model="vera:test", model_digest="b"*64,
                dialogue_mode="compact")

    def test_cli_compact_exercises_existing_loopback_without_tools(self):
        with FakeLocal(answer=response(model="vera:test",text="Ember.")) as fake:
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                code=local_session.main([
                    "--endpoint",fake.url,"--model","vera:test",
                    "--model-digest","b"*64,"--execute",
                    "--host-idle-confirmed","--compact-dialogue",
                    "--prompt","The fictional ship is Ember. Name?"])
            self.assertEqual(0,code)
            self.assertEqual(1,len(fake.requests))
            system=fake.requests[0][1]["messages"][0]["content"].lower()
            self.assertIn("harmless fiction",system)
            self.assertIn("vera> ember.",out.getvalue().lower())

    def test_compact_fails_closed_before_http_for_synthetic_fact_gate(self):
        with FakeLocal(answer=response(model="vera:test",text="wrong")) as fake:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    local_session.main([
                        "--endpoint",fake.url,"--model","vera:test",
                        "--model-digest","b"*64,"--execute",
                        "--host-idle-confirmed","--structured-output",
                        "--synthetic-fact-evidence-gate","--compact-dialogue",
                        "--prompt","G-123"])
            self.assertEqual(2,error.exception.code)
            self.assertEqual(0,len(fake.requests))

    def test_console_forwards_compact_flag_only_when_selected(self):
        with mock.patch.object(conversation_console.ollama_preflight,"probe",
                               return_value={
                                 "status":"RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                                 "model":"qwen3.5:0.8b",
                                 "ollama_tag_digest":"a"*64}), \
             mock.patch.object(conversation_console.local_session,"main",
                               return_value=0) as session, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0,conversation_console.main([
                "--confirm-host-idle","--compact-dialogue","--prompt","Hi"]))
            self.assertIn("--compact-dialogue",session.call_args.args[0])
            self.assertEqual(0,conversation_console.main([
                "--confirm-host-idle","--prompt","Hi"]))
            self.assertNotIn("--compact-dialogue",session.call_args.args[0])


if __name__=="__main__":
    unittest.main()
