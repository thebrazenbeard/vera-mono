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


T0 = "2026-07-30T22:40:00+00:00"
T1 = "2026-07-30T22:40:01+00:00"


def exact(value: str, label: str) -> TemporalEvidence:
    return TemporalEvidence.exact(
        value,
        source="HOST_CLOCK",
        reference_id=f"clock:{label}:{value}",
    )


class TemporalEvidenceTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryCoordinationRepository()
        self.authority = HmacTemporalEvidenceAuthority(
            "test-host-clock", b"v" * 32
        )
        self.bus = CoordinationBus(
            self.repo,
            evidence_verifier=self.authority,
            receipt_time_provider=lambda role, subject: self.authority.issue(
                exact(T1, "receipt"), role=role, subject=subject
            ),
        )
        self.memory = ActorContext("workstream/memory", ALL_PERMISSIONS)
        self.time = ActorContext("workstream/time", ALL_PERMISSIONS)
        self.integration = ActorContext(
            "workstream/integration", ALL_PERMISSIONS
        )

    def post_to_time(self):
        return self.bus.coordination_post(
            self.memory,
            CoordinationEventDraft(
                thread_key="trust-boundary",
                source_branch="workstream/memory",
                target_branch="workstream/time",
                event_type="STATUS",
                status="IN_PROGRESS",
                objective="Test temporal trust boundary",
                summary="Bounded test event.",
            ),
        ).events[0]

    def test_raw_self_certified_host_time_is_rejected(self):
        result = self.bus.entry_checkpoint(
            self.time,
            entry_time=exact(T0, "forged-raw"),
        )
        self.assertEqual(result.receipt.result_class, "INVALID")
        self.assertIn("verifier-issued", result.receipt.error)

    def test_valid_role_and_subject_bound_envelope_is_accepted(self):
        subject = entry_checkpoint_subject("workstream/time", 0, 100)
        envelope = self.authority.issue(
            exact(T0, "entry"),
            role="entry_time",
            subject=subject,
        )
        result = self.bus.entry_checkpoint(
            self.time,
            entry_time=envelope,
        )
        self.assertEqual(result.receipt.result_class, "COMPLETE")
        self.assertEqual(result.receipt.entry_time.value, T0)

    def test_forged_token_is_rejected(self):
        subject = entry_checkpoint_subject("workstream/time", 0, 100)
        envelope = self.authority.issue(
            exact(T0, "entry"),
            role="entry_time",
            subject=subject,
        )
        forged = replace(envelope, verification_token="0" * 64)
        result = self.bus.entry_checkpoint(
            self.time,
            entry_time=forged,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")

    def test_wrong_role_binding_is_rejected(self):
        subject = entry_checkpoint_subject("workstream/time", 0, 100)
        envelope = self.authority.issue(
            exact(T0, "wrong-role"),
            role="state_time",
            subject=subject,
        )
        result = self.bus.entry_checkpoint(
            self.time,
            entry_time=envelope,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")

    def test_wrong_subject_binding_is_rejected(self):
        envelope = self.authority.issue(
            exact(T0, "wrong-subject"),
            role="entry_time",
            subject=entry_checkpoint_subject("workstream/memory", 0, 100),
        )
        result = self.bus.entry_checkpoint(
            self.time,
            entry_time=envelope,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")

    def test_entry_evidence_cannot_replay_across_cursor(self):
        envelope = self.authority.issue(
            exact(T0, "cursor-bound"),
            role="entry_time",
            subject=entry_checkpoint_subject("workstream/time", 0, 100),
        )
        result = self.bus.entry_checkpoint(
            self.time,
            after_sequence=10,
            limit=100,
            entry_time=envelope,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")

    def test_modified_claim_invalidates_token(self):
        subject = entry_checkpoint_subject("workstream/time", 0, 100)
        envelope = self.authority.issue(
            exact(T0, "entry"),
            role="entry_time",
            subject=subject,
        )
        modified = replace(
            envelope,
            evidence=exact(T1, "modified-after-issuance"),
        )
        result = self.bus.entry_checkpoint(
            self.time,
            entry_time=modified,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")

    def test_unregistered_issuer_is_rejected(self):
        other = HmacTemporalEvidenceAuthority(
            "unregistered-clock", b"x" * 32
        )
        envelope = other.issue(
            exact(T0, "unregistered"),
            role="entry_time",
            subject=entry_checkpoint_subject("workstream/time", 0, 100),
        )
        result = self.bus.entry_checkpoint(self.time, entry_time=envelope)
        self.assertEqual(result.receipt.result_class, "INVALID")

    def test_acknowledgement_evidence_is_bound_to_complete_operation(self):
        event = self.post_to_time()
        summary = "Acknowledged."
        payload = {"review": "started"}
        reference_data = {"source_sequence": event.event_sequence}
        envelope = self.authority.issue(
            exact(T0, "ack"),
            role="acknowledgement_time",
            subject=acknowledgement_subject(
                event.event_id,
                actor_workstream=self.time.workstream,
                thread_key=event.thread_key,
                summary=summary,
                payload=payload,
                reference_data=reference_data,
            ),
        )
        result = self.bus.coordination_acknowledge(
            self.time,
            event_id=event.event_id,
            summary=summary,
            acknowledgement_time=envelope,
            payload=payload,
            reference_data=reference_data,
        )
        self.assertEqual(result.receipt.result_class, "COMPLETE")
        self.assertEqual(
            result.events[0].payload["temporal"]["consumption_time"]["precision"],
            "UNKNOWN",
        )

    def test_acknowledgement_evidence_cannot_replay_with_changed_summary(self):
        event = self.post_to_time()
        envelope = self.authority.issue(
            exact(T0, "ack-summary"),
            role="acknowledgement_time",
            subject=acknowledgement_subject(
                event.event_id,
                actor_workstream=self.time.workstream,
                thread_key=event.thread_key,
                summary="Original summary.",
            ),
        )
        result = self.bus.coordination_acknowledge(
            self.time,
            event_id=event.event_id,
            summary="Changed summary.",
            acknowledgement_time=envelope,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")
        self.assertFalse(result.receipt.database_write_confirmed)

    def test_acknowledgement_evidence_cannot_replay_with_changed_payload(self):
        event = self.post_to_time()
        envelope = self.authority.issue(
            exact(T0, "ack-payload"),
            role="acknowledgement_time",
            subject=acknowledgement_subject(
                event.event_id,
                actor_workstream=self.time.workstream,
                thread_key=event.thread_key,
                summary="Acknowledged.",
                payload={"stage": 1},
            ),
        )
        result = self.bus.coordination_acknowledge(
            self.time,
            event_id=event.event_id,
            summary="Acknowledged.",
            acknowledgement_time=envelope,
            payload={"stage": 2},
        )
        self.assertEqual(result.receipt.result_class, "INVALID")
        self.assertFalse(result.receipt.database_write_confirmed)

    def test_exit_evidence_is_bound_to_complete_transition(self):
        objective = "Publish handoff"
        summary = "Handoff ready."
        status = "READY_FOR_REVIEW"
        subject = exit_checkpoint_subject(
            "workstream/integration",
            "handoff",
            "workstream/time",
            objective=objective,
            summary=summary,
            material=True,
            status=status,
        )
        event_envelope = self.authority.issue(
            exact(T0, "exit-event"),
            role="event_time",
            subject=subject,
        )
        state_envelope = self.authority.issue(
            exact(T1, "exit-state"),
            role="state_time",
            subject=subject,
        )
        result = self.bus.exit_checkpoint(
            self.integration,
            thread_key="handoff",
            target_branch="workstream/time",
            objective=objective,
            summary=summary,
            material=True,
            status=status,
            event_time=event_envelope,
            state_time=state_envelope,
        )
        self.assertEqual(result.receipt.result_class, "COMPLETE")
        self.assertEqual(
            result.events[0].payload["temporal"]["event_time"]["value"], T0
        )

    def test_exit_evidence_cannot_replay_with_changed_objective(self):
        subject = exit_checkpoint_subject(
            "workstream/integration",
            "handoff",
            "workstream/time",
            objective="Original objective",
            summary="Handoff ready.",
            material=True,
            status="READY_FOR_REVIEW",
        )
        envelope = self.authority.issue(
            exact(T0, "exit-replay"),
            role="event_time",
            subject=subject,
        )
        result = self.bus.exit_checkpoint(
            self.integration,
            thread_key="handoff",
            target_branch="workstream/time",
            objective="Changed objective",
            summary="Handoff ready.",
            material=True,
            status="READY_FOR_REVIEW",
            event_time=envelope,
        )
        self.assertEqual(result.receipt.result_class, "INVALID")
        self.assertFalse(result.receipt.database_write_confirmed)

    def test_unverified_receipt_provider_fails_closed_to_unknown(self):
        bus = CoordinationBus(
            self.repo,
            evidence_verifier=self.authority,
            receipt_time_provider=lambda role, subject: exact(T1, "raw-receipt"),
        )
        result = bus.entry_checkpoint(self.time)
        self.assertEqual(
            result.receipt.receipt_time.precision,
            "UNKNOWN",
        )
        self.assertEqual(
            result.receipt.receipt_time.source,
            "UNVERIFIED_RECEIPT_TIME_REJECTED",
        )


if __name__ == "__main__":
    unittest.main()
