"""Probe a fact absent despite a valid synthetic PUBLIC source being present."""
from __future__ import annotations
import hashlib
import json
import unittest
from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import counterfactual_subject_eval as counter


class CounterfactualSubjectTests(unittest.TestCase):
    def run_eval(self, endpoint, variant="directory"):
        return counter.run_trial(
            endpoint=endpoint, model="vera:local", model_digest="b"*64,
            variant=variant, timeout_seconds=30)

    def test_source_present_but_requested_subject_missing_blocks_hallucinations(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant), FakeLocal(
                    answer=response(model="vera:local", text="G-FAKE0000")) as server:
                report = self.run_eval(server.url, variant=variant)
                self.assertEqual("MINI_VERA_COUNTERFACTUAL_SUBJECT_V1", report["schema"])
                self.assertEqual(6, report["model_http_calls"])
                self.assertEqual("COMPLETED_WITH_MODEL_FAILURES", report["status"])
                self.assertFalse(report["all_model_cases_pass"])
                self.assertEqual(0, report["raw_correct_cases"])
                self.assertEqual(0, report["guarded_positive_releases"])
                self.assertEqual(3, report["guarded_unknown_count"])
                self.assertEqual(3, len(report["cases"]))
                self.assertEqual(6, len(server.requests))
                by_arm = {item["arm"]:item for item in report["cases"]}
                self.assertEqual({"known_subject", "missing_subject_with_record",
                                  "missing_subject_without_record"}, set(by_arm))
                self.assertEqual("WITHHELD_NO_SUPPORTED_FACT_FOR_QUESTION",
                                 by_arm["missing_subject_with_record"]["client_status"])
                self.assertEqual("WITHHELD_NO_APPROVED_REFERENCE",
                                 by_arm["missing_subject_without_record"]["client_status"])
                self.assertEqual("WITHHELD_MODEL_NOT_SOURCE_MATCHED",
                                 by_arm["known_subject"]["client_status"])
                self.assertFalse(by_arm["missing_subject_with_record"]["raw_model_correct"])
                self.assertFalse(by_arm["missing_subject_without_record"]["raw_model_correct"])
                requests = [json.loads(req[1]["messages"][-1]["content"])
                            for req in server.requests]
                with_record = [x for x in requests if x["project_context_untrusted"]]
                without_record = [x for x in requests if not x["project_context_untrusted"]]
                self.assertEqual(4, len(with_record))
                self.assertEqual(2, len(without_record))
                for item in requests:
                    self.assertNotIn("SYNTHETIC_PRIVATE_NEVER_SEND_", json.dumps(item))
                    self.assertNotIn("canary-private", json.dumps(item))
                self.assertNotIn("G-FAKE0000", json.dumps(report))
                self.assertNotIn('"model_text":', json.dumps(report))
                self.assertEqual("SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
                                 report["evidence_ceiling"])

    def test_matching_source_positive_is_distinct_from_two_unsupported_cases(self):
        from contextlib import nullcontext
        from unittest.mock import patch
        with counter._temporary_fixture("directory") as fixture:
            with patch.object(counter, "_temporary_fixture",
                              return_value=nullcontext(fixture)):
                with FakeLocal(answer=response(
                        model="vera:local", text=fixture.expected)) as server:
                    report = self.run_eval(server.url)
                    self.assertEqual(1, report["raw_correct_cases"])
                    self.assertEqual(1, report["guarded_positive_releases"])
                    self.assertEqual(2, report["guarded_unknown_count"])
                    by_arm = {case["arm"]:case for case in report["cases"]}
                    self.assertTrue(by_arm["known_subject"]["raw_model_correct"])
                    self.assertTrue(by_arm["known_subject"]["client_positive_released"])
                    self.assertFalse(by_arm["missing_subject_with_record"]["raw_model_correct"])
                    self.assertFalse(by_arm["missing_subject_without_record"]["raw_model_correct"])
                    self.assertFalse(by_arm["missing_subject_with_record"]["client_positive_released"])
                    self.assertFalse(by_arm["missing_subject_without_record"]["client_positive_released"])
                    self.assertEqual(6, len(server.requests))
                    self.assertNotIn(fixture.expected, json.dumps(report))

    def test_neural_abstention_is_distinct_from_client_withholding(self):
        with FakeLocal(answer=response(model="vera:local", text="UNKNOWN")) as server:
            report = self.run_eval(server.url)
            self.assertEqual(2, report["raw_correct_cases"])
            self.assertFalse(report["all_model_cases_pass"])
            self.assertEqual(0, report["guarded_positive_releases"])
            self.assertEqual(3, report["guarded_unknown_count"])
            for item in report["cases"]:
                self.assertTrue(item["guarded_model_generated_abstention"])
            self.assertEqual(6, len(server.requests))

    def test_question_variants_target_missing_subject_outside_public_source(self):
        for variant in ("directory", "revision"):
            fixture = counter._temporary_fixture(variant)
            with fixture as case:
                self.assertNotEqual(case.known_question, case.missing_question)
                self.assertNotIn(case.missing_subject, case.public_text)
                self.assertIn(case.known_subject, case.public_text)
                self.assertNotIn(case.expected, case.known_question)
                self.assertNotIn(case.expected, case.missing_question)
                self.assertEqual(64, len(hashlib.sha256(
                    case.public_text.encode()).hexdigest()))

    def test_bad_endpoint_model_and_variant_fail_before_any_http(self):
        with FakeLocal(answer=response(model="vera:local", text="UNKNOWN")) as server:
            cases = [
                dict(endpoint="https://example.com/v1"),
                dict(endpoint=server.url, model_digest="bad"),
                dict(endpoint=server.url, variant="other"),
                dict(endpoint=server.url, timeout_seconds=0),
                dict(endpoint=server.url, model=""),
            ]
            for change in cases:
                with self.subTest(change=change):
                    options = {
                        "endpoint":server.url, "model":"vera:local",
                        "model_digest":"b"*64, "variant":"directory",
                        "timeout_seconds":12,
                    }
                    options.update(change)
                    with self.assertRaises(counter.CounterfactualRefused):
                        counter.run_trial(**options)
            self.assertEqual(0, len(server.requests))

    def test_http_failure_aborts_without_scored_success(self):
        with FakeLocal(status=503) as server:
            with self.assertRaises(counter.CounterfactualRefused):
                self.run_eval(server.url)
            self.assertEqual(1, len(server.requests))


if __name__ == "__main__":
    unittest.main()
