"""Research-only negative-transfer feedback; disposable test signer, no live custody."""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vera_memory.learned_influence import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceBlocked,
    LearnedInfluenceReplay,
    LearnedRevision,
    ReviewDisposition,
    SignedLaterOutcome,
)


class SignedLaterOutcomeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self.revision = LearnedRevision("method:alpha", "revision:1")

    def _gate(self, path: Path) -> DurableLearnedInfluenceGate:
        # The test harness stands in for a separate protected host-provisioning
        # effect. Product code MUST NOT enroll the first caller's evaluator key.
        DurableLearnedInfluenceGate(path)
        with closing(sqlite3.connect(path)) as db, db:
            row = db.execute(
                "SELECT 1 FROM learned_outcome_trust WHERE singleton=1"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO learned_outcome_trust VALUES (1, ?, ?)",
                    (
                        "fixture:external-evaluator",
                        hashlib.sha256(self.public).hexdigest(),
                    ),
                )
        return DurableLearnedInfluenceGate(
            path,
            evaluator_id="fixture:external-evaluator",
            evaluator_public_key=self.public,
        )

    def _prepare(self, gate: DurableLearnedInfluenceGate) -> None:
        gate.review_qualified(
            association_id=self.revision.association_id,
            memory_revision_id=self.revision.memory_revision_id,
            disposition=ReviewDisposition.ADMITTED,
            evidence_ref="fixture:qualified-review",
            calibration_evidence_ids=("calibration:A1",),
            qualification_evidence_ids=("qualification:B1",),
        )
        gate.consume(
            self.revision, cue_event_id="cue:C1", use_evidence_id="later:C1"
        )

    def _signed(self, baseline_loss: float, candidate_loss: float):
        unsigned = SignedLaterOutcome(
            evaluator_id="fixture:external-evaluator",
            association_id=self.revision.association_id,
            memory_revision_id=self.revision.memory_revision_id,
            cue_event_id="cue:C1",
            use_evidence_id="later:C1",
            outcome_evidence_id="outcome:external:C1",
            baseline_loss=baseline_loss,
            candidate_loss=candidate_loss,
            signature_hex="0" * 128,
        )
        return self._resign(unsigned)

    def _resign(self, unsigned: SignedLaterOutcome, **changes) -> SignedLaterOutcome:
        payload = replace(unsigned, **changes)
        return replace(
            payload, signature_hex=self.private.sign(payload.signing_bytes()).hex()
        )

    def test_verified_negative_transfer_quarantines_exact_revision_after_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.db"
            gate = self._gate(path)
            self._prepare(gate)
            receipt = gate.record_later_outcome(self._signed(0.0, 1.0))
            self.assertTrue(receipt.negative_transfer)

            restarted = self._gate(path)
            with self.assertRaises(LearnedInfluenceBlocked):
                restarted.consume(
                    self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
                )
            # Reasserting ADMITTED must not launder an observed bad revision.
            restarted.review_qualified(
                association_id=self.revision.association_id,
                memory_revision_id=self.revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:second-review",
                calibration_evidence_ids=("calibration:A1",),
                qualification_evidence_ids=("qualification:B2",),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                restarted.consume(
                    self.revision, cue_event_id="cue:C3", use_evidence_id="later:C3"
                )

    def test_forged_score_and_replay_are_rejected_without_extra_effect(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            signed = self._signed(0.0, 1.0)
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(replace(signed, candidate_loss=0.0))
            self.assertTrue(gate.record_later_outcome(signed).negative_transfer)
            with self.assertRaises(LearnedInfluenceReplay):
                gate.record_later_outcome(signed)

    def test_outcome_without_matching_later_use_cannot_poison_revision(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            gate.review_qualified(
                association_id=self.revision.association_id,
                memory_revision_id=self.revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:review",
                calibration_evidence_ids=("calibration:A1",),
                qualification_evidence_ids=("qualification:B1",),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(self._signed(0.0, 1.0))
            gate.consume(
                self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
            )

    def test_verified_nonregression_does_not_create_a_promotion(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.db"
            gate = self._gate(path)
            self._prepare(gate)
            receipt = gate.record_later_outcome(self._signed(1.0, 0.0))
            self.assertFalse(receipt.negative_transfer)
            self.assertEqual(receipt.authorization_effect, "NONE")
            restarted = self._gate(path)
            allowed = restarted.consume(
                self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
            )
            self.assertEqual(allowed.authorization_effect, "NONE")

    def test_cross_paired_cue_and_use_must_not_poison_revision(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)  # cue:C1 and later:C1
            gate.consume(
                self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
            )
            cross_paired = self._resign(
                self._signed(0.0, 1.0), use_evidence_id="later:C2"
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(cross_paired)
            # Invalid evidence must not poison the previously admitted revision.
            gate.consume(
                self.revision, cue_event_id="cue:C3", use_evidence_id="later:C3"
            )

    def test_signed_outcome_cannot_relabel_any_prior_c_cue_as_outcome_evidence(self):
        for reused_cue in ("cue:C1", "cue:C2"):
            with self.subTest(reused_cue=reused_cue), TemporaryDirectory() as directory:
                gate = self._gate(Path(directory) / "gate.db")
                self._prepare(gate)
                gate.consume(
                    self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
                )
                reused = self._resign(
                    self._signed(0.0, 1.0), outcome_evidence_id=reused_cue
                )
                with self.assertRaises(LearnedInfluenceBlocked):
                    gate.record_later_outcome(reused)
                # Rejection cannot persist a spurious negative-transfer result.
                gate.consume(
                    self.revision, cue_event_id="cue:C3", use_evidence_id="later:C3"
                )

    def test_later_c_cue_cannot_relabel_recorded_outcome_evidence(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            receipt = gate.record_later_outcome(self._signed(1.0, 0.0))
            self.assertFalse(receipt.negative_transfer)
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.consume(
                    self.revision, cue_event_id="outcome:external:C1",
                    use_evidence_id="later:C2",
                )
            gate.consume(
                self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
            )

    def test_c_cue_and_use_evidence_cannot_exchange_roles(self):
        for cue, use in (
            ("later:C1", "later:C2"),
            ("cue:C2", "cue:C1"),
            ("cue:C2", "cue:C2"),
        ):
            with self.subTest(cue=cue, use=use), TemporaryDirectory() as directory:
                gate = self._gate(Path(directory) / "gate.db")
                self._prepare(gate)
                with self.assertRaises(LearnedInfluenceBlocked):
                    gate.consume(self.revision, cue_event_id=cue, use_evidence_id=use)
                gate.consume(
                    self.revision, cue_event_id="cue:valid", use_evidence_id="later:valid"
                )

    def test_c_use_cannot_relabel_earlier_signed_outcome(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            gate.record_later_outcome(self._signed(1.0, 0.0))
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.consume(
                    self.revision, cue_event_id="cue:C2",
                    use_evidence_id="outcome:external:C1",
                )
            gate.consume(
                self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
            )

    def test_review_cannot_relabel_any_prior_c_role_as_a_or_b(self):
        for prior in ("cue:C1", "later:C1", "outcome:external:C1"):
            for new_role in ("A", "B"):
                with self.subTest(prior=prior, role=new_role), TemporaryDirectory() as directory:
                    gate = self._gate(Path(directory) / "gate.db")
                    self._prepare(gate)
                    gate.record_later_outcome(self._signed(1.0, 0.0))
                    with self.assertRaises(LearnedInfluenceBlocked):
                        gate.review_qualified(
                            association_id=self.revision.association_id,
                            memory_revision_id=self.revision.memory_revision_id,
                            disposition=ReviewDisposition.ADMITTED,
                            evidence_ref="fixture:re-review-relabel-C",
                            calibration_evidence_ids=(
                                (prior,) if new_role == "A" else ("calibration:A1",)
                            ),
                            qualification_evidence_ids=(
                                (prior,) if new_role == "B" else ("qualification:B1",)
                            ),
                        )
                    gate.consume(
                        self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
                    )

    def test_historical_a_cannot_be_reclassified_as_b_on_re_review(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            gate.review_qualified(
                association_id=self.revision.association_id,
                memory_revision_id=self.revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:legitimate-A2-B2",
                calibration_evidence_ids=("calibration:A2",),
                qualification_evidence_ids=("qualification:B2",),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.review_qualified(
                    association_id=self.revision.association_id,
                    memory_revision_id=self.revision.memory_revision_id,
                    disposition=ReviewDisposition.ADMITTED,
                    evidence_ref="fixture:reclassified-A1-as-B",
                    calibration_evidence_ids=("calibration:A2",),
                    qualification_evidence_ids=("calibration:A1",),
                )
            gate.consume(
                self.revision, cue_event_id="cue:C2", use_evidence_id="later:C2"
            )

    def test_legacy_role_collision_survives_restart_and_blocks_new_use(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.db"
            gate = self._gate(path)
            self._prepare(gate)
            # Simulate an old database that admitted a use evidence identity
            # already present as a C cue. Preserve it for explicit recovery.
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "INSERT INTO learned_use_evidence VALUES(?,?,?)",
                    (
                        self.revision.association_id,
                        self.revision.memory_revision_id,
                        "cue:C1",
                    ),
                )
            recovered = self._gate(path)
            with self.assertRaises(LearnedInfluenceBlocked):
                recovered.consume(
                    self.revision, cue_event_id="cue:C2",
                    use_evidence_id="later:C2",
                )
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM learned_use_evidence "
                        "WHERE evidence_id='cue:C1'"
                    ).fetchone()[0], 1,
                )

    def test_orphaned_cue_use_binding_still_reserves_both_role_ids(self):
        for orphan_id, new_role in (("cue:C1", "B"), ("later:C1", "A")):
            with self.subTest(orphan=orphan_id), TemporaryDirectory() as directory:
                path = Path(directory) / "gate.db"
                gate = self._gate(path)
                self._prepare(gate)
                # Simulate a damaged legacy database where the paired row
                # survived but both primary role-table entries were lost.
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("DELETE FROM learned_consumptions")
                    db.execute("DELETE FROM learned_use_evidence")
                recovered = self._gate(path)
                with self.assertRaises(LearnedInfluenceBlocked):
                    recovered.review_qualified(
                        association_id=self.revision.association_id,
                        memory_revision_id=self.revision.memory_revision_id,
                        disposition=ReviewDisposition.ADMITTED,
                        evidence_ref="fixture:orphan-pair-relabel",
                        calibration_evidence_ids=(
                            (orphan_id,) if new_role == "A" else ("calibration:A1",)
                        ),
                        qualification_evidence_ids=(
                            (orphan_id,) if new_role == "B" else ("qualification:B1",)
                        ),
                    )
                with self.assertRaises(LearnedInfluenceBlocked):
                    recovered.consume(
                        self.revision,
                        cue_event_id=(orphan_id if new_role == "B" else "cue:new"),
                        use_evidence_id=(orphan_id if new_role == "A" else "later:new"),
                    )
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM learned_use_cue_bindings")
                        .fetchone()[0], 1,
                    )

    def test_orphaned_signed_outcome_still_reserves_cue_and_use_ids(self):
        for orphan_id, new_role in (("cue:C1", "B"), ("later:C1", "A")):
            with self.subTest(orphan=orphan_id), TemporaryDirectory() as directory:
                path = Path(directory) / "gate.db"
                gate = self._gate(path)
                self._prepare(gate)
                gate.record_later_outcome(self._signed(1.0, 0.0))
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute("DELETE FROM learned_consumptions")
                    db.execute("DELETE FROM learned_use_evidence")
                    db.execute("DELETE FROM learned_use_cue_bindings")
                recovered = self._gate(path)
                with self.assertRaises(LearnedInfluenceBlocked):
                    recovered.review_qualified(
                        association_id=self.revision.association_id,
                        memory_revision_id=self.revision.memory_revision_id,
                        disposition=ReviewDisposition.ADMITTED,
                        evidence_ref="fixture:orphan-outcome-relabel",
                        calibration_evidence_ids=(
                            (orphan_id,) if new_role == "A" else ("calibration:A1",)
                        ),
                        qualification_evidence_ids=(
                            (orphan_id,) if new_role == "B" else ("qualification:B1",)
                        ),
                    )
                with self.assertRaises(LearnedInfluenceBlocked):
                    recovered.consume(
                        self.revision,
                        cue_event_id=(orphan_id if new_role == "B" else "cue:new"),
                        use_evidence_id=(orphan_id if new_role == "A" else "later:new"),
                    )
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM learned_later_outcomes")
                        .fetchone()[0], 1,
                    )

    def test_prior_qualification_id_cannot_be_reclassified_as_outcome(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            gate.review_qualified(
                association_id=self.revision.association_id,
                memory_revision_id=self.revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:re-review",
                calibration_evidence_ids=("calibration:A1",),
                qualification_evidence_ids=("qualification:B2",),
            )
            old_b_as_c = self._resign(
                self._signed(0.0, 1.0),
                outcome_evidence_id="qualification:B1",
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(old_b_as_c)

    def test_prior_qualification_id_cannot_be_reused_as_later_use(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            gate.review_qualified(
                association_id=self.revision.association_id,
                memory_revision_id=self.revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:re-review",
                calibration_evidence_ids=("calibration:A1",),
                qualification_evidence_ids=("qualification:B2",),
            )
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.consume(
                    self.revision,
                    cue_event_id="cue:C2",
                    use_evidence_id="qualification:B1",
                )

    def test_no_evaluator_and_changed_key_cannot_admit_outcome(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "gate.db"
            gate = DurableLearnedInfluenceGate(path)
            self._prepare(gate)
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(self._signed(0.0, 1.0))
            rogue_key = Ed25519PrivateKey.generate().public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw
            )
            with self.assertRaisesRegex(LearnedInfluenceBlocked, "host provisioning"):
                DurableLearnedInfluenceGate(
                    path, evaluator_id="fixture:external-evaluator",
                    evaluator_public_key=rogue_key,
                )
            pinned = self._gate(path)
            with self.assertRaises(LearnedInfluenceBlocked):
                DurableLearnedInfluenceGate(
                    path,
                    evaluator_id="fixture:external-evaluator",
                    evaluator_public_key=Ed25519PrivateKey.generate()
                    .public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
                )
            self.assertTrue(pinned.record_later_outcome(self._signed(0.0, 1.0)).negative_transfer)

    def test_nonfinite_and_negative_zero_metrics_fail_before_signature(self):
        signed = self._signed(0.0, 1.0)
        for value in (float("nan"), float("inf"), float("-inf"), -0.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(signed, candidate_loss=value)

    def test_stale_revision_outcome_does_not_quarantine_successor(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            gate.record_later_outcome(self._signed(0.0, 1.0))
            successor = LearnedRevision(self.revision.association_id, "revision:2")
            gate.review_qualified(
                association_id=successor.association_id,
                memory_revision_id=successor.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="fixture:successor-review",
                calibration_evidence_ids=("calibration:A3",),
                qualification_evidence_ids=("qualification:B3",),
            )
            next_use = gate.consume(
                successor, cue_event_id="cue:new", use_evidence_id="later:new"
            )
            self.assertEqual(next_use.memory_revision_id, successor.memory_revision_id)
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(self._resign(
                    self._signed(0.0, 1.0), memory_revision_id="revision:unknown"
                ))

    def test_concurrent_signed_outcomes_have_exactly_one_durable_winner(self):
        with TemporaryDirectory() as directory:
            gate = self._gate(Path(directory) / "gate.db")
            self._prepare(gate)
            initial = self._signed(0.0, 1.0)
            second = self._resign(
                initial, outcome_evidence_id="outcome:external:C1-other"
            )

            def record(outcome):
                try:
                    return gate.record_later_outcome(outcome).negative_transfer
                except LearnedInfluenceReplay:
                    return "REPLAY"

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(record, (initial, second)))
            self.assertCountEqual(results, (True, "REPLAY"))

    def test_legacy_evidence_backfills_but_unpaired_legacy_c_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-gate.db"
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript("""
                    CREATE TABLE learned_reviews (
                      association_id TEXT PRIMARY KEY,
                      memory_revision_id TEXT, disposition TEXT, evidence_ref TEXT);
                    CREATE TABLE learned_consumptions (
                      association_id TEXT, memory_revision_id TEXT, cue_event_id TEXT,
                      PRIMARY KEY(association_id,memory_revision_id,cue_event_id));
                    CREATE TABLE learned_evidence_bindings (
                      association_id TEXT, memory_revision_id TEXT,
                      evidence_class TEXT, evidence_id TEXT,
                      PRIMARY KEY(association_id,memory_revision_id,evidence_class,evidence_id));
                    CREATE TABLE learned_use_evidence (
                      association_id TEXT, memory_revision_id TEXT, evidence_id TEXT,
                      PRIMARY KEY(association_id,memory_revision_id,evidence_id));
                """)
                db.execute("INSERT INTO learned_reviews VALUES (?,?,?,?)", (
                    self.revision.association_id, self.revision.memory_revision_id,
                    "ADMITTED", "fixture:legacy-review"))
                db.executemany("INSERT INTO learned_evidence_bindings VALUES (?,?,?,?)", (
                    (self.revision.association_id, self.revision.memory_revision_id,
                     kind, evidence_id) for kind, evidence_id in (
                        ("CALIBRATION", "calibration:A1"),
                        ("QUALIFICATION", "qualification:B1"))))
                db.execute("INSERT INTO learned_consumptions VALUES (?,?,?)", (
                    self.revision.association_id, self.revision.memory_revision_id,
                    "cue:C1"))
                db.execute("INSERT INTO learned_use_evidence VALUES (?,?,?)", (
                    self.revision.association_id, self.revision.memory_revision_id,
                    "later:C1"))

            gate = self._gate(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM learned_evidence_history"
                ).fetchone()[0], 2)
            # The old schema never paired cue:C1 with later:C1. It is unsafe
            # to manufacture that relation during schema migration.
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.record_later_outcome(self._signed(0.0, 1.0))
            with self.assertRaises(LearnedInfluenceBlocked):
                gate.consume(
                    self.revision, cue_event_id="cue:C2",
                    use_evidence_id="qualification:B1",
                )


if __name__ == "__main__":
    unittest.main()
