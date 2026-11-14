"""Controlled same-model prompt ablation; tests precede implementation."""
from __future__ import annotations
import json
from unittest import TestCase, main
from unittest.mock import patch
from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import prompt_ablation as study
from tools.mini_vera import counterfactual_subject_eval as cases


class PromptAblationTests(TestCase):
    def test_same_question_and_records_for_each_arm_with_only_system_changed(self):
        with FakeLocal(answer=response(model="vera:local", text="G-FAKE0000")) as server:
            report = study.run_trial(
                endpoint=server.url, model="vera:local",
                model_digest="b"*64, variant="directory", timeout_seconds=30)
            self.assertEqual(9, len(server.requests))
        self.assertEqual("MINI_VERA_PROMPT_ABLATION_V1", report["schema"])
        self.assertEqual(9, report["http_calls"])
        self.assertFalse(report["model_behavior_qualified"])
        self.assertEqual("SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
                         report["evidence_ceiling"])
        self.assertEqual({"baseline", "explicit_abstain", "exact_subject_lookup"},
                         set(report["arm_results"]))
        requests = [r[1] for r in server.requests]
        by_user = {}
        for payload in requests:
            self.assertEqual({"model","messages","stream","temperature","max_tokens",
                              "seed","reasoning_effort"}, set(payload))
            self.assertEqual(0, payload["temperature"])
            self.assertEqual(256, payload["max_tokens"])
            self.assertEqual(20261106, payload["seed"])
            self.assertEqual("none", payload["reasoning_effort"])
            self.assertEqual(2, len(payload["messages"]))
            self.assertNotIn("SYNTHETIC_PRIVATE_NEVER_SEND_",json.dumps(payload))
            self.assertNotIn("canary-private",json.dumps(payload))
            user = payload["messages"][-1]["content"]
            by_user.setdefault(user, set()).add(payload["messages"][0]["content"])
        self.assertEqual(3,len(by_user))
        for systems in by_user.values():
            self.assertEqual(3,len(systems))
        self.assertNotIn("G-FAKE0000",json.dumps(report))
        for arm in report["arm_results"].values():
            self.assertEqual(0, arm["raw_exact_count"])
            self.assertEqual(0, arm["missing_fact_abstentions"])
            self.assertEqual(0, arm["supported_fact_hits"])

    def test_controlled_fake_model_helps_only_when_prompt_requires_abstention(self):
        with cases._temporary_fixture("revision") as fixture:
            def model(payload, *, endpoint, timeout_seconds):
                user = json.loads(payload["messages"][-1]["content"])
                system = payload["messages"][0]["content"]
                question = user["local_user_turn"]
                is_known = question == fixture.known_question
                explicit = "MINI_VERA_EXPLICIT_UNKNOWN_RULE" in system
                lookup = "MINI_VERA_EXACT_SUBJECT_RULE" in system
                text = fixture.expected if is_known else (
                    "UNKNOWN" if explicit or lookup else "G-FAKE0000")
                return {"text":text, "finish_reason":"stop",
                        "elapsed_ms":10.0,"response_sha256":study.loopback.sha256(text.encode())}
            with patch.object(study.counter, "_temporary_fixture",
                              return_value=__import__("contextlib").nullcontext(fixture)):
                with patch.object(study.blind_compare,"_one_call",
                                  side_effect=model) as stub:
                    report = study.run_trial(
                        endpoint="http://127.0.0.1:11451/v1",
                        model="vera:local",model_digest="b"*64,
                        variant="revision", timeout_seconds=30)
            self.assertEqual(9, stub.call_count)
            baseline = report["arm_results"]["baseline"]
            self.assertEqual(1, baseline["raw_exact_count"])
            self.assertEqual(0, baseline["missing_fact_abstentions"])
            for name in ("explicit_abstain","exact_subject_lookup"):
                item=report["arm_results"][name]
                self.assertEqual(3,item["raw_exact_count"])
                self.assertEqual(2,item["missing_fact_abstentions"])
                self.assertEqual(1,item["supported_fact_hits"])
            self.assertNotIn(fixture.expected,json.dumps(report))
            self.assertNotIn("G-FAKE0000",json.dumps(report))
            self.assertFalse(report["independent_heldout"])

    def test_response_truncation_fails_neural_accuracy_instead_of_being_scored(self):
        def returns_truncated(_payload, *, endpoint, timeout_seconds):
            return {"text":"UNKNOWN","finish_reason":"length",
                    "elapsed_ms":5.0,"response_sha256":study.loopback.sha256(b"UNKNOWN")}
        with patch.object(study.blind_compare,"_one_call",side_effect=returns_truncated):
            report=study.run_trial(endpoint="http://127.0.0.1:11451/v1",
                model="vera:local",model_digest="b"*64,
                variant="directory",timeout_seconds=30)
        for result in report["arm_results"].values():
            self.assertEqual(0,result["raw_exact_count"])
            self.assertEqual(3,result["truncated_count"])
            self.assertEqual(0,result["missing_fact_abstentions"])
        self.assertEqual("COMPLETED_WITH_TRUNCATIONS",report["status"])

    def test_bad_arguments_refuse_before_http(self):
        cases_bad=[
            {"endpoint":"https://example.com/v1"},
            {"model_digest":"bad"},
            {"model":""},
            {"variant":"unrecognized"},
            {"timeout_seconds":10},
            {"timeout_seconds":True},
        ]
        with patch.object(study.blind_compare,"_one_call") as stub:
            for change in cases_bad:
                with self.subTest(change=change):
                    kwargs=dict(endpoint="http://127.0.0.1:11451/v1",
                        model="vera:local",model_digest="b"*64,
                        variant="directory",timeout_seconds=30)
                    kwargs.update(change)
                    with self.assertRaises(study.AblationRefused):
                        study.run_trial(**kwargs)
        stub.assert_not_called()

    def test_http_error_aborts_without_promoting_partial_score(self):
        count=0
        def broken(*a,**k):
            nonlocal count
            count+=1
            if count==4:
                raise study.loopback.LoopbackRejected("transport failed")
            return {"text":"UNKNOWN","finish_reason":"stop","elapsed_ms":1.0,
                    "response_sha256":study.loopback.sha256(b"UNKNOWN")}
        with patch.object(study.blind_compare,"_one_call",side_effect=broken):
            with self.assertRaises(study.AblationAborted) as err:
                study.run_trial(endpoint="http://127.0.0.1:11451/v1",
                    model="vera:local",model_digest="b"*64,
                    variant="directory",timeout_seconds=30)
        self.assertEqual(4,err.exception.attempted)
        self.assertEqual("INVALID_OR_UNAVAILABLE_REPLY",err.exception.reason)

    def test_validation_only_has_no_network_effect(self):
        with patch.object(study.blind_compare,"_one_call") as call:
            code=study.main(["--endpoint","http://127.0.0.1:11451/v1",
                "--model","vera:local","--model-digest","b"*64,
                "--variant","directory"])
        self.assertEqual(0,code)
        call.assert_not_called()


if __name__=="__main__":
    main()
