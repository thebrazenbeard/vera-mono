"""Cross-branch Goal 1 acceptance checks against exact source-file snapshots.

Run with four explicit paths to the real PR-head Python sources. No package
install, provider mutation, credential, model call, or learner truth access.
"""
import argparse
import json
from pathlib import Path
import unittest

from research.goal1_acceptance_bridge.probe import inspect_contracts


EXPECTED_SOURCE_SHA256 = {
    "qvr_journal": "4bff14c593c58dd5e328a02ad00d4f583dac4a04f6b55aa1ccebbe8adbee5351",
    "revision_receipt": "0db8df1d4710189c8c0d8feccd253b5d533cad9241315c7a2a5c4363cf258acb",
    "learner_binding": "4b8bd97330a81fa2ae32f6296c1db2fa7cc19a730316839ad2ba26b0e6e9d07d",
    "evaluator_controller": "99237cfd9c07c6b064538649b97fbcb23b301da36424c648706687fd443554f7",
}


class Goal1CrossBranchProbeTests(unittest.TestCase):
    paths = None

    @classmethod
    def setUpClass(cls):
        if cls.paths is None:
            raise AssertionError("exact #82/#86/#87 source paths required, never skip")

    def report(self):
        return inspect_contracts(*self.paths)

    def test_exact_pr_source_cut_is_pinned(self):
        self.assertEqual(self.report()["source_sha256"], EXPECTED_SOURCE_SHA256)

    def test_actual_binder_packet_reaches_actual_controller_and_fails_without_witness(self):
        report = self.report()
        self.assertTrue(report["protocol"]["public_packet_bound_to_actual_sources"])
        self.assertTrue(report["protocol"]["unwitnessed_commit_rejected"])
        self.assertTrue(report["protocol"]["self_report_rejected"])
        self.assertTrue(report["protocol"]["outcome_unknown_rejected"])

    def test_qvr_success_journal_reopens_but_timeout_not_reserved(self):
        report = self.report()
        self.assertTrue(report["protocol"]["local_qvr_receipt_reopened"])
        self.assertTrue(report["protocol"]["unrecorded_timeout_id_reusable"])
        self.assertFalse(report["qualification"]["passed"])

    def test_simulated_verifier_cannot_be_mistaken_for_independent_custody(self):
        report = self.report()
        self.assertTrue(report["protocol"]["test_only_verifier_accepted_synthetic_packet"])
        self.assertEqual(report["qualification"]["result"], "BLOCKED")
        self.assertIn("NO_INDEPENDENT_GATEWAY_ATTESTATION", report["qualification"]["blockers"])
        self.assertIn("NO_RESERVED_ATTEMPT_BEFORE_DISPATCH", report["qualification"]["blockers"])
        self.assertIn("NO_FOUR_ARM_COLD_RESTART_CONTROLLED_RESULT", report["qualification"]["blockers"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--journal", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--binding", required=True)
    p.add_argument("--controller", required=True)
    args = p.parse_args()
    Goal1CrossBranchProbeTests.paths = tuple(map(Path, (
        args.journal, args.revision, args.binding, args.controller,
    )))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Goal1CrossBranchProbeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("SOURCE_CONTRACT_PROBE=" + json.dumps(
            inspect_contracts(*Goal1CrossBranchProbeTests.paths), sort_keys=True
        ))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
