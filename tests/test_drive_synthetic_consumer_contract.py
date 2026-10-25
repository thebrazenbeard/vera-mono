"""Isolated negative contract suite; no MESO/Volition effects or imports."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


drive = load("_drive_contract_source", ROOT / "packages/vera_core/src/vera_core/drive_feedback.py")
consumer = load("_drive_consumer_review_source", ROOT / "research/drive_feedback/synthetic_consumer_review.py")


class DriveSyntheticConsumerContractTests(unittest.TestCase):
    def setUp(self):
        self.observation = drive.DriveObservation(
            event_id="outcome:1",
            attempt_id="attempt:1",
            physical_effect_id="physical:1",
            observer_id="synthetic:observer",
            source_sequence=1,
            observed_at_ms=2_000_000,
            need_id="rest",
            expected_need_revision=0,
            absolute_post_level=.7,
            unit="normalized",
            goal_id="goal:1",
            choice_id="choice:1",
            expected_goal_revision=0,
            effect_status="EFFECT",
            request_goal_credit=True,
            evidence_digest="a" * 64,
        )
        digest = drive._claim_sha256(self.observation)
        self.admission = drive.DriveAdmission(
            event_id="outcome:1", status="ADMITTED",
            claim_sha256=digest, need_revision=1, goal_credit=True,
            goal_credit_reason="EXACT_GOAL_SATISFIED", replayed=False,
        )
        self.item = drive.DriveOutboxItem(
            event_id="outcome:1", claim_sha256=digest, need_id="rest",
            need_revision=1, goal_credit=True,
            goal_credit_reason="EXACT_GOAL_SATISFIED",
        )

    def review(self, **overrides):
        kwargs = dict(
            item=self.item, observation=self.observation,
            admission=self.admission, now_ms=2_000_000,
            current_need_revision=1,
        )
        kwargs.update(overrides)
        return consumer.review_synthetic_outbox(**kwargs)

    def assertHeldWithoutCandidate(self, reason, **updates):
        outcome = self.review(**updates)
        self.assertEqual(outcome.status, "HOLD")
        self.assertEqual(outcome.reason, reason)
        self.assertIsNone(outcome.candidate)
        self.assertFalse(outcome.effect_authority)

    def test_structurally_matched_synthetic_claim_still_hold(self):
        result = self.review()
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.reason, "NO_INDEPENDENT_WITNESS_OR_DOWNSTREAM_ADMISSION")
        self.assertFalse(result.effect_authority)
        self.assertEqual(result.candidate.need_id, "rest")
        self.assertEqual(result.candidate.measured_level, .7)
        self.assertFalse(result.candidate.effect_authority)
        self.assertFalse(hasattr(result, "goal_completion_admission"))

    def test_default_missing_evidence_and_clock_fail_closed(self):
        self.assertEqual(consumer.review_synthetic_outbox(self.item).reason, "MISSING_SOURCE_RECORD")
        self.assertHeldWithoutCandidate("UNTRUSTED_OR_INVALID_CLOCK", now_ms=None)
        self.assertHeldWithoutCandidate("MISSING_CURRENT_NEED_REVISION", current_need_revision=None)

    def test_replay_and_previous_hold_cannot_become_new_admissions(self):
        self.assertHeldWithoutCandidate(
            "NOT_FRESHLY_ADMITTED", admission=replace(self.admission, status="REPLAY_NOOP", replayed=True),
        )
        self.assertHeldWithoutCandidate(
            "NOT_FRESHLY_ADMITTED", admission=replace(self.admission, status="HOLD"),
        )

    def test_expiry_and_future_timestamp_fail_closed(self):
        self.assertHeldWithoutCandidate("OBSERVATION_NOT_FRESH", now_ms=2_060_001)
        self.assertHeldWithoutCandidate("OBSERVATION_NOT_FRESH", now_ms=1_994_999)
        self.assertEqual(self.review(now_ms=2_060_000).status, "HOLD")

    def test_outbox_and_admission_cannot_be_relabelled(self):
        for mutated in (
            replace(self.item, event_id="outcome:other"),
            replace(self.item, need_id="other"),
            replace(self.item, need_revision=2),
            replace(self.item, claim_sha256="0" * 64),
        ):
            with self.subTest(mutated=mutated):
                self.assertHeldWithoutCandidate("SOURCE_OUTBOX_BINDING_MISMATCH", item=mutated)
        self.assertHeldWithoutCandidate(
            "GOAL_CREDIT_BINDING_MISMATCH", item=replace(self.item, goal_credit=False),
        )

    def test_original_observation_mutation_invalidates_original_digest(self):
        self.assertHeldWithoutCandidate(
            "SOURCE_OUTBOX_BINDING_MISMATCH",
            observation=replace(self.observation, absolute_post_level=.9),
        )

    def test_rehashed_forged_identifiers_do_not_create_typed_candidate(self):
        for field, value in (("event_id", None), ("need_id", None), ("need_id", [])):
            with self.subTest(field=field, value=value):
                forged = replace(self.observation, **{field: value})
                digest = drive._claim_sha256(forged)
                self.assertHeldWithoutCandidate(
                    "INVALID_SOURCE_IDENTIFIERS",
                    observation=forged,
                    item=replace(
                        self.item, event_id=forged.event_id, need_id=forged.need_id,
                        claim_sha256=digest,
                    ),
                    admission=replace(
                        self.admission, event_id=forged.event_id, claim_sha256=digest,
                    ),
                )

    def test_rehashed_forged_evidence_digest_does_not_create_typed_candidate(self):
        for value in (None, "NOT_SHA256", "A" * 64):
            with self.subTest(value=value):
                forged = replace(self.observation, evidence_digest=value)
                digest = drive._claim_sha256(forged)
                self.assertHeldWithoutCandidate(
                    "INVALID_SOURCE_EVIDENCE_DIGEST",
                    observation=forged,
                    item=replace(self.item, claim_sha256=digest),
                    admission=replace(self.admission, claim_sha256=digest),
                )

    def test_later_need_revision_cannot_recover_historical_level(self):
        self.assertHeldWithoutCandidate("OUTBOX_LEVEL_SUPERSEDED", current_need_revision=2)

    def test_real_sqlite_outbox_with_synthetic_verifier_is_never_admitted_downstream(self):
        class SyntheticVerifier:
            def verify(self, observation, digest):
                # This is explicitly a test double, NOT observer custody.
                return drive.DriveWitness(
                    claim_sha256=digest, observer_id=observation.observer_id,
                    attestation_id=f"synthetic:{observation.event_id}",
                    verified_at_ms=max(2_000_000, observation.observed_at_ms),
                )

        with TemporaryDirectory() as directory:
            store = drive.DriveFeedbackStore(
                Path(directory) / "db.sqlite", verifier=SyntheticVerifier(),
                clock_ms=lambda: 2_000_000,
            )
            store.register_need("rest", level=.2)
            store.register_goal("goal:1", need_id="rest", choice_id="choice:1", target_level=.6)
            admission = store.admit(self.observation)
            self.assertEqual(admission.status, "ADMITTED")
            original = store.pending_outbox()[0]
            review = self.review(item=original, admission=admission)
            self.assertEqual(review.status, "HOLD")
            self.assertFalse(review.effect_authority)
            self.assertEqual(review.candidate.measured_level, .7)

            later = replace(
                self.observation,
                event_id="outcome:2", attempt_id="attempt:2",
                physical_effect_id="physical:2", source_sequence=2,
                observed_at_ms=2_000_001, expected_need_revision=1,
                absolute_post_level=.8, goal_id=None, choice_id=None,
                expected_goal_revision=None, request_goal_credit=False,
                evidence_digest="b" * 64,
            )
            second = store.admit(later)
            self.assertEqual(second.status, "ADMITTED")
            self.assertEqual(store.read_need("rest").revision, 2)
            self.assertEqual(
                self.review(item=original, admission=admission, current_need_revision=2).reason,
                "OUTBOX_LEVEL_SUPERSEDED",
            )
            replay = store.admit(self.observation)
            self.assertEqual(replay.status, "REPLAY_NOOP")
            self.assertEqual(self.review(item=original, admission=replay).reason, "NOT_FRESHLY_ADMITTED")


if __name__ == "__main__":
    unittest.main()
