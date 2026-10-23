"""Negative controls for a guarded context revision; not a learning benchmark."""
import tempfile
from pathlib import Path
import unittest

from research.goal1_learning_trial.revision_context import (
    VersionedLearningRule, prepare_trial_prompt,
)
from vera_core.corrective_learning import CorrectiveLearningLedger, CorrectiveStage
from vera_memory.learned_influence import (
    DurableLearnedInfluenceGate, LearnedInfluenceBlocked,
    LearnedInfluenceReplay, LearnedInfluenceStale, ReviewDisposition,
)

RULE = VersionedLearningRule(
    association_id="synthetic-input-parity",
    correction_id="synthetic-correction-01",
    failure_signature_id="synthetic-parity-mismatch",
    rule_text="For an even input predict A; for an odd input predict B.",
)

def complete_ledger(path):
    ledger = CorrectiveLearningLedger(path)
    ledger.start(
        correction_id=RULE.correction_id,
        failure_signature_id=RULE.failure_signature_id,
        summary="Synthetic failed initial parity predictions",
        evidence_refs=("synthetic:calibration-01",),
    )
    for stage in (
        CorrectiveStage.UNDERSTAND, CorrectiveStage.CALIBRATE,
        CorrectiveStage.KNOW, CorrectiveStage.UNLEARN, CorrectiveStage.PREVENT,
    ):
        kw = {}
        if stage is CorrectiveStage.PREVENT:
            kw = {"guardrail_refs": ("synthetic:guard-01",),
                  "verification_refs": ("synthetic:verification-01",)}
        ledger.advance(
            RULE.correction_id, stage=stage,
            summary="Synthetic stage " + stage.value,
            evidence_refs=("synthetic:stage:" + stage.value,), **kw,
        )
    return ledger

def admitted(gate, *, rule=RULE, disposition=ReviewDisposition.ADMITTED):
    gate.review_qualified(
        association_id=rule.association_id, memory_revision_id=rule.revision_id,
        disposition=disposition, evidence_ref="synthetic:controller-review",
        calibration_evidence_ids=("synthetic:cal-A",),
        qualification_evidence_ids=("synthetic:qual-B",),
    )

def trial(*, cue="later:cue-01", use="synthetic:later-C", **kwargs):
    return prepare_trial_prompt(
        condition="REVISED", task_prompt="Input is 7. Choose A or B.",
        case_id="heldout:case-01", cue_event_id=cue,
        later_use_evidence_id=use, **kwargs,
    )

class RevisionContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name)
        self.path=base/"gate.sqlite"
        self.ledgerpath=base/"correction.sqlite"
        self.gate=DurableLearnedInfluenceGate(self.path)

    def test_frozen_control_has_no_rule_or_review_effect(self):
        result = prepare_trial_prompt(
            condition="FROZEN", task_prompt="Input is 7. Choose A or B.",
            case_id="heldout:case-01", cue_event_id="later:cue-01",
        )
        self.assertEqual(result.condition, "FROZEN")
        self.assertIsNone(result.revision_id)
        self.assertNotIn(RULE.rule_text, result.prompt)
        self.assertEqual(result.authorization_effect, "NONE")
        self.assertFalse(result.learning_improvement_verified)

    def test_revised_blocked_before_completed_correction(self):
        ledger = CorrectiveLearningLedger(self.ledgerpath)
        admitted(self.gate)
        with self.assertRaises(LearnedInfluenceBlocked):
            trial(revision=RULE, correction_ledger=ledger, influence_gate=self.gate)
        ledger.start(
            correction_id=RULE.correction_id, failure_signature_id=RULE.failure_signature_id,
            summary="Synthetic failure", evidence_refs=("synthetic:cal-A",),
        )
        with self.assertRaisesRegex(LearnedInfluenceBlocked, "finish PREVENT"):
            trial(revision=RULE, correction_ledger=ledger, influence_gate=self.gate)

    def test_qualified_rule_changes_exact_prompt_and_is_one_use(self):
        ledger=complete_ledger(self.ledgerpath)
        admitted(self.gate)
        result=trial(revision=RULE, correction_ledger=ledger, influence_gate=self.gate)
        self.assertEqual(result.revision_id, RULE.revision_id)
        self.assertIn(RULE.rule_text, result.prompt)
        self.assertEqual(len(result.prompt_sha256), 64)
        self.assertEqual(result.review_evidence_ref, "synthetic:controller-review")
        self.assertFalse(result.independent_truth_verified)
        self.assertFalse(result.model_consumption_verified)
        with self.assertRaises(LearnedInfluenceReplay):
            trial(revision=RULE, correction_ledger=ledger, influence_gate=self.gate)

    def test_cold_reopen_preserves_revision_and_cue_replay_barrier(self):
        ledger=complete_ledger(self.ledgerpath)
        admitted(self.gate)
        original=trial(revision=RULE, correction_ledger=ledger, influence_gate=self.gate)
        reopened_gate=DurableLearnedInfluenceGate(self.path)
        reopened_ledger=CorrectiveLearningLedger(self.ledgerpath)
        with self.assertRaises(LearnedInfluenceReplay):
            trial(revision=RULE, correction_ledger=reopened_ledger,
                  influence_gate=reopened_gate)
        another=trial(revision=RULE, correction_ledger=reopened_ledger,
                      influence_gate=reopened_gate, cue="later:cue-02", use="synthetic:later-D")
        self.assertEqual(original.revision_id, another.revision_id)
        self.assertEqual(original.prompt_sha256, another.prompt_sha256)
        with self.assertRaises(LearnedInfluenceReplay):
            trial(revision=RULE, correction_ledger=reopened_ledger,
                  influence_gate=reopened_gate, cue="later:cue-03", use="synthetic:later-D")

    def test_modified_and_quarantined_rule_denied(self):
        ledger=complete_ledger(self.ledgerpath)
        admitted(self.gate)
        changed=VersionedLearningRule(
            RULE.association_id,RULE.correction_id,RULE.failure_signature_id,
            "For an even input predict B; for an odd input predict A.",
        )
        self.assertNotEqual(RULE.revision_id,changed.revision_id)
        with self.assertRaises(LearnedInfluenceStale):
            trial(revision=changed, correction_ledger=ledger, influence_gate=self.gate)
        admitted(self.gate, disposition=ReviewDisposition.QUARANTINED)
        with self.assertRaises(LearnedInfluenceBlocked):
            trial(revision=RULE, correction_ledger=ledger, influence_gate=self.gate)

    def test_unqualified_review_cannot_use_later_evidence(self):
        ledger=complete_ledger(self.ledgerpath)
        self.gate.review(
            association_id=RULE.association_id,memory_revision_id=RULE.revision_id,
            disposition=ReviewDisposition.ADMITTED,evidence_ref="self-review-only",
        )
        with self.assertRaises(LearnedInfluenceBlocked):
            trial(revision=RULE,correction_ledger=ledger,influence_gate=self.gate)

    def test_calibration_truth_id_cannot_be_reused_as_later_case(self):
        ledger=complete_ledger(self.ledgerpath)
        admitted(self.gate)
        with self.assertRaises(LearnedInfluenceBlocked):
            trial(revision=RULE,correction_ledger=ledger,
                  influence_gate=self.gate,use="synthetic:cal-A")
        with self.assertRaises(LearnedInfluenceBlocked):
            trial(revision=RULE,correction_ledger=ledger,
                  influence_gate=self.gate,use="synthetic:qual-B")

    def test_no_frozen_influence_and_reject_bad_rule_content(self):
        with self.assertRaises(ValueError):
            prepare_trial_prompt(
                condition="FROZEN", task_prompt="Input is 7", case_id="case",
                cue_event_id="cue", revision=RULE,
            )
        with self.assertRaises(ValueError):
            VersionedLearningRule(RULE.association_id,RULE.correction_id,
                                 RULE.failure_signature_id,"hello\nexec script")
        with self.assertRaises(ValueError):
            prepare_trial_prompt(condition="FROZEN", task_prompt="x"*1500,
                                 case_id="case",cue_event_id="cue")

if __name__ == "__main__":
    unittest.main()
