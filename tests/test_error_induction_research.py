"""Synthetic error-driven rule induction; not a qualification of real learning."""

from __future__ import annotations

from contextlib import closing
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vera_core.agi_method_research import (
    CalibrationCase,
    MethodSpec,
    consume_research_method,
    induce_error_rule_candidate,
    save_method_choice,
    select_calibrated_method,
    selection_revision,
)
from vera_memory import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceBlocked,
    ReviewDisposition,
    SignedLaterOutcome,
)


class ErrorInductionResearchTests(unittest.TestCase):
    def setUp(self):
        self.baseline = MethodSpec("press-safety", (), "proceed")
        self.training = (
            CalibrationCase("A:1", "Danger at the stamping press", "inspect"),
            CalibrationCase("A:2", "Conveyor clear", "proceed"),
        )

    def test_induced_revision_is_selected_and_used_after_cold_restart(self):
        # Only a baseline + labeled errors are supplied, not a candidate rule.
        induced = induce_error_rule_candidate(self.baseline, self.training)
        self.assertIsNotNone(induced)
        self.assertEqual(induced.authorization_effect, "NONE")
        self.assertEqual(induced.evidence_status, "TRAINING_LABELS_NOT_ATTESTED")
        self.assertEqual(induced.source_calibration_ids, ("A:1", "A:2"))
        self.assertNotEqual(induced.method.digest, self.baseline.digest)
        self.assertEqual(induced.method.choose("Danger at a new press"), "inspect")
        choice = select_calibrated_method(self.baseline, (induced.method,), self.training)
        self.assertEqual(choice.baseline_correct, 1)
        self.assertEqual(choice.selected_correct, 2)
        self.assertEqual(choice.selected, induced.method)

        with TemporaryDirectory() as root:
            selection = Path(root) / "research-method.json"
            save_method_choice(selection, choice)
            database = Path(root) / "gate.db"
            DurableLearnedInfluenceGate(database).review_qualified(
                association_id=selection_revision(selection).association_id,
                memory_revision_id=selection_revision(selection).memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:operator-review-B",
                calibration_evidence_ids=choice.calibration_ids,
                qualification_evidence_ids=("B:1",),
            )
            # Deliberately construct a new gate to exercise durable recovery.
            receipt = consume_research_method(
                DurableLearnedInfluenceGate(database), selection,
                prompt="Danger at a new press", cue_event_id="C:1",
                later_use_evidence_id="C:result-1",
            )
            self.assertEqual(receipt.action, "inspect")
            self.assertEqual(receipt.method_digest, induced.method.digest)
            self.assertTrue(receipt.learned_receipt.evidence_split_qualified)
            self.assertEqual(receipt.authorization_effect, "NONE")

    def test_error_induction_to_signed_negative_outcome_blocks_future_use(self):
        """Inert A -> B -> C -> signed negative D -> cold-restart quarantine."""
        induced = induce_error_rule_candidate(self.baseline, self.training)
        self.assertIsNotNone(induced)
        choice = select_calibrated_method(
            self.baseline, (induced.method,), self.training
        )
        with TemporaryDirectory() as root:
            selection = Path(root) / "selected.json"
            save_method_choice(selection, choice)
            revision = selection_revision(selection)
            database = Path(root) / "gate.db"
            # Disposable test-only external trust provisioning, distinct from
            # runtime learning and NOT qualified evaluator custody.
            private_key = Ed25519PrivateKey.generate()
            public_key = private_key.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw
            )
            DurableLearnedInfluenceGate(database)
            with closing(sqlite3.connect(database)) as db, db:
                db.execute(
                    "INSERT INTO learned_outcome_trust VALUES (1, ?, ?)",
                    ("fixture:evaluator", hashlib.sha256(public_key).hexdigest()),
                )
            gate = DurableLearnedInfluenceGate(
                database, evaluator_id="fixture:evaluator",
                evaluator_public_key=public_key,
            )
            gate.review_qualified(
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:separate-B-review",
                calibration_evidence_ids=choice.calibration_ids,
                qualification_evidence_ids=("fixture:B1",),
            )
            first_use = consume_research_method(
                gate, selection, prompt="Danger was a false alarm",
                cue_event_id="fixture:C1", later_use_evidence_id="fixture:C-use1",
            )
            self.assertEqual(first_use.action, "inspect")
            self.assertEqual(first_use.authorization_effect, "NONE")
            unsigned = SignedLaterOutcome(
                evaluator_id="fixture:evaluator",
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                cue_event_id="fixture:C1", use_evidence_id="fixture:C-use1",
                outcome_evidence_id="fixture:C-outcome1",
                baseline_loss=0.0, candidate_loss=1.0,
                signature_hex="0" * 128,
            )
            signed = replace(
                unsigned, signature_hex=private_key.sign(unsigned.signing_bytes()).hex()
            )
            outcome = gate.record_later_outcome(signed)
            self.assertTrue(outcome.negative_transfer)
            self.assertEqual(outcome.authorization_effect, "NONE")
            # A new process without the evaluator key must still respect the
            # durable quarantine; merely re-reviewing cannot unlock it.
            restarted = DurableLearnedInfluenceGate(database)
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    restarted, selection, prompt="Danger at another press",
                    cue_event_id="fixture:C2", later_use_evidence_id="fixture:C-use2",
                )

    def test_conflicting_training_labels_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicting"):
            induce_error_rule_candidate(self.baseline, (
                CalibrationCase("A:1", "Danger at press", "inspect"),
                CalibrationCase("A:2", "Danger at press", "proceed"),
            ))

    def test_no_candidate_when_no_corrective_improvement(self):
        induced = induce_error_rule_candidate(self.baseline, (
            CalibrationCase("A:1", "Conveyor clear", "proceed"),
        ))
        self.assertIsNone(induced)

    def test_negative_control_does_not_degrade_previously_correct_cases(self):
        # A single cue cannot safely override two contradictory nearby inputs.
        training = (
            CalibrationCase("A:1", "Danger at press", "inspect"),
            CalibrationCase("A:2", "Danger is only a rumor", "proceed"),
            CalibrationCase("A:3", "Press clear", "proceed"),
        )
        induced = induce_error_rule_candidate(self.baseline, training)
        if induced is not None:
            self.assertEqual(induced.method.choose("Danger is only a rumor"), "proceed")
            self.assertEqual(induced.method.choose("Press clear"), "proceed")

    def test_induction_overfits_a_but_has_negative_transfer_on_new_cases(self):
        induced = induce_error_rule_candidate(self.baseline, self.training)
        self.assertIsNotNone(induced)
        self.assertEqual((induced.baseline_correct, induced.induced_correct), (1, 2))
        shifted = (
            CalibrationCase("B:1", "Danger was a false alarm", "proceed"),
            CalibrationCase("B:2", "No hazard at the press", "proceed"),
            CalibrationCase("B:3", "Conveyor still clear", "proceed"),
        )
        baseline_score = sum(self.baseline.choose(case.prompt) == case.expected_action
                             for case in shifted)
        induced_score = sum(induced.method.choose(case.prompt) == case.expected_action
                            for case in shifted)
        self.assertEqual(baseline_score, 3)
        self.assertEqual(induced_score, 2)
        self.assertEqual(induced.authorization_effect, "NONE")

    def test_induction_does_not_auto_admit_without_separate_b_review(self):
        induced = induce_error_rule_candidate(self.baseline, self.training)
        self.assertIsNotNone(induced)
        choice = select_calibrated_method(self.baseline, (induced.method,), self.training)
        with TemporaryDirectory() as root:
            selection = Path(root) / "research-method.json"
            save_method_choice(selection, choice)
            gate = DurableLearnedInfluenceGate(Path(root) / "gate.db")
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    gate, selection,
                    prompt="Danger at press", cue_event_id="C:not-admitted",
                    later_use_evidence_id="C:missing-B",
                )


if __name__ == "__main__":
    unittest.main()
