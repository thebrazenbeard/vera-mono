"""Separate-process source-only receipt custody negative-control policy."""
from __future__ import annotations
import unittest
from research.goal1_acceptance_bridge.cold_process_signed_terminal_probe import (
    report_gate,
)


def report():
    return {
        "classification":"PROCESS_SEPARATION_ONLY",
        "cases":[{
            "status":s,"new_process_verified":True,
            "source_restart_replay_refused":True,
            "tamper_paths_rejected":True,
            "common_owner_rewrite_accepted":True,
            "original_pin_rejects_rewrite":True,
            "independent_custody":False,
            "qualified":False,
        } for s in ("COMPLETED","OUTCOME_UNKNOWN")],
    }


class ColdProcessGateTests(unittest.TestCase):
    def test_strict_source_requires_two_distinct_terminal_states(self):
        r=report()
        self.assertEqual(report_gate(r,require_source=True,require_independent=False),0)
        r["cases"]=r["cases"][:1]
        self.assertEqual(report_gate(r,require_source=True,require_independent=False),2)

    def test_independent_gate_never_uses_same_user_process_separation(self):
        r=report()
        self.assertEqual(report_gate(r,require_source=True,require_independent=True),2)
        r["independent_claim_custody"]=True
        self.assertEqual(report_gate(r,require_source=True,require_independent=True),2)

    def test_missing_whole_directory_rewrite_negative_control_holds(self):
        r=report()
        r["cases"][0].pop("common_owner_rewrite_accepted")
        self.assertEqual(report_gate(r,require_source=True,require_independent=False),2)

    def test_missing_original_pinned_key_falsifier_holds(self):
        r=report()
        r["cases"][0].pop("original_pin_rejects_rewrite",None)
        self.assertEqual(report_gate(r,require_source=True,require_independent=False),2)

    def test_false_claim_of_rewrite_resistance_holds(self):
        r=report()
        r["cases"][0]["common_owner_rewrite_accepted"]=False
        self.assertEqual(report_gate(r,require_source=True,require_independent=False),2)

    def test_substituted_self_asserted_qualification_holds(self):
        r=report()
        r["cases"][1]["qualified"]=True
        self.assertEqual(report_gate(r,require_source=True,require_independent=False),2)

    def test_missing_replay_or_tamper_rejection_holds(self):
        for name in ("source_restart_replay_refused","tamper_paths_rejected"):
            r=report()
            r["cases"][0][name]=False
            self.assertEqual(report_gate(r,require_source=True,require_independent=False),2)


if __name__=="__main__":
    unittest.main()
