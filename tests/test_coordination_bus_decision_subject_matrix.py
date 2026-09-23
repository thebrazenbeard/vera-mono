from __future__ import annotations

from dataclasses import replace
import unittest

from coordination_bus import (
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    HmacDecisionAuthority,
    InMemoryCoordinationRepository,
)


class DecisionSubjectBindingMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = ActorContext("workstream/project-architecture", frozenset())
        self.authority = HmacDecisionAuthority("project-owner", b"m" * 32)
        self.draft = CoordinationEventDraft(
            thread_key="decision-subject-matrix-v1",
            source_branch=self.actor.canonical_workstream,
            target_branch="workstream/integration",
            event_type="DECISION",
            status="APPROVED",
            objective="Bind every meaning-bearing decision field",
            summary="The exact draft requires external authority.",
            payload={"merge_authorized": False, "scope": ["source-only"]},
            reference_data={"pull_request": 8, "head": "abc123"},
        )

    def envelope(self):
        return self.authority.issue(
            actor_workstream=self.actor.canonical_workstream,
            draft=self.draft,
        )

    def bus(self):
        return CoordinationBus(
            InMemoryCoordinationRepository(),
            decision_authority_verifier=self.authority,
        )

    def test_mutating_any_meaning_bearing_field_invalidates_authority(self):
        mutations = {
            "thread_key": replace(self.draft, thread_key="other-thread"),
            "target_branch": replace(
                self.draft, target_branch="workstream/time"
            ),
            "status": replace(self.draft, status="CANCELLED"),
            "objective": replace(self.draft, objective="Changed objective"),
            "summary": replace(self.draft, summary="Changed summary"),
            "active_issue": replace(self.draft, active_issue="issue-99"),
            "requested_perspective": replace(
                self.draft, requested_perspective="Changed perspective"
            ),
            "acknowledges_event_id": replace(
                self.draft,
                acknowledges_event_id="00000000-0000-0000-0000-000000000001",
            ),
            "supersedes_event_id": replace(
                self.draft,
                supersedes_event_id="00000000-0000-0000-0000-000000000002",
            ),
            "payload": replace(
                self.draft, payload={"merge_authorized": True}
            ),
            "reference_data": replace(
                self.draft, reference_data={"pull_request": 17}
            ),
        }
        for field, altered in mutations.items():
            with self.subTest(field=field):
                result = self.bus().coordination_post(
                    self.actor,
                    altered,
                    decision_authority=self.envelope(),
                )
                self.assertEqual(result.receipt.result_class, "DENIED")
                self.assertFalse(result.receipt.database_write_confirmed)

    def test_authority_is_bound_to_source_actor(self):
        envelope = self.envelope()
        other_actor = ActorContext("workstream/integration", frozenset())
        altered = replace(
            self.draft,
            source_branch=other_actor.canonical_workstream,
        )
        result = self.bus().coordination_post(
            other_actor,
            altered,
            decision_authority=envelope,
        )
        self.assertEqual(result.receipt.result_class, "DENIED")
        self.assertFalse(result.receipt.database_write_confirmed)


if __name__ == "__main__":
    unittest.main()
