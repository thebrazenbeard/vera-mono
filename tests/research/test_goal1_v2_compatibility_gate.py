"""Fail-closed report policy for source-only terminal V2 interop.

These tests do not substitute a report for the required exact physical probe.
They prevent a successful positive sample from hiding the zero-ms falsifier.
"""
from __future__ import annotations

import unittest

from research.goal1_acceptance_bridge.terminal_v2_source_interop import (
    source_compatibility_exit_code,
)


def sample_case(status):
    return {
        "gateway_status":status,
        "signature_covers_exact_gateway_bytes":True,
        "malaphor_v2_accepted":True,
        "wrong_claim_rejected":True,
        "tampered_bytes_rejected":True,
        "independent_custody":False,
        "learning_qualified":False,
    }


def report():
    return {
        "verdict":"V2_SOURCE_COMPATIBLE_ONLY",
        "cases":[sample_case("COMPLETED"),sample_case("OUTCOME_UNKNOWN")],
        "zero_ms_contract_boundary":{"malaphor_v2_rejected_zero_ms":True},
    }


class V2CompatibilityReportTests(unittest.TestCase):
    def test_positive_samples_cannot_hide_zero_ms_rejection(self):
        self.assertEqual(source_compatibility_exit_code(report(),require_compatible=True),2)
        self.assertEqual(source_compatibility_exit_code(report(),require_compatible=False),0)

    def test_missing_zero_duration_boundary_cannot_pass_strict(self):
        result=report()
        del result["zero_ms_contract_boundary"]
        self.assertEqual(source_compatibility_exit_code(result,require_compatible=True),2)

    def test_one_accepted_terminal_is_not_enough(self):
        result=report()
        result["zero_ms_contract_boundary"]["malaphor_v2_rejected_zero_ms"]=False
        result["cases"][1]["malaphor_v2_accepted"]=False
        self.assertEqual(source_compatibility_exit_code(result,require_compatible=True),2)

    def test_duplicate_or_missing_terminal_is_not_enough(self):
        result=report()
        result["zero_ms_contract_boundary"]["malaphor_v2_rejected_zero_ms"]=False
        result["cases"]=result["cases"][:1]
        self.assertEqual(source_compatibility_exit_code(result,require_compatible=True),2)

    def test_self_asserted_custody_is_not_compatible(self):
        result=report()
        result["zero_ms_contract_boundary"]["malaphor_v2_rejected_zero_ms"]=False
        result["cases"][0]["independent_custody"]=True
        self.assertEqual(source_compatibility_exit_code(result,require_compatible=True),2)


if __name__=="__main__":
    unittest.main()
