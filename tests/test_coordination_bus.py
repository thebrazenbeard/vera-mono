from __future__ import annotations

import unittest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    InMemoryCoordinationRepository,
    INSERT_EVENT_SQL,
    PERMISSION_ACKNOWLEDGE,
    PERMISSION_POST,
    PERMISSION_READ_ANY,
    PERMISSION_READ_SELF,
    PERMISSION_RESOLVE,
    PERMISSION_REVIEW,
    PERMISSION_STATUS,
    READ_INBOX_SQL,
    RepositoryConflict,
)
from coordination_bus.supabase_sql import insert_params


class CoordinationBusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryCoordinationRepository()
        self.bus = CoordinationBus(self.repo)
        self.memory = ActorContext("workstream/memory", ALL_PERMISSIONS)
        self.time = ActorContext("workstream/time", ALL_PERMISSIONS)
        self.initiative = ActorContext("workstream/initiatives", ALL_PERMISSIONS)
        self.integration = ActorContext("workstream/integration", ALL_PERMISSIONS)

    def issue(self):
        return self.bus.coordination_post(
            self.memory,
            CoordinationEventDraft(
                thread_key="memory-temporal-contract-v1",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="ISSUE",
                status="READY_FOR_REVIEW",
                objective="Define temporal fields required by canonical memory records",
                summary="Memory requests the smallest storage-neutral temporal contract.",
                active_issue="Temporal fields are not yet finalized.",
                requested_perspective="Return event, state, record, and retrieval time semantics.",
            ),
        )

    def test_post_confirms_write_and_receipt(self):
        result = self.issue()
        self.assertTrue(result.receipt.database_write_confirmed)
        self.assertEqual(result.receipt.event_sequence, 1)
        self.assertEqual(len(result.receipt.result_hash), 64)

    def test_source_must_match_actor(self):
        result = self.bus.coordination_post(
            self.memory,
            CoordinationEventDraft(
                thread_key="x", source_branch="workstream/time",
                target_branch="workstream/memory", event_type="STATUS",
                status="IN_PROGRESS", objective="x", summary="x",
            ),
        )
        self.assertEqual(result.receipt.result_class, "DENIED")
        self.assertFalse(result.receipt.database_write_confirmed)

    def test_unknown_workstream_rejected(self):
        with self.assertRaises(ValueError):
            ActorContext("workstream/vera", ALL_PERMISSIONS).validate()

    def test_invalid_event_status_pair_rejected(self):
        with self.assertRaises(ValueError):
            CoordinationEventDraft(
                thread_key="x",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="ACKNOWLEDGEMENT",
                status="APPROVED",
                objective="x",
                summary="x",
                acknowledges_event_id="abc",
            ).validate()

    def test_issue_requires_active_issue(self):
        with self.assertRaises(ValueError):
            CoordinationEventDraft(
                thread_key="x",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="ISSUE",
                status="READY_FOR_REVIEW",
                objective="x",
                summary="x",
            ).validate()

    def test_read_self_permission(self):
        self.issue()
        actor = ActorContext("workstream/time", frozenset({PERMISSION_READ_SELF}))
        result = self.bus.coordination_read_inbox(actor)
        self.assertEqual([e.event_sequence for e in result.events], [1])
        self.assertFalse(result.receipt.database_write_confirmed)

    def test_read_other_inbox_requires_any_permission(self):
        actor = ActorContext("workstream/time", frozenset({PERMISSION_READ_SELF}))
        result = self.bus.coordination_read_inbox(
            actor, target_branch="workstream/memory"
        )
        self.assertEqual(result.receipt.result_class, "DENIED")

    def test_cross_inbox_read_with_any_permission(self):
        self.issue()
        actor = ActorContext("workstream/integration", frozenset({PERMISSION_READ_ANY}))
        result = self.bus.coordination_read_inbox(actor, target_branch="workstream/time")
        self.assertEqual(len(result.events), 1)

    def test_only_addressed_target_can_acknowledge(self):
        event = self.issue().events[0]
        result = self.bus.coordination_acknowledge(
            self.initiative, event_id=event.event_id, summary="Consumed."
        )
        self.assertEqual(result.receipt.result_class, "DENIED")

    def test_acknowledgement_hides_consumed_message_from_default_inbox(self):
        event = self.issue().events[0]
        ack = self.bus.coordination_acknowledge(
            self.time, event_id=event.event_id, summary="Temporal workstream consumed request."
        )
        self.assertEqual(ack.events[0].acknowledges_event_id, event.event_id)
        self.assertEqual(self.bus.coordination_read_inbox(self.time).events, ())
        full = self.bus.coordination_read_inbox(
            self.time, include_acknowledged=True
        )
        self.assertEqual(len(full.events), 1)

    def test_acknowledgement_requires_permission(self):
        event = self.issue().events[0]
        actor = ActorContext("workstream/time", frozenset({PERMISSION_READ_SELF}))
        result = self.bus.coordination_acknowledge(
            actor, event_id=event.event_id, summary="x"
        )
        self.assertEqual(result.receipt.result_class, "DENIED")

    def test_request_review_creates_ready_status(self):
        result = self.bus.coordination_request_review(
            self.initiative,
            thread_key="initiative-time-review-v1",
            target_branch="workstream/time",
            objective="Review temporal fields used by initiative receipts",
            summary="Initiative kernel requests temporal contract review.",
            requested_perspective="Check event, record, and decision time distinctions.",
        )
        self.assertEqual(result.events[0].event_type, "STATUS")
        self.assertEqual(result.events[0].status, "READY_FOR_REVIEW")

    def test_resolve_thread_requires_participant(self):
        event = self.issue().events[0]
        result = self.bus.coordination_resolve_thread(
            self.integration, acknowledges_event_id=event.event_id,
            summary="Resolved.",
        )
        self.assertEqual(result.receipt.result_class, "DENIED")

    def test_resolution_links_original(self):
        event = self.issue().events[0]
        result = self.bus.coordination_resolve_thread(
            self.time,
            acknowledges_event_id=event.event_id,
            summary="Temporal contract returned.",
        )
        self.assertEqual(result.events[0].event_type, "RESOLUTION")
        self.assertEqual(result.events[0].status, "RESOLVED")
        self.assertEqual(result.events[0].acknowledges_event_id, event.event_id)

    def test_supersession_stays_in_thread(self):
        first = self.bus.coordination_publish_status(
            self.memory,
            thread_key="memory-build-v1",
            target_branch="workstream/integration",
            status="IN_PROGRESS",
            objective="Build memory system",
            summary="Initial status.",
        ).events[0]
        result = self.bus.coordination_publish_status(
            self.memory, thread_key="different-thread",
            target_branch="workstream/integration", status="IN_PROGRESS",
            objective="Build memory system", summary="Wrong thread.",
            supersedes_event_id=first.event_id,
        )
        self.assertEqual(result.receipt.result_class, "CONFLICT")

    def test_one_successor_per_superseded_event(self):
        first = self.bus.coordination_publish_status(
            self.memory,
            thread_key="memory-build-v1",
            target_branch="workstream/integration",
            status="IN_PROGRESS",
            objective="Build memory system",
            summary="Initial status.",
        ).events[0]
        self.bus.coordination_publish_status(
            self.memory,
            thread_key="memory-build-v1",
            target_branch="workstream/integration",
            status="READY_FOR_REVIEW",
            objective="Build memory system",
            summary="Review status.",
            supersedes_event_id=first.event_id,
        )
        result = self.bus.coordination_publish_status(
            self.memory, thread_key="memory-build-v1",
            target_branch="workstream/integration", status="BLOCKED",
            objective="Build memory system", summary="Competing successor.",
            supersedes_event_id=first.event_id,
        )
        self.assertEqual(result.receipt.result_class, "CONFLICT")

    def test_entry_checkpoint_reads_without_acknowledging(self):
        self.issue()
        result = self.bus.entry_checkpoint(self.time)
        self.assertEqual(result.receipt.operation, "coordination_entry_checkpoint")
        self.assertEqual(len(result.events), 1)
        self.assertEqual(len(self.bus.entry_checkpoint(self.time).events), 1)

    def test_non_material_exit_writes_nothing(self):
        result = self.bus.exit_checkpoint(
            self.initiative,
            thread_key="initiative-kernel",
            target_branch="workstream/integration",
            objective="Build initiative kernel",
            summary="No material state change.",
            material=False,
        )
        self.assertFalse(result.receipt.database_write_confirmed)
        self.assertEqual(self.repo.list_thread("initiative-kernel"), ())

    def test_material_exit_writes_status(self):
        result = self.bus.exit_checkpoint(
            self.initiative,
            thread_key="initiative-kernel",
            target_branch="workstream/integration",
            objective="Build initiative kernel",
            summary="Implementation ready for integration review.",
            material=True,
            status="READY_FOR_REVIEW",
        )
        self.assertTrue(result.receipt.database_write_confirmed)
        self.assertEqual(result.receipt.operation, "coordination_exit_checkpoint")

    def test_receipts_are_deterministic_for_same_read_state(self):
        self.issue()
        first = self.bus.coordination_read_inbox(self.time)
        second = self.bus.coordination_read_inbox(self.time)
        self.assertEqual(first.receipt.result_hash, second.receipt.result_hash)

    def test_sql_insert_omits_generated_fields(self):
        lower = INSERT_EVENT_SQL.lower()
        insert_columns = lower.split("(", 1)[1].split(") values", 1)[0]
        columns = {item.strip() for item in insert_columns.replace("\n", " ").split(",")}
        self.assertNotIn("event_sequence", columns)
        self.assertNotIn("record_time", columns)
        self.assertNotIn("event_id", columns)
        self.assertIn("returning", lower)

    def test_sql_inbox_uses_explicit_acknowledgement_filter(self):
        self.assertIn("response.acknowledges_event_id = event.event_id", READ_INBOX_SQL)
        self.assertIn("response.source_branch = %(target_branch)s", READ_INBOX_SQL)

    def test_sql_params_are_canonical_json(self):
        params = insert_params(
            CoordinationEventDraft(
                thread_key="x",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="STATUS",
                status="IN_PROGRESS",
                objective="x",
                summary="x",
                payload={"z": 1, "a": 2},
            )
        )
        self.assertEqual(params["payload"], '{"a":2,"z":1}')

    def test_generic_post_cannot_bypass_acknowledgement_permission(self):
        original = self.issue().events[0]
        actor = ActorContext(
            "workstream/time", frozenset({"coordination:post"})
        )
        result_draft = CoordinationEventDraft(
            thread_key=original.thread_key,
            source_branch="workstream/time",
            target_branch="workstream/memory",
            event_type="ACKNOWLEDGEMENT",
            status="ACKNOWLEDGED",
            objective=original.objective,
            summary="Attempted acknowledgement through generic post.",
            acknowledges_event_id=original.event_id,
        )
        result = self.bus.coordination_post(actor, result_draft)
        self.assertEqual(result.receipt.result_class, "DENIED")

    def test_generic_review_requires_addressed_target(self):
        original = self.issue().events[0]
        review = CoordinationEventDraft(
            thread_key=original.thread_key,
            source_branch="workstream/integration",
            target_branch="workstream/memory",
            event_type="REVIEW",
            status="APPROVED",
            objective=original.objective,
            summary="Unauthorized review.",
            acknowledges_event_id=original.event_id,
        )
        result = self.bus.coordination_post(self.integration, review)
        self.assertEqual(result.receipt.result_class, "DENIED")

    def test_entry_checkpoint_hash_covers_all_returned_events(self):
        self.issue()
        first = self.bus.entry_checkpoint(self.time)
        self.bus.coordination_post(
            self.memory,
            CoordinationEventDraft(
                thread_key="second-thread",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="STATUS",
                status="IN_PROGRESS",
                objective="Second objective",
                summary="Second inbox event.",
            ),
        )
        second = self.bus.entry_checkpoint(self.time)
        self.assertNotEqual(first.receipt.result_hash, second.receipt.result_hash)
        self.assertEqual(len(second.events), 2)

    def test_failure_receipt_is_deterministic(self):
        actor = ActorContext("workstream/time", frozenset({PERMISSION_READ_SELF}))
        first = self.bus.coordination_read_inbox(
            actor, target_branch="workstream/memory"
        )
        second = self.bus.coordination_read_inbox(
            actor, target_branch="workstream/memory"
        )
        self.assertEqual(first.receipt.result_class, "DENIED")
        self.assertEqual(first.receipt.result_hash, second.receipt.result_hash)
        self.assertIsNotNone(first.receipt.error)


if __name__ == "__main__":
    unittest.main()
