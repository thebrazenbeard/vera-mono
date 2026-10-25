"""Inert DRIVE outcome-to-need/goal SQLite reference contract."""

from __future__ import annotations

import importlib.util
import inspect
import os
from pathlib import Path
import sqlite3
import stat
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from dataclasses import replace

SOURCE = Path(__file__).resolve().parents[1] / "packages/vera_core/src/vera_core/drive_feedback.py"


def reference_module():
    spec = importlib.util.spec_from_file_location("_drive_feedback_under_test", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DriveFeedbackContractTests(unittest.TestCase):
    def test_source_reference_module_exists(self):
        self.assertTrue(SOURCE.is_file())

    def test_public_reference_types_exist(self):
        module = reference_module()
        self.assertTrue(all(hasattr(module, name) for name in (
            "DriveObservation", "DriveWitness", "DriveFeedbackStore",
            "DriveAdmission", "DriveFeedbackError",
        )))

    def test_store_has_explicit_host_verifier_and_atomic_admission_api(self):
        module = reference_module()
        parameters = inspect.signature(module.DriveFeedbackStore.__init__).parameters
        self.assertIn("verifier", parameters)
        self.assertIn("clock_ms", parameters)
        self.assertTrue(all(hasattr(module.DriveFeedbackStore, name) for name in (
            "register_need", "register_goal", "replace_goal", "veto_goal",
            "admit", "read_need", "read_goal", "pending_outbox", "ack_outbox",
        )))


class SyntheticHostVerifier:
    """A test fake, intentionally NOT a trusted external witness."""

    def __init__(self, module):
        self.module = module
        self.enabled = True
        self.observed = []
        self.fixed_attestation_id = None

    def verify(self, claim, claim_sha256):
        self.observed.append(claim.event_id)
        if not self.enabled:
            return None
        return self.module.DriveWitness(
            claim_sha256=claim_sha256,
            observer_id=claim.observer_id,
            attestation_id=self.fixed_attestation_id or f"synthetic:{claim.event_id}",
            verified_at_ms=2_000_000,
        )


class DriveFeedbackBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.module = reference_module()
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.path = Path(self.scratch.name) / "drive" / "feedback.sqlite"
        self.verifier = SyntheticHostVerifier(self.module)

    def store(self, *, verifier=True):
        return self.module.DriveFeedbackStore(
            self.path,
            verifier=self.verifier if verifier else None,
            clock_ms=lambda: 2_000_000,
        )

    def seed(self, store=None):
        s = store or self.store()
        s.register_need("need:rest", level=.2)
        s.register_goal(
            "goal:original", need_id="need:rest", choice_id="choice:original",
            target_level=.6,
        )
        return s

    def observation(self, **updates):
        value = dict(
            event_id="event:1",
            attempt_id="attempt:1",
            physical_effect_id="effect:1",
            observer_id="sensor:outside",
            source_sequence=1,
            observed_at_ms=1_999_000,
            need_id="need:rest",
            expected_need_revision=0,
            absolute_post_level=.8,
            unit="normalized",
            goal_id="goal:original",
            choice_id="choice:original",
            expected_goal_revision=0,
            effect_status="EFFECT",
            request_goal_credit=True,
            evidence_digest="a" * 64,
        )
        value.update(updates)
        return self.module.DriveObservation(**value)

    def test_unverified_candidates_and_forged_labels_do_not_mutate(self):
        s = self.seed(self.store(verifier=False))
        result = s.admit(self.observation(observer_id="observer:claimed"))
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.goal_credit_reason, "VERIFIER_UNAVAILABLE")
        self.assertEqual(s.read_need("need:rest").revision, 0)
        self.assertEqual(s.read_goal("goal:original").status, "ACTIVE")
        self.assertEqual(s.pending_outbox(), ())
        self.verifier.enabled = False
        result = self.store().admit(self.observation())
        self.assertEqual(result.goal_credit_reason, "WITNESS_UNAVAILABLE")
        self.assertEqual(self.store().pending_outbox(), ())

    def test_one_transaction_credits_exact_goal_and_restarts_without_duplication(self):
        s = self.seed()
        claim = self.observation()
        admitted = s.admit(claim)
        self.assertEqual(admitted.status, "ADMITTED")
        self.assertTrue(admitted.goal_credit)
        self.assertEqual(s.read_need("need:rest").revision, 1)
        self.assertEqual(s.read_need("need:rest").level, .8)
        self.assertEqual(s.read_goal("goal:original").status, "SATISFIED")
        self.assertEqual(s.read_goal("goal:original").credited_event_id, "event:1")
        restarted = self.store()
        self.assertEqual(len(restarted.pending_outbox()), 1)
        self.assertTrue(restarted.admit(claim).replayed)
        self.assertEqual(restarted.read_need("need:rest").revision, 1)
        self.assertEqual(len(restarted.pending_outbox()), 1)
        self.assertTrue(restarted.ack_outbox("event:1"))
        self.assertFalse(restarted.ack_outbox("event:1"))
        self.assertEqual(self.store().pending_outbox(), ())
        self.assertTrue(self.store().admit(claim).replayed)
        self.assertEqual(self.store().pending_outbox(), ())

    def test_duplicate_effect_attempt_evidence_sequence_and_changed_event_conflict(self):
        s = self.seed()
        claim = self.observation()
        s.admit(claim)
        for changes in (
            {"event_id": "event:2", "source_sequence": 2, "attempt_id": "attempt:2",
             "evidence_digest": "b" * 64},  # physical effect reused
            {"event_id": "event:2", "source_sequence": 2, "physical_effect_id": "effect:2",
             "evidence_digest": "b" * 64},  # attempt reused
            {"event_id": "event:2", "source_sequence": 2, "physical_effect_id": "effect:2",
             "attempt_id": "attempt:2"},  # evidence reused
            {"event_id": "event:2", "physical_effect_id": "effect:2",
             "attempt_id": "attempt:2", "evidence_digest": "b" * 64},  # observer sequence reused
            {"absolute_post_level": .7},  # same event changed claim
        ):
            with self.subTest(changes=changes), self.assertRaises(self.module.DriveFeedbackError):
                s.admit(self.observation(expected_need_revision=1, **changes))
        self.assertEqual(s.read_need("need:rest").revision, 1)
        self.assertEqual(len(s.pending_outbox()), 1)

    def test_stale_goal_replacement_accepts_independent_need_only_not_new_goal_credit(self):
        s = self.seed()
        s.replace_goal(
            "goal:original", new_goal_id="goal:replacement",
            new_choice_id="choice:new", target_level=.6,
        )
        old = s.admit(self.observation())
        self.assertEqual(old.status, "ADMITTED")
        self.assertFalse(old.goal_credit)
        self.assertEqual(old.goal_credit_reason, "GOAL_NOT_ACTIVE")
        self.assertEqual(s.read_need("need:rest").level, .8)
        self.assertEqual(s.read_goal("goal:replacement").status, "ACTIVE")
        self.assertEqual(s.read_goal("goal:original").status, "REPLACED")

    def test_failed_noop_and_increase_only_effects_never_credit_satisfaction(self):
        s = self.seed()
        for status in ("NO_EFFECT", "FAILED"):
            with self.subTest(status=status), self.assertRaises(self.module.DriveFeedbackError):
                s.admit(self.observation(effect_status=status))
        self.assertEqual(s.read_need("need:rest").revision, 0)
        worsened = s.admit(self.observation(absolute_post_level=.1))
        self.assertFalse(worsened.goal_credit)
        self.assertEqual(worsened.goal_credit_reason, "NO_NEED_IMPROVEMENT")
        self.assertEqual(s.read_need("need:rest").level, .1)

    def test_stale_need_revision_rejected_without_partial_outbox(self):
        s = self.seed()
        s.admit(self.observation())
        with self.assertRaises(self.module.DriveFeedbackError):
            s.admit(self.observation(
                event_id="event:second", attempt_id="attempt:second",
                physical_effect_id="effect:second", evidence_digest="b" * 64,
                source_sequence=2, expected_need_revision=0,
            ))
        self.assertEqual(s.read_need("need:rest").revision, 1)
        self.assertEqual(len(s.pending_outbox()), 1)

    def test_concurrent_distinct_effects_same_need_revision_only_one_wins(self):
        self.seed()
        claims = [
            self.observation(),
            self.observation(
                event_id="event:other", attempt_id="attempt:other",
                physical_effect_id="effect:other", evidence_digest="b" * 64,
                source_sequence=2,
            ),
        ]
        results = []
        lock = threading.Lock()

        def worker(claim):
            try:
                answer = self.store().admit(claim).status
            except self.module.DriveFeedbackError:
                answer = "REJECTED_STALE"
            with lock:
                results.append(answer)

        threads = [threading.Thread(target=worker, args=(claim,)) for claim in claims]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertCountEqual(results, ["ADMITTED", "REJECTED_STALE"])
        self.assertEqual(self.store().read_need("need:rest").revision, 1)
        self.assertEqual(len(self.store().pending_outbox()), 1)

    def test_each_injected_crash_boundary_rolls_back_every_projection(self):
        for stage in ("after_receipt", "after_need", "after_goal", "after_outbox"):
            with self.subTest(stage=stage):
                with TemporaryDirectory() as directory:
                    s = self.module.DriveFeedbackStore(
                        Path(directory) / "drive.sqlite",
                        verifier=self.verifier,
                        clock_ms=lambda: 2_000_000,
                    )
                    self.seed(s)

                    def inject(name):
                        if name == stage:
                            raise RuntimeError("injected crash")

                    s._fault_point = inject
                    with self.assertRaisesRegex(RuntimeError, "injected crash"):
                        s.admit(self.observation())
                    fresh = self.module.DriveFeedbackStore(
                        Path(directory) / "drive.sqlite", verifier=self.verifier,
                        clock_ms=lambda: 2_000_000,
                    )
                    self.assertEqual(fresh.read_need("need:rest").revision, 0)
                    self.assertEqual(fresh.read_goal("goal:original").status, "ACTIVE")
                    self.assertEqual(fresh.pending_outbox(), ())
                    self.assertTrue(fresh.admit(self.observation()).goal_credit)

    def test_malformed_and_untrusted_witness_never_admit(self):
        s = self.seed()
        for changes in (
            {"absolute_post_level": float("nan")},
            {"absolute_post_level": float("inf")},
            {"absolute_post_level": True},
            {"expected_need_revision": True},
            {"observed_at_ms": 2_999_999},
            {"event_id": "x" * 2000},
            {"evidence_digest": "invented"},
            {"source_sequence": 0},
            {"effect_status": []},
        ):
            with self.subTest(changes=changes):
                observation = self.observation(**changes)
                try:
                    answer = s.admit(observation)
                except self.module.DriveFeedbackError:
                    continue
                self.assertEqual(answer.status, "HOLD")
        self.assertEqual(s.read_need("need:rest").revision, 0)
        self.assertEqual(s.pending_outbox(), ())

    def test_veto_blocks_credit_without_hiding_trusted_need_measurement(self):
        s = self.seed()
        s.veto_goal("goal:original")
        result = s.admit(self.observation())
        self.assertFalse(result.goal_credit)
        self.assertEqual(result.goal_credit_reason, "GOAL_NOT_ACTIVE")
        self.assertEqual(s.read_need("need:rest").revision, 1)
        self.assertEqual(s.read_goal("goal:original").status, "VETOED")

    def test_reused_witness_identity_cannot_credit_a_second_goal(self):
        s = self.seed()
        self.verifier.fixed_attestation_id = "synthetic:shared-attestation"
        self.assertTrue(s.admit(self.observation()).goal_credit)
        s.register_goal(
            "goal:second", need_id="need:rest", choice_id="choice:second",
            target_level=.9,
        )
        with self.assertRaises(self.module.DriveFeedbackError):
            s.admit(self.observation(
                event_id="event:2", attempt_id="attempt:2",
                physical_effect_id="effect:2", evidence_digest="b" * 64,
                source_sequence=2, expected_need_revision=1,
                absolute_post_level=.95, goal_id="goal:second",
                choice_id="choice:second", expected_goal_revision=0,
            ))
        self.assertEqual(s.read_need("need:rest").revision, 1)
        self.assertEqual(s.read_goal("goal:second").status, "ACTIVE")

    def test_known_schema_with_dropped_projection_table_fails_closed(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE goal_projection")
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()

    def test_huge_level_fails_with_controlled_validation_error(self):
        s = self.seed()
        with self.assertRaises(self.module.DriveFeedbackError):
            s.admit(self.observation(absolute_post_level=10**5000))

    def test_observer_clock_cannot_move_backward_on_later_sequence(self):
        s = self.seed()
        s.admit(self.observation())
        with self.assertRaises(self.module.DriveFeedbackError):
            s.admit(self.observation(
                event_id="event:second", attempt_id="attempt:second",
                physical_effect_id="effect:second", evidence_digest="b" * 64,
                source_sequence=2, observed_at_ms=1_998_000,
                expected_need_revision=1, absolute_post_level=.7,
                goal_id=None, choice_id=None, expected_goal_revision=None,
                request_goal_credit=False,
            ))
        self.assertEqual(s.read_need("need:rest").revision, 1)

    def test_only_one_active_goal_can_own_a_need_at_once(self):
        s = self.seed()
        with self.assertRaises(self.module.DriveFeedbackError):
            s.register_goal(
                "goal:second", need_id="need:rest",
                choice_id="choice:second", target_level=.7,
            )
        self.assertEqual(s.read_goal("goal:original").status, "ACTIVE")
        with self.assertRaises(KeyError):
            s.read_goal("goal:second")

    def test_unversioned_partial_schema_is_not_silently_repaired(self):
        self.path.parent.mkdir(parents=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE need_projection("
                "need_id TEXT PRIMARY KEY, revision INTEGER, level REAL, unit TEXT)"
            )
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()

    def test_unversioned_preexisting_valid_store_is_not_silently_adopted(self):
        s = self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA user_version = 0")
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()

    def test_known_schema_with_same_column_names_but_no_uniques_is_rejected(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE outcome_receipt")
            # Matching column names are insufficient to enforce exactly-once.
            db.execute("""
                CREATE TABLE outcome_receipt (
                    event_id TEXT, attempt_id TEXT, physical_effect_id TEXT,
                    evidence_digest TEXT, observer_id TEXT, source_sequence INTEGER,
                    observed_at_ms INTEGER, claim_sha256 TEXT, witness_id TEXT,
                    need_id TEXT, need_revision INTEGER, goal_credit INTEGER,
                    goal_credit_reason TEXT
                )
            """)
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()

    def test_unexpected_trigger_is_rejected_before_running_any_admission(self):
        self.seed()
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TRIGGER forge_on_receipt AFTER INSERT ON outcome_receipt
                BEGIN UPDATE need_projection SET level=1; END
            """)
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()

    def test_outbox_batch_is_bounded_and_does_not_discard_items(self):
        s = self.seed()
        s.admit(self.observation())
        self.assertEqual(len(s.pending_outbox(limit=1)), 1)
        for invalid in (0, 1001, True, 1.1):
            with self.subTest(invalid=invalid), self.assertRaises(self.module.DriveFeedbackError):
                s.pending_outbox(limit=invalid)
        self.assertEqual(len(s.pending_outbox()), 1)

    def test_bootstrap_interruption_rolls_back_all_schema_objects_and_version(self):
        base = self.module.DriveFeedbackStore
        for failure_stage in (1, 2, 3, 4, 5, "after_version"):
            with self.subTest(stage=failure_stage):
                path = self.path.with_name(f"bootstrap-{failure_stage}.sqlite")

                class InterruptedBootstrap(base):
                    @staticmethod
                    def _bootstrap_fault_point(stage):
                        if stage == failure_stage:
                            raise RuntimeError("simulated first-open power loss")

                with self.assertRaisesRegex(RuntimeError, "simulated first-open power loss"):
                    InterruptedBootstrap(path)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
                    self.assertEqual(db.execute(
                        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0], 0)
                restarted = base(path)
                self.assertEqual(restarted.register_need("need:rest", level=.2).revision, 0)

    def test_concurrent_first_open_is_idempotent_and_serialized(self):
        for batch in range(12):
            with self.subTest(batch=batch):
                path = self.path.with_name(f"first-open-{batch}.sqlite")
                barrier = threading.Barrier(8)
                results = []
                lock = threading.Lock()

                def bootstrap():
                    try:
                        barrier.wait(timeout=5)
                        self.module.DriveFeedbackStore(path)
                        result = "READY"
                    except Exception as exc:
                        result = f"{type(exc).__name__}:{exc}"
                    with lock:
                        results.append(result)

                threads = [threading.Thread(target=bootstrap) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(results, ["READY"] * 8)
                self.module.DriveFeedbackStore(path).register_need("need:rest", level=.2)

    def test_verifier_latency_cannot_admit_an_expired_observation(self):
        now = [2_000_000]

        class SlowVerifier(SyntheticHostVerifier):
            def verify(inner_self, claim, claim_sha256):
                witness = super().verify(claim, claim_sha256)
                now[0] = 2_100_000
                return witness

        s = self.module.DriveFeedbackStore(
            self.path, verifier=SlowVerifier(self.module), clock_ms=lambda: now[0]
        )
        self.seed(s)
        result = s.admit(self.observation())
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.goal_credit_reason, "OBSERVATION_NOT_FRESH")
        self.assertEqual(s.read_need("need:rest").revision, 0)
        self.assertEqual(s.pending_outbox(), ())

    def test_commit_latency_cannot_admit_an_expired_observation(self):
        now = [2_000_000]
        s = self.module.DriveFeedbackStore(
            self.path, verifier=self.verifier, clock_ms=lambda: now[0]
        )
        self.seed(s)

        def latency(stage):
            if stage == "after_outbox":
                now[0] = 2_100_000

        s._fault_point = latency
        result = s.admit(self.observation())
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.goal_credit_reason, "OBSERVATION_NOT_FRESH")
        self.assertEqual(s.read_need("need:rest").revision, 0)
        self.assertEqual(s.read_goal("goal:original").status, "ACTIVE")
        self.assertEqual(s.pending_outbox(), ())

    @unittest.skipUnless(os.name == "posix", "POSIX owner/mode semantics")
    def test_private_directory_and_database_created_with_private_modes(self):
        s = self.store()
        self.assertEqual(stat.S_IMODE(s.path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(s.path.stat().st_mode), 0o600)
        with sqlite3.connect(s.path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    @unittest.skipUnless(os.name == "posix", "POSIX owner/mode semantics")
    def test_preexisting_shared_directory_or_database_is_not_silently_chmodded(self):
        self.path.parent.mkdir(parents=True, mode=0o755)
        self.path.parent.chmod(0o755)
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()
        self.path.parent.chmod(0o700)
        self.path.touch(mode=0o644)
        self.path.chmod(0o644)
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink semantics")
    def test_symlinked_file_or_parent_is_rejected(self):
        self.path.parent.mkdir(parents=True, mode=0o700)
        target = self.path.parent / "target.sqlite"
        target.touch(mode=0o600)
        self.path.symlink_to(target)
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()
        self.path.unlink()
        link_parent = self.path.parent.parent / "linked-parent"
        link_parent.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(self.module.DriveFeedbackError):
            self.module.DriveFeedbackStore(link_parent / "test.sqlite")

    def test_foreign_journal_mode_is_not_silently_used(self):
        s = self.seed()
        with sqlite3.connect(s.path) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        with self.assertRaises(self.module.DriveFeedbackError):
            self.store()


if __name__ == "__main__":
    unittest.main()
