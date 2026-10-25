"""Research wiring tests, not a claim of autonomous method discovery."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from vera_core.agi_method_research import (
    CalibrationCase,
    MethodSpec,
    consume_research_method,
    load_method_choice,
    save_method_choice,
    select_calibrated_method,
    selection_revision,
)
from vera_core import ClosedLoopFrontier, ClosedLoopTask
from vera_memory import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceBlocked,
    LearnedInfluenceReplay,
    LearnedInfluenceStale,
    ReviewDisposition,
)


class BoundedMethodConsumptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = MethodSpec("risk-check", (), "proceed")
        self.candidate = MethodSpec("risk-check", (("danger", "inspect"),), "proceed")
        self.calibration = (
            CalibrationCase("cal:A1", "Danger identified at press", "inspect"),
            CalibrationCase("cal:A2", "Clear line", "proceed"),
        )

    def test_selected_exact_artifact_is_consumed_after_split_review_and_restart(self):
        choice = select_calibrated_method(
            self.baseline, (self.candidate,), self.calibration
        )
        self.assertEqual(choice.selected, self.candidate)
        self.assertEqual(choice.baseline_correct, 1)
        self.assertEqual(choice.selected_correct, 2)
        self.assertEqual(choice.calibration_ids, ("cal:A1", "cal:A2"))
        self.assertNotEqual(self.candidate.revision.memory_revision_id,
                            self.baseline.revision.memory_revision_id)

        with TemporaryDirectory() as directory:
            db_file = Path(directory) / "learning.db"
            choice_file = Path(directory) / "selected-method.json"
            choice_digest = save_method_choice(choice_file, choice)
            gate = DurableLearnedInfluenceGate(db_file)
            reviewed_revision = selection_revision(choice_file)
            gate.review_qualified(
                association_id=reviewed_revision.association_id,
                memory_revision_id=reviewed_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="independent:fixture-qualification-B1",
                calibration_evidence_ids=choice.calibration_ids,
                qualification_evidence_ids=("qualification:B1",),
            )
            later = consume_research_method(
                gate, choice_file,
                prompt="Danger at unfamiliar downstream conveyor",
                cue_event_id="cue:C1", later_use_evidence_id="later:C1",
            )
            self.assertEqual(later.action, "inspect")
            self.assertEqual(later.method_digest, self.candidate.digest)
            self.assertEqual(later.selection_digest, choice_digest)
            self.assertEqual(later.matched_rule_index, 0)
            self.assertEqual(later.calibration_score_delta, 1)
            self.assertEqual(len(later.prompt_sha256), 64)
            self.assertEqual(later.revision, reviewed_revision)
            self.assertEqual(later.authorization_effect, "NONE")
            self.assertEqual(later.learned_receipt.use_evidence_id, "later:C1")
            self.assertTrue(later.learned_receipt.evidence_split_qualified)

            # Neither review nor method object is reused in-memory after reopen.
            del choice
            reopened = DurableLearnedInfluenceGate(db_file)
            recovered, recovered_digest = load_method_choice(choice_file)
            self.assertEqual(recovered_digest, choice_digest)
            self.assertEqual(recovered.selected.digest, self.candidate.digest)
            with self.assertRaises(LearnedInfluenceReplay):
                consume_research_method(
                    reopened, choice_file,
                    prompt="Danger at unfamiliar downstream conveyor",
                    cue_event_id="cue:C1", later_use_evidence_id="later:C1",
                )
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    reopened, choice_file,
                    prompt="Clear downstream conveyor",
                    cue_event_id="cue:C2", later_use_evidence_id="cal:A1",
                )
            baseline_file = Path(directory) / "baseline-method.json"
            save_method_choice(
                baseline_file,
                select_calibrated_method(self.baseline, (), self.calibration),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    reopened, baseline_file,
                    prompt="Clear downstream conveyor",
                    cue_event_id="cue:C3", later_use_evidence_id="later:C3",
                )
            second = consume_research_method(
                reopened, choice_file,
                prompt="Clear downstream conveyor",
                cue_event_id="cue:C4", later_use_evidence_id="later:C4",
            )
            self.assertEqual(second.action, "proceed")
            self.assertEqual(second.method_digest, later.method_digest)

    def test_no_change_when_training_ties_and_negative_transfer_is_visible(self):
        candidate = MethodSpec("risk-check", (("hazard", "inspect"),), "proceed")
        choice = select_calibrated_method(
            self.baseline, (candidate,), self.calibration
        )
        self.assertEqual(choice.selected, self.baseline)
        self.assertEqual(choice.selected_correct, choice.baseline_correct)

        positive = select_calibrated_method(
            self.baseline, (self.candidate,), self.calibration
        )
        # Labeled distinct-surface C cases are scored ONLY after the A choice.
        # Literal substring matching fails on negation and unseen synonyms.
        held_out = (
            ("No danger remains at the press", "proceed"),
            ("Hazard at valve", "inspect"),
        )
        frozen_baseline_correct = sum(
            self.baseline.choose(prompt) == oracle for prompt, oracle in held_out
        )
        selected_correct = sum(
            positive.selected.choose(prompt) == oracle for prompt, oracle in held_out
        )
        self.assertEqual(frozen_baseline_correct, 1)
        self.assertEqual(selected_correct, 0)
        self.assertLess(selected_correct, frozen_baseline_correct)
        # This is a deliberately negative synthetic control, not proof that
        # either method generalized or a model made its own method revision.

    def test_exact_method_bytes_and_validation(self):
        self.assertEqual(self.candidate.digest, MethodSpec(
            "risk-check", (("danger", "inspect"),), "proceed"
        ).digest)
        self.assertNotEqual(self.candidate.digest, MethodSpec(
            "risk-check", (("danger", "halt"),), "proceed"
        ).digest)
        with self.assertRaises(FrozenInstanceError):
            self.candidate.default_action = "inspect"
        invalid = (
            lambda: MethodSpec("", (), "proceed"),
            lambda: MethodSpec("risk-check", (("", "inspect"),), "proceed"),
            lambda: MethodSpec(
                "risk-check", (("danger", "inspect"), ("danger", "halt")), "proceed"
            ),
            lambda: MethodSpec("risk-check", (("danger", ""),), "proceed"),
        )
        for create in invalid:
            with self.subTest(create=create), self.assertRaises(ValueError):
                create()

    def test_calibration_cannot_reuse_ids_or_solely_self_grade(self):
        with self.assertRaises(ValueError):
            select_calibrated_method(self.baseline, (self.candidate,), (
                CalibrationCase("cal:A", "Danger", "inspect"),
                CalibrationCase("cal:A", "Clear", "proceed"),
            ))
        with self.assertRaises(ValueError):
            select_calibrated_method(self.baseline, (self.candidate,), ())

    def test_generic_reason_callback_can_ignore_revision_but_bound_method_cannot(self):
        """Adversarial negative: prior callback review != downstream use."""
        with TemporaryDirectory() as directory:
            frontier = ClosedLoopFrontier(directory)
            choice_file = Path(directory) / "selection.json"
            save_method_choice(choice_file, select_calibrated_method(
                self.baseline, (self.candidate,), self.calibration
            ))
            frontier.review_learning_qualified(
                self.candidate.revision,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review:fixture-method-A",
                calibration_evidence_ids=("cal:A1", "cal:A2"),
                qualification_evidence_ids=("qualification:B1",),
            )
            bound_revision = selection_revision(choice_file)
            frontier.learned_influence.review_qualified(
                association_id=bound_revision.association_id,
                memory_revision_id=bound_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review:fixture-bound-method",
                calibration_evidence_ids=("cal:A1", "cal:A2"),
                qualification_evidence_ids=("qualification:B1",),
            )
            task = ClosedLoopTask(
                task_id="ignored-method-negative-control",
                prompt="Danger at a press",
                semantic_object={
                    "schema_version": "0.1",
                    "object_type": "node",
                    "id": "NODE-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "primary_label": "ignored research method",
                    "aliases": [],
                    "node_kind": "concept",
                    "notes": None,
                },
            )
            old_path = frontier.run_with_learning(
                task,
                revision=self.candidate.revision,
                cue_event_id="cue:C-negative",
                use_evidence_id="later:C-negative",
                reason=lambda _prompt, _semantic, _revision: (
                    "proceed", ("synthetic:ignored-method",)
                ),
                act=lambda _action: {"success": True, "synthetic": True},
            )
            self.assertEqual(old_path.reasoned_action, "proceed")
            self.assertEqual(old_path.learned_influence.memory_revision_id,
                             self.candidate.revision.memory_revision_id)
            # Existing callback acceptance is not evidence that its revision
            # influenced the decision. The new constrained interpreter binds it.
            bound = consume_research_method(
                frontier.learned_influence,
                choice_file,
                prompt=task.prompt,
                cue_event_id="cue:C-bound",
                later_use_evidence_id="later:C-bound",
            )
            self.assertEqual(bound.action, "inspect")
            self.assertNotEqual(bound.action, old_path.reasoned_action)
            self.assertEqual(bound.method_digest, self.candidate.digest)

    def test_reviewer_quarantine_then_explicit_baseline_rollback(self):
        with TemporaryDirectory() as directory:
            gate = DurableLearnedInfluenceGate(Path(directory) / "gate.db")
            candidate_file = Path(directory) / "candidate.json"
            baseline_file = Path(directory) / "baseline.json"
            save_method_choice(candidate_file, select_calibrated_method(
                self.baseline, (self.candidate,), self.calibration
            ))
            save_method_choice(baseline_file, select_calibrated_method(
                self.baseline, (), self.calibration
            ))
            candidate_revision = selection_revision(candidate_file)
            baseline_revision = selection_revision(baseline_file)
            gate.review_qualified(
                association_id=candidate_revision.association_id,
                memory_revision_id=candidate_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review:fixture-admit",
                calibration_evidence_ids=("cal:A1", "cal:A2"),
                qualification_evidence_ids=("qualification:B1",),
            )
            self.assertEqual(consume_research_method(
                gate, candidate_file, prompt="Danger", cue_event_id="cue:C1",
                later_use_evidence_id="later:C1",
            ).action, "inspect")

            gate.review(
                association_id=candidate_revision.association_id,
                memory_revision_id=candidate_revision.memory_revision_id,
                disposition=ReviewDisposition.QUARANTINED,
                evidence_ref="review:negative-transfer",
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    gate, candidate_file, prompt="Danger", cue_event_id="cue:C2",
                    later_use_evidence_id="later:C2",
                )
            gate.review_qualified(
                association_id=baseline_revision.association_id,
                memory_revision_id=baseline_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review:explicit-baseline-rollback",
                calibration_evidence_ids=("cal:A1", "cal:A2"),
                qualification_evidence_ids=("qualification:B3",),
            )
            reverted = consume_research_method(
                gate, baseline_file, prompt="Danger", cue_event_id="cue:C3",
                later_use_evidence_id="later:C3",
            )
            self.assertEqual(reverted.action, "proceed")
            self.assertNotEqual(reverted.method_digest, self.candidate.digest)
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    gate, candidate_file, prompt="Danger", cue_event_id="cue:C4",
                    later_use_evidence_id="later:C4",
                )

    def test_selection_bytes_cannot_be_substituted_without_detection(self):
        choice = select_calibrated_method(
            self.baseline, (self.candidate,), self.calibration
        )
        with TemporaryDirectory() as directory:
            choice_file = Path(directory) / "selection.json"
            checksum = save_method_choice(choice_file, choice)
            self.assertEqual(load_method_choice(choice_file)[1], checksum)
            with self.assertRaises(FileExistsError):
                save_method_choice(choice_file, choice)
            with self.assertRaises(TypeError):
                consume_research_method(
                    DurableLearnedInfluenceGate(Path(directory) / "gate.db"),
                    self.baseline, prompt="Danger", cue_event_id="cue:C1",
                    later_use_evidence_id="later:C1",
                )
            # Explicit persisted selected artifact is the only method input.
            raw = choice_file.read_bytes()
            choice_file.write_bytes(raw.replace(b'inspect', b'proceed'))
            with self.assertRaises(ValueError):
                load_method_choice(choice_file)

    def test_recomputed_public_checksum_cannot_forge_no_change_score(self):
        no_change = select_calibrated_method(
            self.baseline, (), self.calibration
        )
        with TemporaryDirectory() as directory:
            choice_file = Path(directory) / "no-change.json"
            save_method_choice(choice_file, no_change)
            envelope = json.loads(choice_file.read_text())
            payload = envelope["payload"]
            payload["baseline_correct"] = 0
            payload["selected_correct"] = 1
            canonical = lambda value: json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("ascii")
            envelope["sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
            choice_file.write_bytes(canonical(envelope))
            # Checksum matches altered bytes; semantic recomputation must fail.
            with self.assertRaises(ValueError):
                load_method_choice(choice_file)
            choice_file.write_bytes(b'x' * 16385)
            with self.assertRaises(ValueError):
                load_method_choice(choice_file)

    def test_unqualified_review_cannot_return_method_execution_trace(self):
        with TemporaryDirectory() as directory:
            choice_file = Path(directory) / "selection.json"
            save_method_choice(choice_file, select_calibrated_method(
                self.baseline, (self.candidate,), self.calibration
            ))
            gate = DurableLearnedInfluenceGate(Path(directory) / "gate.db")
            reviewed_revision = selection_revision(choice_file)
            gate.review(
                association_id=reviewed_revision.association_id,
                memory_revision_id=reviewed_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="ordinary-review-not-qualification",
            )
            with self.assertRaisesRegex(LearnedInfluenceBlocked, "calibration"):
                consume_research_method(
                    gate, choice_file, prompt="Danger", cue_event_id="cue:C1",
                    later_use_evidence_id="later:C1",
                )
            # Gate rejects before durable consumption; a retry is also held.
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    gate, choice_file, prompt="Danger", cue_event_id="cue:C1",
                    later_use_evidence_id="later:C1",
                )

    def test_gate_qualification_a_must_match_selected_method_calibration_a(self):
        with TemporaryDirectory() as directory:
            choice_file = Path(directory) / "selected.json"
            choice = select_calibrated_method(
                self.baseline, (self.candidate,), self.calibration
            )
            save_method_choice(choice_file, choice)
            gate = DurableLearnedInfluenceGate(Path(directory) / "gate.db")
            reviewed_revision = selection_revision(choice_file)
            gate.review_qualified(
                association_id=reviewed_revision.association_id,
                memory_revision_id=reviewed_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="qualification:unrelated-A",
                calibration_evidence_ids=("unrelated:A999",),
                qualification_evidence_ids=("qualification:B1",),
            )
            with self.assertRaisesRegex(LearnedInfluenceBlocked, "calibration"):
                consume_research_method(
                    gate, choice_file, prompt="Danger", cue_event_id="cue:C1",
                    later_use_evidence_id="later:C1",
                )
            # Mismatched admission must not consume C, even before re-review.
            gate.review_qualified(
                association_id=reviewed_revision.association_id,
                memory_revision_id=reviewed_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="qualification:matching-A",
                calibration_evidence_ids=choice.calibration_ids,
                qualification_evidence_ids=("qualification:B1",),
            )
            admitted = consume_research_method(
                gate, choice_file, prompt="Danger", cue_event_id="cue:C1",
                later_use_evidence_id="later:C1",
            )
            self.assertEqual(admitted.action, "inspect")

    def test_equal_method_revision_different_selection_a_cannot_reuse_review(self):
        with TemporaryDirectory() as directory:
            a_file = Path(directory) / "choice-A.json"
            x_file = Path(directory) / "choice-X.json"
            a = select_calibrated_method(self.baseline, (self.candidate,), self.calibration)
            x = select_calibrated_method(self.baseline, (self.candidate,), (
                CalibrationCase("other:X1", "Danger identified at press", "inspect"),
                CalibrationCase("other:X2", "Clear line", "proceed"),
            ))
            save_method_choice(a_file, a)
            save_method_choice(x_file, x)
            self.assertEqual(a.selected.revision, x.selected.revision)
            self.assertNotEqual(selection_revision(a_file), selection_revision(x_file))
            gate = DurableLearnedInfluenceGate(Path(directory) / "gate.db")
            a_revision = selection_revision(a_file)
            gate.review_qualified(
                association_id=a_revision.association_id,
                memory_revision_id=a_revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review:only-A",
                calibration_evidence_ids=a.calibration_ids,
                qualification_evidence_ids=("qualification:B1",),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                consume_research_method(
                    gate, x_file, prompt="Danger", cue_event_id="cue:C-X",
                    later_use_evidence_id="later:C-X",
                )
            self.assertEqual(consume_research_method(
                gate, a_file, prompt="Danger", cue_event_id="cue:C-A",
                later_use_evidence_id="later:C-A",
            ).action, "inspect")

    def test_bounded_research_input_sizes(self):
        with self.assertRaises(ValueError):
            MethodSpec("risk-check", tuple((f"cue-{i}", "inspect")
                                           for i in range(17)), "proceed")
        with self.assertRaises(ValueError):
            MethodSpec("risk-check", (), "x" * 4097)
        with self.assertRaises(ValueError):
            self.baseline.choose("x" * 4097)
        with self.assertRaises(ValueError):
            select_calibrated_method(self.baseline, tuple(
                MethodSpec("risk-check", ((f"cue-{i}", "inspect"),), "proceed")
                for i in range(9)
            ), self.calibration)
        with self.assertRaises(ValueError):
            select_calibrated_method(self.baseline, (self.candidate,), tuple(
                CalibrationCase(f"cal:{i}", "Danger", "inspect")
                for i in range(65)
            ))

    @unittest.skipUnless(os.name == "posix", "POSIX private-mode contract")
    def test_selection_artifact_private_mode_directory_and_symlink_guards(self):
        choice = select_calibrated_method(
            self.baseline, (self.candidate,), self.calibration
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            private_file = root / "choice.json"
            save_method_choice(private_file, choice)
            self.assertEqual(stat.S_IMODE(private_file.stat().st_mode), 0o600)
            self.assertEqual(load_method_choice(private_file)[0].selected,
                             self.candidate)

            symlink_file = root / "link.json"
            symlink_file.symlink_to(private_file)
            with self.assertRaises(OSError):
                load_method_choice(symlink_file)
            with self.assertRaises(FileExistsError):
                save_method_choice(symlink_file, choice)

            private_file.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private owner-only"):
                load_method_choice(private_file)

            unsafe_dir = root / "shared"
            unsafe_dir.mkdir(mode=0o755)
            with self.assertRaisesRegex(ValueError, "private 0700 directory"):
                save_method_choice(unsafe_dir / "new.json", choice)


if __name__ == "__main__":
    unittest.main()
