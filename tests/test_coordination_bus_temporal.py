from __future__ import annotations

from dataclasses import replace
import unittest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    HmacTemporalEvidenceAuthority,
    InMemoryCoordinationRepository,
    TemporalEvidence,
    acknowledgement_subject,
    entry_checkpoint_subject,
    exit_checkpoint_subject,
)


T0 = "2026-07-30T22:20:00+00:00"
T1 = "2026-07-30T22:20:01+00:00"
T2 = "2026-07-30T22:20:02+00:00"


def exact(value: str, role: str) -> TemporalEvidence:
    return TemporalEvidence.exact(
        value,
        source="HOST_CLOCK",
        reference_id=f"host:{role}:{value}",
    )


class TemporalCoordinationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryCoordinationRepository()
        self.authority = HmacTemporalEvidenceAuthority(
            "temporal-test-host", b"t" * 32
        )
        self.bus = CoordinationBus(
            self.repo,
            evidence_verifier=self.authority,
            receipt_time_provider=lambda role, subject: self.authority.issue(
                exact(T2, "receipt"), role=role, subject=subject
            ),
        )
        self.memory = ActorContext("workstream/memory", ALL_PERMISSIONS)
        self.time = ActorContext("workstream/time", ALL_PERMISSIONS)
        self.integration = ActorContext("workstream/integration", ALL_PERMISSIONS)

    def post_to_time(self, thread: str) -> None:
        result = self.bus.coordination_post(
            self.memory,
            CoordinationEventDraft(
                thread_key=thread,
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="STATUS",
                status="IN_PROGRESS",
                objective=thread,
                summary=f"status for {thread}",
            ),
        )
        self.assertEqual(result.receipt.result_class, "COMPLETE")

    def test_limited_page_returns_candidate_cursor_and_has_more(self):
        self.post_to_time("one")
        self.post_to_time("two")
        subject = entry_checkpoint_subject("workstream/time", 0, 1)
        result = self.bus.entry_checkpoint(
            self.time,
            after_sequence=0,
            limit=1,
            entry_time=self.authority.issue(
                exact(T0, "entry"),
                role="entry_time",
                subject=subject,
            ),
            retrieval_time=self.authority.issue(
                exact(T1, "retrieval"),
                role="retrieval_time",
                subject=subject,
            ),
        )
        self.assertEqual(result.receipt.cursor_in, 0)
        self.assertEqual(result.receipt.cursor_out, 1)
        self.assertEqual(result.receipt.page_limit, 1)
        self.assertTrue(result.receipt.has_more)
        self.assertFalse(result.receipt.page_complete)
        self.assertFalse(result.receipt.cursor_committed)
        self.assertEqual(result.receipt.entry_time.precision, "EXACT")
        self.assertEqual(result.receipt.retrieval_time.precision, "EXACT")

    def test_cursor_handles_sequence_gaps_without_inventing_time(self):
        self.post_to_time("one")
        self.post_to_time("two")
        self.post_to_time("three")
        self.repo._events = [
            replace(self.repo._events[0], event_sequence=2),
            replace(self.repo._events[1], event_sequence=7),
            replace(self.repo._events[2], event_sequence=11),
        ]
        result = self.bus.entry_checkpoint(self.time, after_sequence=2, limit=1)
        self.assertEqual([event.event_sequence for event in result.events], [7])
        self.assertEqual(result.receipt.cursor_out, 7)
        self.assertTrue(result.receipt.has_more)
        self.assertIn(
            "Sequence gaps do not imply missing time",
            " ".join(result.receipt.limitations),
        )

    def test_empty_page_preserves_cursor(self):
        result = self.bus.entry_checkpoint(self.time, after_sequence=99, limit=10)
        self.assertEqual(result.events, ())
        self.assertEqual(result.receipt.cursor_in, 99)
        self.assertEqual(result.receipt.cursor_out, 99)
        self.assertFalse(result.receipt.has_more)
        self.assertTrue(result.receipt.page_complete)

    def test_missing_checkpoint_times_are_explicit_unknown(self):
        result = self.bus.entry_checkpoint(self.time)
        self.assertEqual(result.receipt.entry_time.precision, "UNKNOWN")
        self.assertEqual(result.receipt.retrieval_time.precision, "UNKNOWN")
        self.assertIsNone(result.receipt.entry_time.value)
        self.assertIsNone(result.receipt.retrieval_time.value)

    def test_acknowledgement_does_not_invent_consumption_time(self):
        self.post_to_time("ack-thread")
        original = self.repo._events[-1]
        summary = "Acknowledged for review."
        subject = acknowledgement_subject(
            original.event_id,
            actor_workstream=self.time.workstream,
            thread_key=original.thread_key,
            summary=summary,
        )
        result = self.bus.coordination_acknowledge(
            self.time,
            event_id=original.event_id,
            summary=summary,
            acknowledgement_time=self.authority.issue(
                exact(T1, "acknowledgement"),
                role="acknowledgement_time",
                subject=subject,
            ),
        )
        temporal = result.events[0].payload["temporal"]
        self.assertEqual(temporal["consumption_time"]["precision"], "UNKNOWN")
        self.assertEqual(
            temporal["record_time_semantics"],
            "DATABASE_PERSISTENCE_TIME_ONLY",
        )
        self.assertIn(
            "does not prove processing completion",
            " ".join(result.receipt.limitations),
        )

    def test_material_exit_separates_event_state_and_record_time(self):
        objective = "Publish bounded handoff"
        summary = "Temporal review completed."
        status = "READY_FOR_REVIEW"
        subject = exit_checkpoint_subject(
            "workstream/integration",
            "exit-thread",
            "workstream/time",
            objective=objective,
            summary=summary,
            material=True,
            status=status,
        )
        result = self.bus.exit_checkpoint(
            self.integration,
            thread_key="exit-thread",
            target_branch="workstream/time",
            objective=objective,
            summary=summary,
            material=True,
            status=status,
            event_time=self.authority.issue(
                exact(T0, "event"),
                role="event_time",
                subject=subject,
            ),
            state_time=self.authority.issue(
                exact(T1, "state"),
                role="state_time",
                subject=subject,
            ),
        )
        temporal = result.events[0].payload["temporal"]
        self.assertEqual(temporal["event_time"]["value"], T0)
        self.assertEqual(temporal["state_time"]["value"], T1)
        self.assertNotEqual(result.events[0].record_time, T0)
        self.assertNotEqual(result.events[0].record_time, T1)

    def test_receipt_time_is_excluded_from_deterministic_result_hash(self):
        times = iter([exact(T1, "receipt-one"), exact(T2, "receipt-two")])
        authority = HmacTemporalEvidenceAuthority(
            "receipt-test-host", b"r" * 32
        )
        bus = CoordinationBus(
            self.repo,
            evidence_verifier=authority,
            receipt_time_provider=lambda role, subject: authority.issue(
                next(times), role=role, subject=subject
            ),
        )
        first = bus.entry_checkpoint(self.time)
        second = bus.entry_checkpoint(self.time)
        self.assertNotEqual(
            first.receipt.receipt_time.value,
            second.receipt.receipt_time.value,
        )
        self.assertEqual(first.receipt.result_hash, second.receipt.result_hash)

    def test_record_time_cannot_substitute_for_material_event_time(self):
        hostile = TemporalEvidence.exact(
            T0,
            source="COORDINATION_RECORD_TIME",
            reference_id="row:record-time",
        )
        result = self.bus.exit_checkpoint(
            self.integration,
            thread_key="hostile-exit",
            target_branch="workstream/time",
            objective="Attempt record-time substitution",
            summary="Hostile temporal input.",
            material=True,
            event_time=hostile,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")
        self.assertFalse(result.receipt.database_write_confirmed)

    def test_model_cannot_verify_checkpoint_time(self):
        hostile = TemporalEvidence(
            "EXACT",
            "MODEL",
            True,
            value=T0,
            reference_id="model-claim",
        )
        result = self.bus.entry_checkpoint(self.time, entry_time=hostile)
        self.assertEqual(result.receipt.result_class, "INVALID")


if __name__ == "__main__":
    unittest.main()
