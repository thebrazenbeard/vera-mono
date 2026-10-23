"""Adversarial tests for the isolated Goal 1 evaluator scaffold."""
from dataclasses import replace
import unittest, tempfile, subprocess, sys, json, os
from pathlib import Path
from research.goal1_evaluator.acceptance import Evaluator, EventJournal, commit_prediction, make_reversal_suite


class EvaluatorFalsificationTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.truth = make_reversal_suite()
        self.evaluator = Evaluator(self.cases, self.truth)

    def receipts(self, cases, candidate="candidate-v1", predict=None, start=1, budget=3):
        predict = predict or (lambda case: "A")
        return tuple(commit_prediction(case=c, candidate_id=candidate, prediction=predict(c), commit_sequence=start+i, budget_units=budget) for i,c in enumerate(cases))

    def test_learner_view_excludes_answer_key(self):
        view = self.cases[0].learner_view()
        self.assertNotIn("expected_label", view)
        self.assertNotIn("answer", view)
        self.assertNotIn(self.truth[self.cases[0].case_id], view.values())

    def test_scorer_uses_controller_truth_not_candidate_supplied_labels(self):
        cases = self.evaluator.public_cases(split="qualification")
        rows = self.receipts(cases, predict=lambda c: "poisoned-label")
        self.assertEqual(self.evaluator.score(rows, outcome_sequence=99).accuracy, 0.0)

    def test_candidate_cannot_select_scoring_split_per_call(self):
        rows = self.receipts(self.evaluator.public_cases(split="calibration"))
        with self.assertRaises(TypeError):
            self.evaluator.score(rows, outcome_sequence=99, required_split="calibration")

    def test_post_outcome_prediction_is_rejected(self):
        rows = self.receipts(self.evaluator.public_cases(split="qualification"), start=100)
        with self.assertRaisesRegex(ValueError, "before scoring"):
            self.evaluator.score(rows, outcome_sequence=50)

    def test_scorer_revalidates_untrusted_receipt_fields(self):
        rows = self.receipts(self.evaluator.public_cases(split="qualification"))
        with self.assertRaisesRegex(ValueError, "budget_units"):
            self.evaluator.score((replace(rows[0], budget_units=-1), rows[1]), outcome_sequence=99)
        with self.assertRaisesRegex(ValueError, "commit_sequence"):
            self.evaluator.score((replace(rows[0], commit_sequence=True), rows[1]), outcome_sequence=99)

    def test_receipt_created_after_observed_outcome_can_claim_earlier_sequence(self):
        # Intentional exploit: model the outcome being observed first, then
        # create receipts afterward with a caller-chosen earlier sequence.
        observed_outcome = {"sequence": 3, "label": "A"}
        rows = self.receipts(self.evaluator.public_cases(split="qualification"), start=1)
        self.assertEqual(observed_outcome["sequence"], 2)
        self.assertEqual(self.evaluator.score(rows, outcome_sequence=observed_outcome["sequence"]).scored_cases, 2)

    def test_replay_guard_can_be_bypassed_by_rotating_untrusted_candidate_id(self):
        # Intentional exploit: candidate_id is caller-authored, not attested.
        cases = self.evaluator.public_cases(split="qualification")
        first = self.receipts(cases, candidate="candidate-identity-1", predict=lambda c: "A")
        second = self.receipts(cases, candidate="candidate-identity-2", predict=lambda c: "A")
        self.evaluator.score(first, outcome_sequence=99)
        self.assertEqual(self.evaluator.score(second, outcome_sequence=100).accuracy, 0.5)

    def test_tampered_prediction_is_rejected(self):
        rows = self.receipts(self.evaluator.public_cases(split="qualification"))
        forged = replace(rows[0], prediction="forged-answer")
        with self.assertRaisesRegex(ValueError, "commitment mismatch"):
            self.evaluator.score((forged, rows[1]), outcome_sequence=99)

    def test_prompt_substitution_is_rejected(self):
        rows = self.receipts(self.evaluator.public_cases(split="qualification"))
        forged = replace(rows[0], prompt_digest="0"*64)
        with self.assertRaisesRegex(ValueError, "commitment mismatch"):
            self.evaluator.score((forged, rows[1]), outcome_sequence=99)

    def test_incomplete_batch_and_same_instance_replay_are_rejected(self):
        rows = self.receipts(self.evaluator.public_cases(split="qualification"))
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            self.evaluator.score(rows[:1], outcome_sequence=99)
        self.evaluator.score(rows, outcome_sequence=99)
        with self.assertRaisesRegex(ValueError, "replay"):
            self.evaluator.score(rows, outcome_sequence=100)
        # Distinct baselines must be able to score the same held-out cases.
        baseline = self.receipts(self.evaluator.public_cases(split="qualification"), candidate="frozen-v1", predict=lambda c: "B")
        self.assertEqual(self.evaluator.score(baseline, outcome_sequence=100).scored_cases, 2)

    def test_compromised_truth_custodian_can_still_fabricate_a_win(self):
        cases = self.evaluator.public_cases(split="qualification")
        poisoned_truth = {key: "A" for key in self.truth}
        compromised = Evaluator(self.cases, poisoned_truth)
        rows = self.receipts(cases, candidate="always-A", predict=lambda c: "A")
        self.assertEqual(compromised.score(rows, outcome_sequence=99).accuracy, 1.0)
        # Intentional counterexample: in-process code cannot prove that its
        # answer-key custodian is independent or honest.

    def test_rule_reversal_defeats_stale_policy(self):
        cases = self.evaluator.public_cases(split="reversal")
        stale = self.receipts(cases, candidate="stale-v1", predict=lambda c: "A" if c.features[0] == "circle" else "B")
        reversal_evaluator = Evaluator(self.cases, self.truth, qualification_split="reversal")
        self.assertEqual(reversal_evaluator.score(stale, outcome_sequence=99).accuracy, 0.0)

    def test_event_journal_survives_distinct_process_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "events.sqlite")
            journal = EventJournal(path)
            journal.append({"kind": "prediction_committed", "candidate": "candidate-v1", "challenge": "heldout-0"})
            journal.append({"kind": "outcome_scored", "challenge": "heldout-0", "score": 1})
            before = journal.read_all()
            script = "from research.goal1_evaluator.acceptance import EventJournal; import json,sys; print(json.dumps(EventJournal(sys.argv[1]).read_all(),sort_keys=True))"
            root = str(Path(__file__).resolve().parents[2])
            env = dict(os.environ, PYTHONPATH=root + os.pathsep + os.environ.get("PYTHONPATH", ""))
            child = subprocess.run([sys.executable, "-c", script, path], text=True, capture_output=True, env=env, check=True)
            self.assertEqual(json.loads(child.stdout), before)
            self.assertEqual(json.loads(child.stdout)[-1]["event"]["kind"], "outcome_scored")

    def test_budget_is_measured_not_assumed(self):
        rows = self.receipts(self.evaluator.public_cases(split="qualification"), budget=7)
        self.assertEqual(self.evaluator.score(rows, outcome_sequence=99).budget_units, 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)
