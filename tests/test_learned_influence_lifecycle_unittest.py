"""SQLite handle lifetime regressions for durable learned influences."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from vera_memory.learned_influence import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceReplay,
    LearnedRevision,
    ReviewDisposition,
)


class _TrackedConnection(sqlite3.Connection):
    closed = False

    def close(self):
        self.closed = True
        return super().close()


class LearnedInfluenceConnectionLifecycleTests(unittest.TestCase):
    def _track(self, database: Path):
        connections = []

        def connect(gate):
            db = sqlite3.connect(
                database,
                timeout=5.0,
                isolation_level=None,
                factory=_TrackedConnection,
            )
            db.row_factory = sqlite3.Row
            connections.append(db)
            return db

        return connections, patch.object(DurableLearnedInfluenceGate, "_connect", connect)

    def test_constructor_and_review_close_connections(self):
        with tempfile.TemporaryDirectory(prefix="learned-lifecycle-") as tmp:
            path = Path(tmp) / "learned.db"
            connections, installed = self._track(path)
            with installed:
                gate = DurableLearnedInfluenceGate(path)
                gate.review(
                    association_id="association-1",
                    memory_revision_id="rev-1",
                    disposition=ReviewDisposition.ADMITTED,
                    evidence_ref="review-1",
                )
            self.assertEqual(len(connections), 2)
            self.assertTrue(all(db.closed for db in connections))

    def test_review_failure_rolls_back_and_closes_connection(self):
        with tempfile.TemporaryDirectory(prefix="learned-lifecycle-") as tmp:
            path = Path(tmp) / "learned.db"
            gate = DurableLearnedInfluenceGate(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    """CREATE TRIGGER block_learned_review BEFORE INSERT
                    ON learned_reviews BEGIN SELECT RAISE(FAIL, 'synthetic failure'); END"""
                )
            connections, installed = self._track(path)
            with installed:
                with self.assertRaises(sqlite3.IntegrityError):
                    gate.review(
                        association_id="association-1",
                        memory_revision_id="rev-1",
                        disposition=ReviewDisposition.ADMITTED,
                        evidence_ref="review-1",
                    )
            self.assertEqual(len(connections), 1)
            self.assertTrue(connections[0].closed)

    def test_review_and_replay_semantics_survive_restart(self):
        with tempfile.TemporaryDirectory(prefix="learned-lifecycle-") as tmp:
            path = Path(tmp) / "learned.db"
            revision = LearnedRevision("association-1", "rev-1")
            gate = DurableLearnedInfluenceGate(path)
            gate.review(
                association_id=revision.association_id,
                memory_revision_id=revision.memory_revision_id,
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review-1",
            )
            receipt = gate.consume(revision, cue_event_id="event-1")
            self.assertEqual(receipt.review_evidence_ref, "review-1")
            restarted = DurableLearnedInfluenceGate(path)
            with self.assertRaises(LearnedInfluenceReplay):
                restarted.consume(revision, cue_event_id="event-1")
            self.assertEqual(
                restarted.consume(revision, cue_event_id="event-2").cue_event_id,
                "event-2",
            )

    @unittest.skipUnless(os.name == "nt", "Windows lock behavior only")
    def test_file_can_be_removed_without_waiting_for_garbage_collection(self):
        with tempfile.TemporaryDirectory(prefix="learned-lifecycle-") as tmp:
            path = Path(tmp) / "learned.db"
            gate = DurableLearnedInfluenceGate(path)
            gate.review(
                association_id="association-1",
                memory_revision_id="rev-1",
                disposition=ReviewDisposition.ADMITTED,
                evidence_ref="review-1",
            )
            path.unlink()
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
