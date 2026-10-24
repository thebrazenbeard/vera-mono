"""Fail-closed Goal 1 current-head source versus independent-custody gate."""
from __future__ import annotations
from pathlib import Path
import tempfile
import unittest

from research.goal1_acceptance_bridge.terminal_v2_converged_readback import (
    compatibility_gate, freeze,
)


def make_report():
    cases = []
    for label in ("COMPLETED_0MS", "COMPLETED_1MS", "OUTCOME_UNKNOWN"):
        cases.append({
            "case": label, "original_signed_bytes_read_back": True,
            "exact_v2_accepted": True, "claim_substitution_rejected": True,
            "wire_tamper_rejected": True,
            "local_metadata_tamper_rejected": True,
            "qualified": False,
        })
    return {
        "classification": "SOURCE_INTEROP_ONLY",
        "independent_claim_custody": False,
        "cases": cases,
    }


class CurrentHeadGateTests(unittest.TestCase):
    def test_all_three_cases_are_required_for_source_gate(self):
        report = make_report()
        self.assertEqual(compatibility_gate(
            report, require_source=True, require_independent=False), 0)
        report["cases"].pop()
        self.assertEqual(compatibility_gate(
            report, require_source=True, require_independent=False), 2)

    def test_missing_or_forged_check_cannot_promote_source(self):
        report = make_report()
        del report["cases"][0]["local_metadata_tamper_rejected"]
        self.assertEqual(compatibility_gate(
            report, require_source=True, require_independent=False), 2)
        report = make_report()
        report["cases"][0]["qualified"] = True
        self.assertEqual(compatibility_gate(
            report, require_source=True, require_independent=False), 2)

    def test_fake_independence_claim_cannot_open_protected_gate(self):
        report = make_report()
        report["independent_claim_custody"] = True
        self.assertEqual(compatibility_gate(
            report, require_source=True, require_independent=True), 2)
        self.assertEqual(compatibility_gate(
            report, require_source=True, require_independent=False), 2)

    def test_even_valid_source_interop_cannot_claim_independent_effect(self):
        self.assertEqual(compatibility_gate(
            make_report(), require_source=True, require_independent=True), 2)

    def test_pinned_bytes_reject_source_substitution(self):
        with tempfile.TemporaryDirectory(prefix="goal1-source-pin-") as td:
            path = Path(td)/"gateway.py"
            path.write_text("print('untrusted')\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                freeze(path, "a"*64)


if __name__=="__main__":
    unittest.main()
