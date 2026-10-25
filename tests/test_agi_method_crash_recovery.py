"""Crash boundary: a consumed cue is not evidence of executed method output."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from vera_core.agi_method_research import (
    CalibrationCase, MethodSpec, consume_research_method, save_method_choice,
    select_calibrated_method, selection_revision,
)
from vera_memory import (
    DurableLearnedInfluenceGate, LearnedInfluenceBlocked,
    LearnedInfluenceReplay, LearnedRevision, ResearchMethodAttemptClaim,
    ReviewDisposition,
)


class MethodCommitCrashTests(unittest.TestCase):
    def test_atomic_insert_failure_rolls_back_c_and_legacy_use_is_not_invented(self):
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "gate.db"
            gate = DurableLearnedInfluenceGate(db_path)
            revision = LearnedRevision("research-selection:" + "a" * 64,
                                       "sha256:" + "b" * 64)
            gate.review_qualified(
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="B:review",
                calibration_evidence_ids=("A:1",),
                qualification_evidence_ids=("B:1",),
            )
            claim = ResearchMethodAttemptClaim(
                selection_digest="a" * 64, method_digest="b" * 64,
                prompt_sha256="c" * 64, action_sha256="d" * 64,
            )
            spoof = ResearchMethodAttemptClaim(
                selection_digest="f" * 64, method_digest="b" * 64,
                prompt_sha256="c" * 64, action_sha256="d" * 64,
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.consume(
                    revision, cue_event_id="C:spoof", use_evidence_id="C:spoof-use",
                    expected_calibration_evidence_ids=("A:1",),
                    research_method_attempt=spoof,
                )
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute("""CREATE TRIGGER fault_before_research_insert
                    BEFORE INSERT ON learned_research_method_attempts
                    BEGIN SELECT RAISE(ABORT, 'injected crash before commit'); END""")
            with self.assertRaises(sqlite3.DatabaseError):
                gate.consume(
                    revision, cue_event_id="C:rollback", use_evidence_id="C:rollback-use",
                    expected_calibration_evidence_ids=("A:1",),
                    research_method_attempt=claim,
                )
            with closing(sqlite3.connect(db_path)) as db, db:
                for table in (
                    "learned_consumptions", "learned_use_evidence",
                    "learned_use_cue_bindings", "learned_research_method_attempts",
                ):
                    self.assertEqual(db.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0], 0)
                db.execute("DROP TRIGGER fault_before_research_insert")

            reopened = DurableLearnedInfluenceGate(db_path)
            consumed = reopened.consume(
                revision, cue_event_id="C:rollback", use_evidence_id="C:rollback-use",
                expected_calibration_evidence_ids=("A:1",),
                research_method_attempt=claim,
            )
            self.assertEqual(consumed.authorization_effect, "NONE")
            journal = reopened.read_research_method_attempt(
                revision, cue_event_id="C:rollback"
            )
            self.assertEqual(journal.execution_state, "UNKNOWN")
            self.assertTrue(journal.evidence_split_qualified)
            self.assertEqual(journal.authorization_effect, "NONE")

            # A legacy/plain consumed cue has no recoverable method intent.
            reopened.consume(
                revision, cue_event_id="C:legacy", use_evidence_id="C:legacy-use",
                expected_calibration_evidence_ids=("A:1",),
            )
            self.assertIsNone(reopened.read_research_method_attempt(
                revision, cue_event_id="C:legacy"
            ))
            # Even direct DB modification cannot turn a prepared claim into
            # a false 'EXECUTED' declaration through this restricted schema.
            with self.assertRaises(sqlite3.IntegrityError), closing(sqlite3.connect(db_path)) as db, db:
                db.execute("""UPDATE learned_research_method_attempts
                    SET execution_state='EXECUTED' WHERE cue_event_id='C:rollback'""")
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute("""UPDATE learned_research_method_attempts
                    SET evidence_split_qualified=0 WHERE cue_event_id='C:rollback'""")
            with self.assertRaises(LearnedInfluenceBlocked):
                reopened.read_research_method_attempt(
                    revision, cue_event_id="C:rollback"
                )
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute("""UPDATE learned_research_method_attempts
                    SET evidence_split_qualified=1 WHERE cue_event_id='C:rollback'""")
                db.execute("""DELETE FROM learned_use_evidence
                    WHERE evidence_id='C:rollback-use'""")
            with self.assertRaises(LearnedInfluenceBlocked):
                reopened.read_research_method_attempt(
                    revision, cue_event_id="C:rollback"
                )

    def test_consumption_commit_then_crash_recovers_unknown_not_executed(self):
        baseline = MethodSpec("risk-check", (), "proceed")
        candidate = MethodSpec("risk-check", (("danger", "inspect"),), "proceed")
        a = (
            CalibrationCase("A:1", "danger near press", "inspect"),
            CalibrationCase("A:2", "line clear", "proceed"),
        )
        with TemporaryDirectory() as directory:
            choice_path = Path(directory) / "choice.json"
            db_path = Path(directory) / "gate.db"
            save_method_choice(
                choice_path, select_calibrated_method(baseline, (candidate,), a),
            )
            revision = selection_revision(choice_path)
            gate = DurableLearnedInfluenceGate(db_path)
            gate.review_qualified(
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review:B1",
                calibration_evidence_ids=("A:1", "A:2"),
                qualification_evidence_ids=("B:1",),
            )
            committed_consume = gate.consume

            def crash_after_commit(*args, **kwargs):
                committed_consume(*args, **kwargs)
                raise SystemExit("simulated process death after consumption commit")

            gate.consume = crash_after_commit
            with self.assertRaises(SystemExit):
                consume_research_method(
                    gate, choice_path, prompt="danger at conveyor",
                    cue_event_id="C:cue", later_use_evidence_id="C:use",
                )

            recovered = DurableLearnedInfluenceGate(db_path)
            # The C-use fence definitely committed: retry is a replay.
            with self.assertRaises(LearnedInfluenceReplay):
                recovered.consume(
                    revision, cue_event_id="C:cue", use_evidence_id="C:use",
                    expected_calibration_evidence_ids=("A:1", "A:2"),
                )
            durable_attempt = recovered.read_research_method_attempt(
                revision, cue_event_id="C:cue"
            )
            self.assertIsNotNone(durable_attempt)
            self.assertEqual(durable_attempt.execution_state, "UNKNOWN")
            self.assertEqual(durable_attempt.authorization_effect, "NONE")
            self.assertEqual(durable_attempt.use_evidence_id, "C:use")
            self.assertEqual(durable_attempt.selection_digest,
                             revision.association_id.removeprefix("research-selection:"))
            self.assertEqual(durable_attempt.method_digest, candidate.digest)

            # Persistent evidence is only a PREPARED C intention + consumption,
            # never fabricated method execution or independently observed effect.
            with closing(sqlite3.connect(db_path)) as db, db:
                row = db.execute(
                    "SELECT execution_state, authorization_effect "
                    "FROM learned_research_method_attempts WHERE cue_event_id=?",
                    ("C:cue",),
                ).fetchone()
            self.assertEqual(row, ("UNKNOWN", "NONE"))

            ordinary_return = consume_research_method(
                recovered, choice_path, prompt="danger at conveyor",
                cue_event_id="C:normal", later_use_evidence_id="C:normal-use",
            )
            self.assertEqual(ordinary_return.action, "inspect")
            normal_attempt = recovered.read_research_method_attempt(
                revision, cue_event_id="C:normal"
            )
            # Even when this call returned its ephemeral action to the test,
            # the durable store must not claim independently executed effects.
            self.assertEqual(normal_attempt.execution_state, "UNKNOWN")
            self.assertEqual(normal_attempt.authorization_effect, "NONE")


if __name__ == "__main__":
    unittest.main()
