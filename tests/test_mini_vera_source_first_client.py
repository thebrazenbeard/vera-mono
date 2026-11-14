"""TDD: source-first client fact release is separate from neural correctness."""
from __future__ import annotations
import contextlib
import io
import json
import unittest

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import compose, counterfactual_subject_eval as counter
from tools.mini_vera import local_session, public_fact_guard as guard


class SourceFirstClientGateTests(unittest.TestCase):
    def make_request(self, question, provider=None):
        if provider is None:
            state, key = local_session.empty_public_state()
            revision = 0
        else:
            state, key, revision = provider()
        identity, iraw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, braw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        request = local_session.compose_local_turn(
            text=question, turn_id="synthetic-source-first",
            history=[], identity=identity, identity_raw=iraw,
            behavior=behavior, behavior_raw=braw,
            state=state, key=key, revision=revision,
            model="vera:local", model_digest="b"*64)
        return request, (state, key, revision) if provider is not None else None

    def model_record(self, request, text, status="UNVERIFIED_LOCAL_MODEL_OUTPUT"):
        return {
            "schema": "MINI_VERA_LOCAL_OUTPUT_V1",
            "request_sha256": request["request_sha256"],
            "model": {
                "text": text, "status": status,
                "trust": "UNVERIFIED_GENERATIVE_TEXT",
            },
            "client": {"tool_actions_executed": 0, "tool_receipts": []},
        }

    def test_opt_in_uses_exact_approved_source_when_model_invents_wrong_gate(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant), counter._temporary_fixture(variant) as case:
                req, binding = self.make_request(case.known_question, case.provider)
                wrong = self.model_record(req, "G-00000000")
                old = guard.apply(req, wrong, approved_state_binding=binding)
                self.assertEqual("UNKNOWN", old["client"]["fact_gate"]["client_answer"])
                new = guard.apply(req, wrong, approved_state_binding=binding,
                                  source_first=True)
                gate = new["client"]["fact_gate"]
                self.assertEqual(case.expected, gate["client_answer"])
                self.assertEqual("SOURCE_FIRST_SYNTHETIC_RECORD_NOT_HOST_ATTESTATION",
                                 gate["status"])
                self.assertEqual("CLIENT_DETERMINISTIC_SYNTHETIC_SOURCE_NOT_NEURAL",
                                 gate["client_answer_origin"])
                self.assertTrue(gate["source_first_mode"])
                self.assertFalse(gate["model_exact_source_match"])
                self.assertFalse(gate["model_generated_abstention"])
                self.assertFalse(gate["host_issuer_qualified"])
                self.assertEqual("POST_APPROVAL_STATE_CONSISTENT_NOT_HOST_ATTESTED",
                                 gate["source_binding"])
                self.assertIsNone(new["model"]["text"])
                self.assertNotIn("G-00000000", json.dumps(new))

    def test_client_answer_does_not_depend_on_neural_sample_or_truncation(self):
        with counter._temporary_fixture("revision") as case:
            req, binding = self.make_request(case.known_question, case.provider)
            for text,status in (
                ("UNKNOWN", "UNVERIFIED_LOCAL_MODEL_OUTPUT"),
                ("G-00000000", "UNVERIFIED_LOCAL_MODEL_OUTPUT"),
                ("G-00000000", "TRUNCATED_UNVERIFIED_OUTPUT"),
            ):
                with self.subTest(text=text,status=status):
                    response_data = guard.apply(
                        req, self.model_record(req, text, status),
                        approved_state_binding=binding, source_first=True)
                    gate = response_data["client"]["fact_gate"]
                    self.assertEqual(case.expected, gate["client_answer"])
                    self.assertFalse(gate["model_exact_source_match"])
                    self.assertEqual(status, response_data["model"]["status"])
                    self.assertIsNone(response_data["model"]["text"])
                    self.assertEqual("CLIENT_DETERMINISTIC_SYNTHETIC_SOURCE_NOT_NEURAL",
                                     gate["client_answer_origin"])

    def test_missing_subject_with_irrelevant_public_record_must_remain_unknown(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant), counter._temporary_fixture(variant) as case:
                req, binding = self.make_request(case.missing_question, case.provider)
                record = self.model_record(req, case.expected)
                output = guard.apply(
                    req, record, approved_state_binding=binding, source_first=True)
                gate = output["client"]["fact_gate"]
                self.assertEqual("UNKNOWN", gate["client_answer"])
                self.assertEqual("WITHHELD_NO_SUPPORTED_FACT_FOR_QUESTION",
                                 gate["status"])
                self.assertFalse(gate["model_exact_source_match"])
                self.assertFalse(gate["host_issuer_qualified"])
                self.assertIsNone(output["model"]["text"])

    def test_no_public_source_or_missing_live_binding_never_releases(self):
        with counter._temporary_fixture("revision") as case:
            req, binding = self.make_request(case.known_question, case.provider)
            forged = self.model_record(req, case.expected)
            no_binding = guard.apply(req, forged, source_first=True)
            self.assertEqual("UNKNOWN", no_binding["client"]["fact_gate"]["client_answer"])
            self.assertEqual("WITHHELD_NO_LIVE_SOURCE_BINDING",
                             no_binding["client"]["fact_gate"]["status"])
            empty_req, _ = self.make_request(case.known_question)
            none = guard.apply(empty_req, self.model_record(empty_req, case.expected),
                               source_first=True)
            self.assertEqual("UNKNOWN", none["client"]["fact_gate"]["client_answer"])
            self.assertEqual("WITHHELD_NO_APPROVED_REFERENCE",
                             none["client"]["fact_gate"]["status"])
            with self.assertRaises(guard.GuardRefused):
                guard.apply(req, forged,
                            approved_state_binding=(
                                {**binding[0], "revision": 111},
                                binding[1], 111), source_first=True)

    def test_non_boolean_mode_or_forged_output_envelope_fails_closed(self):
        with counter._temporary_fixture("revision") as case:
            req, binding = self.make_request(case.known_question, case.provider)
            record = self.model_record(req, "G-FAKE1234")
            with self.assertRaises(guard.GuardRefused):
                guard.apply(req, record, approved_state_binding=binding, source_first=1)
            record["client"]["injected_text"] = "G-LEAK0000"
            with self.assertRaises(guard.GuardRefused):
                guard.apply(req, record, approved_state_binding=binding, source_first=True)

    def test_real_fake_http_opt_in_cli_returns_source_even_if_model_wrong(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant), counter._temporary_fixture(variant) as case:
                calls = 0
                def provider():
                    nonlocal calls
                    calls += 1
                    return case.provider()
                with FakeLocal(answer=response(model="vera:local", text="G-00000000")) as server:
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = local_session.main([
                            "--endpoint", server.url, "--model", "vera:local",
                            "--model-digest", "b"*64, "--execute",
                            "--host-idle-confirmed", "--structured-output",
                            "--synthetic-fact-evidence-gate",
                            "--synthetic-source-first", "--prompt", case.known_question,
                        ], live_public_provider=provider)
                    self.assertEqual(0, code)
                    self.assertEqual(1, len(server.requests))
                    self.assertEqual(2, calls)
                    result = json.loads(output.getvalue())
                    gate = result["client"]["fact_gate"]
                    self.assertEqual(case.expected, gate["client_answer"])
                    self.assertEqual("SOURCE_FIRST_SYNTHETIC_RECORD_NOT_HOST_ATTESTATION",
                                     gate["status"])
                    self.assertIsNone(result["model"]["text"])
                    self.assertNotIn("G-00000000", output.getvalue())

    def test_live_revocation_prevents_source_first_even_when_model_says_yes(self):
        with counter._temporary_fixture("revision") as case:
            calls = 0
            def provider():
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise ValueError("approval revoked")
                return case.provider()
            with FakeLocal(answer=response(model="vera:local", text=case.expected)) as server:
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    code = local_session.main([
                        "--endpoint", server.url, "--model", "vera:local",
                        "--model-digest", "b"*64, "--execute",
                        "--host-idle-confirmed", "--structured-output",
                        "--synthetic-fact-evidence-gate",
                        "--synthetic-source-first", "--prompt", case.known_question,
                    ], live_public_provider=provider)
                self.assertEqual(2, code)
                self.assertEqual(2, calls)
                self.assertEqual(1, len(server.requests))
                self.assertEqual("", output.getvalue())
                self.assertIn("withheld", error.getvalue())

    def test_source_first_flag_without_synthetic_gate_refused_before_http(self):
        with FakeLocal(answer=response(model="vera:local", text="UNKNOWN")) as server:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    local_session.main([
                        "--endpoint", server.url, "--model", "vera:local",
                        "--model-digest", "b"*64, "--execute",
                        "--host-idle-confirmed", "--structured-output",
                        "--synthetic-source-first", "--prompt",
                        "For cargo C-12345678, what is the gate?",
                    ])
            self.assertEqual(2, caught.exception.code)
            self.assertEqual(0, len(server.requests))


    def test_source_only_cli_returns_exact_r2_answer_without_any_model_http(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant), counter._temporary_fixture(variant) as case:
                calls = 0
                def provider():
                    nonlocal calls
                    calls += 1
                    return case.provider()
                with FakeLocal(answer=response(model="vera:local", text="G-00000000")) as server:
                    out=io.StringIO()
                    with contextlib.redirect_stdout(out):
                        code=local_session.main([
                            "--endpoint", server.url, "--model", "vera:local",
                            "--model-digest", "b"*64, "--structured-output",
                            "--synthetic-source-only", "--prompt", case.known_question,
                        ], live_public_provider=provider)
                    self.assertEqual(0,code)
                    self.assertEqual(2,calls)
                    self.assertEqual(0,len(server.requests))
                    record=json.loads(out.getvalue())
                    self.assertEqual("MINI_VERA_SYNTHETIC_SOURCE_ONLY_V1",record["schema"])
                    self.assertEqual("SOURCE_FIRST_SYNTHETIC_RECORD_NOT_HOST_ATTESTATION",
                                     record["status"])
                    self.assertEqual(case.expected,record["client_answer"])
                    self.assertEqual("CLIENT_DETERMINISTIC_SYNTHETIC_SOURCE_NOT_NEURAL",
                                     record["client_answer_origin"])
                    self.assertEqual(0,record["model_http_calls"])
                    self.assertFalse(record["neural_evaluation_performed"])
                    self.assertFalse(record["host_issuer_qualified"])
                    self.assertEqual("POST_APPROVAL_STATE_CONSISTENT_NOT_HOST_ATTESTED",
                                     record["source_binding"])

    def test_source_only_missing_subject_with_record_is_unknown_without_http(self):
        with counter._temporary_fixture("revision") as case:
            with FakeLocal(answer=response(model="vera:local",text=case.expected)) as server:
                out=io.StringIO()
                with contextlib.redirect_stdout(out):
                    code=local_session.main([
                        "--endpoint",server.url,"--model","vera:local",
                        "--model-digest","b"*64,"--structured-output",
                        "--synthetic-source-only","--prompt",case.missing_question,
                    ],live_public_provider=case.provider)
                self.assertEqual(0,code)
                self.assertEqual(0,len(server.requests))
                result=json.loads(out.getvalue())
                self.assertEqual("UNKNOWN",result["client_answer"])
                self.assertEqual("WITHHELD_NO_SUPPORTED_FACT_FOR_QUESTION",
                                 result["status"])
                self.assertFalse(result["neural_evaluation_performed"])

    def test_source_only_revocation_or_state_mutation_stops_before_release(self):
        with counter._temporary_fixture("revision") as case:
            for mutation in ("revoked","modified"):
                with self.subTest(mutation=mutation):
                    calls=0
                    def provider():
                        nonlocal calls
                        calls+=1
                        state,key,revision=case.provider()
                        if calls==2:
                            if mutation=="revoked":
                                raise ValueError("approval revoked")
                            state["revision"]=revision+1
                        return state,key,revision
                    with FakeLocal(answer=response(model="vera:local",text=case.expected)) as server:
                        out,err=io.StringIO(),io.StringIO()
                        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
                            code=local_session.main([
                                "--endpoint",server.url,"--model","vera:local",
                                "--model-digest","b"*64,"--structured-output",
                                "--synthetic-source-only","--prompt",case.known_question,
                            ],live_public_provider=provider)
                        self.assertEqual(2,code)
                        self.assertEqual(2,calls)
                        self.assertEqual(0,len(server.requests))
                        self.assertEqual("",out.getvalue())
                        self.assertIn("withheld",err.getvalue())

    def test_source_only_without_provider_or_with_http_execute_is_refused(self):
        with counter._temporary_fixture("revision") as case:
            with FakeLocal(answer=response(model="vera:local",text=case.expected)) as server:
                options=[
                    (["--synthetic-source-only"],None),
                    (["--synthetic-source-only","--execute","--host-idle-confirmed"],case.provider),
                    (["--synthetic-source-only","--synthetic-fact-evidence-gate"],case.provider),
                ]
                for extra, provider in options:
                    with self.subTest(extra=extra):
                        argv=[
                            "--endpoint",server.url,"--model","vera:local",
                            "--model-digest","b"*64,"--structured-output",
                            "--prompt",case.known_question,*extra]
                        with contextlib.redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit) as error:
                                local_session.main(argv, live_public_provider=provider)
                        self.assertEqual(2,error.exception.code)
                        self.assertEqual(0,len(server.requests))

    def test_direct_source_only_api_requires_binding_even_for_matching_record(self):
        with counter._temporary_fixture("revision") as case:
            req,binding=self.make_request(case.known_question,case.provider)
            with self.assertRaises(guard.GuardRefused):
                guard.resolve_source_only(req, None)
            result=guard.resolve_source_only(req,binding)
            self.assertEqual(case.expected,result["client_answer"])
            self.assertEqual(0,result["model_http_calls"])
            self.assertFalse(result["neural_evaluation_performed"])
            with self.assertRaises(guard.GuardRefused):
                guard.resolve_source_only(req,(binding[0],b"x"*32,binding[2]))
if __name__ == "__main__":
    unittest.main()
