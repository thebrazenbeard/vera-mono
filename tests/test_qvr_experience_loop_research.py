"""Bounded Goal 1 selected-QVR experience-loop research: no model/network in tests."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "research"))
from qvr_experience_loop import (
    TRAIN, HOLDOUT, classify, choose_query, choose_rule,
    verify_feedback, evaluator_subprocess, eval_request, predict_all,
)


class ExperienceLoopContractTests(unittest.TestCase):
    def test_exact_initial_decision_parsing(self):
        self.assertEqual(choose_query("A train-b"), ("A", "train-b"))
        for bad in ("A train-a", "B train-d because", "B train-a", "a train-b", "A hidden-e", "<think>B train-c</think>", "A train-b\nmore"):
            with self.subTest(bad=bad):
                self.assertIsNone(choose_query(bad))

    def test_discriminating_queries_are_required(self):
        self.assertEqual(choose_query("B train-c"), ("B", "train-c"))
        self.assertEqual(choose_query("A train-d"), ("A", "train-d"))

    def test_wrong_model_revision_never_overrides_evaluator(self):
        item = verify_feedback("train-d", "0", model_revision="A")
        self.assertEqual(item["evidence_rule"], "B")
        self.assertTrue(item["model_disagreed"])
        self.assertEqual(item["observed_label"], "0")

    def test_in_family_feedback_of_each_label(self):
        a = verify_feedback("train-d", "1", model_revision="A")
        b = verify_feedback("train-d", "0", model_revision="B")
        self.assertEqual(a["evidence_rule"], "A")
        self.assertEqual(b["evidence_rule"], "B")
        self.assertFalse(a["model_disagreed"])
        self.assertFalse(b["model_disagreed"])

    def test_invalid_labels_and_ambiguous_probe_fail_closed(self):
        for case, label in (("train-a", "0"), ("train-a", "1"), ("train-d", "2"), ("hidden-e", "1")):
            with self.subTest(case=case,label=label):
                with self.assertRaises(ValueError):
                    verify_feedback(case, label, model_revision="B")

    def test_features_rejected_when_malformed(self):
        with self.assertRaises(ValueError):
            classify("B", "01")
        with self.assertRaises(ValueError):
            classify("B", "012")
        with self.assertRaises(ValueError):
            classify("C", "011")

    def test_unseen_predictions_are_exact_full_set(self):
        x = predict_all("B", HOLDOUT)
        self.assertEqual(x, {"hidden-e": "1", "hidden-f": "0", "hidden-g": "0", "hidden-h": "1"})
        self.assertEqual(predict_all("A", HOLDOUT), {"hidden-e": "0", "hidden-f": "1", "hidden-g": "1", "hidden-h": "1"})

    def test_model_choose_rule_strict(self):
        self.assertEqual(choose_rule("B"), "B")
        for text in ("B because", "{\"rule\":\"B\"}", "a", " A \n B "):
            self.assertIsNone(choose_rule(text))

    def test_evaluator_is_finite_external_process_with_hidden_truth(self):
        with evaluator_subprocess() as proc:
            hello = eval_request(proc, {"action": "start"})
            self.assertEqual(hello["status"], "INQUIRY")
            self.assertEqual(hello["train"], TRAIN)
            self.assertEqual(hello["probe_budget"], 1)
            self.assertNotIn("rule", hello)
            self.assertNotIn("labels", str(hello))
            self.assertEqual(len(hello["precommit"]), 64)
            outcome = eval_request(proc, {"action": "probe", "id": "train-d"})
            self.assertEqual(outcome["id"], "train-d")
            self.assertIn(outcome["label"], ("0","1"))
            self.assertEqual(eval_request(proc, {"action": "probe", "id": "train-c"})["error"], "PROBE_DENIED")
            self.assertEqual(eval_request(proc, {"action": "probe", "id": "hidden-e"})["error"], "PROBE_DENIED")
            future = eval_request(proc, {"action": "holdout"})
            self.assertEqual(future["inputs"], HOLDOUT)
            self.assertNotIn("truth", future)
            selected = verify_feedback("train-d",outcome["label"],model_revision="C")["evidence_rule"]
            predictions = predict_all(selected, future["inputs"])
            scored = eval_request(proc, {"action": "score", "predictions": predictions})
            self.assertEqual(scored["correct"], 4)
            self.assertEqual(scored["attempted"], 4)
            self.assertEqual(eval_request(proc, {"action": "score", "predictions": predictions})["error"], "TRIAL_CLOSED")

    def test_no_early_ground_truth_from_evaluator(self):
        with evaluator_subprocess() as proc:
            self.assertEqual(eval_request(proc, {"action": "score", "predictions": {}})["error"], "INVALID_PHASE")
            self.assertEqual(eval_request(proc, {"action": "holdout"})["error"], "INVALID_PHASE")
            eval_request(proc, {"action": "start"})
            self.assertEqual(eval_request(proc, {"action": "holdout"})["error"], "INVALID_PHASE")

    def test_repeated_start_and_invalid_request_rejected(self):
        with evaluator_subprocess() as proc:
            eval_request(proc, {"action": "start"})
            self.assertEqual(eval_request(proc, {"action": "start"})["error"], "INVALID_REQUEST")
            self.assertEqual(eval_request(proc, {"action": "probe", "id": "train-b", "debug": True})["error"], "INVALID_REQUEST")

    def test_absent_feedback_cannot_select_provisional_rule(self):
        with self.assertRaises(ValueError):
            verify_feedback("train-d", "", model_revision="B")


if __name__=="__main__":
    unittest.main()
