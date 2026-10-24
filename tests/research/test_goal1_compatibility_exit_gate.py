"""Strict exit gate for the frozen Goal 1 cross-owner signed-terminal probe.

Diagnostic mode can succeed while accurately reporting incompatibility.
Qualification-minded consumers must fail closed on that same report.
"""
from __future__ import annotations

import unittest

from research.goal1_acceptance_bridge.gateway_evaluator_contract_probe import compatibility_exit_code


class CompatibilityExitGateTests(unittest.TestCase):
    def test_diagnostic_result_does_not_raise_process_failure(self):
        report={"verdict": "BLOCKED_DIFFERENT_SIGNED_TERMINAL_SCHEMAS"}
        self.assertEqual(compatibility_exit_code(report, require_compatible=False), 0)

    def test_strict_result_is_nonzero_on_observed_schema_mismatch(self):
        report={"verdict": "BLOCKED_DIFFERENT_SIGNED_TERMINAL_SCHEMAS",
                "terminal_cases": [
                    {"gateway_status":"COMPLETED",
                     "malaphor_evaluator_directly_accepted_terminal": False},
                    {"gateway_status":"OUTCOME_UNKNOWN",
                     "malaphor_evaluator_directly_accepted_terminal": False},
                ]}
        self.assertEqual(compatibility_exit_code(report, require_compatible=True), 2)

    def test_strict_uses_exact_case_verification_not_a_claimed_verdict(self):
        report={"verdict":"SOURCE_SCHEMA_DIRECTLY_COMPATIBLE",
                "terminal_cases": [
                    {"gateway_status":"COMPLETED",
                     "malaphor_evaluator_directly_accepted_terminal": True},
                    {"gateway_status":"OUTCOME_UNKNOWN",
                     "malaphor_evaluator_directly_accepted_terminal": False},
                ]}
        self.assertEqual(compatibility_exit_code(report, require_compatible=True), 2)

    def test_strict_rejects_missing_or_duplicated_cases(self):
        cases=({"gateway_status":"COMPLETED",
                "malaphor_evaluator_directly_accepted_terminal":True},)
        report={"verdict":"SOURCE_SCHEMA_DIRECTLY_COMPATIBLE",
                "terminal_cases":list(cases)}
        self.assertEqual(compatibility_exit_code(report, require_compatible=True), 2)
        report["terminal_cases"]=list(cases)*2
        self.assertEqual(compatibility_exit_code(report, require_compatible=True), 2)

    def test_strict_rejects_self_claimed_independent_attestation(self):
        report={"verdict":"SOURCE_SCHEMA_DIRECTLY_COMPATIBLE",
                "terminal_cases": [
                    {"gateway_status":x,
                     "malaphor_evaluator_directly_accepted_terminal":True,
                     "independent_attestation":True}
                    for x in ("COMPLETED","OUTCOME_UNKNOWN")],
                "test_key_custody":"SAME_PROCESS_EPHEMERAL_NOT_INDEPENDENT"}
        self.assertEqual(compatibility_exit_code(report, require_compatible=True), 2)


if __name__=="__main__":
    unittest.main()
