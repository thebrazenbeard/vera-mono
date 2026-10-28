"""Source-only fail-closed regression cases for external assignment views."""

import unittest

from vera_core.external_assignment_currentness import (
    ExternalAssignmentEvent,
    ExternalAssignmentObservation,
    ExternalSourceCompletenessClaim,
    assess_external_assignment_currentness,
)


class ExternalAssignmentCurrentnessTests(unittest.TestCase):
    def _observation(self, *events):
        return ExternalAssignmentObservation(
            assignment_ref="external:assignment-123",
            events=events,
            authority_binding_claim="VALID",
        )

    def _assert_fail_closed(self, assessment):
        self.assertEqual(assessment.assignment_state, "UNRESOLVED")
        self.assertIsNone(assessment.owner)
        self.assertEqual(assessment.blocking_state, "UNRESOLVED")
        self.assertEqual(assessment.workload_capacity, "UNRESOLVED")
        self.assertFalse(assessment.effect_eligible)
        self.assertFalse(assessment.source_completeness_qualified)

    def test_cur19_apparent_successor_with_incomplete_source_remains_unresolved(self):
        observation = self._observation(
            ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),
            ExternalAssignmentEvent("next", "REROUTE", predecessor="root", owner="alice"),
        )
        completeness = ExternalSourceCompletenessClaim(
            source_ref="external-feed:A",
            status="INCOMPLETE",
            evidence_refs=("page:visible-subset",),
        )
        result = assess_external_assignment_currentness(observation, completeness)
        self._assert_fail_closed(result)
        self.assertEqual(result.reason, "SOURCE_COMPLETENESS_NOT_ESTABLISHED")

    def test_cur20_terminal_complete_does_not_override_incomplete_source(self):
        observation = self._observation(
            ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),
            ExternalAssignmentEvent("done", "COMPLETE", predecessor="root", owner="bob"),
        )
        result = assess_external_assignment_currentness(
            observation,
            ExternalSourceCompletenessClaim("external-feed:A", "INCOMPLETE"),
        )
        self._assert_fail_closed(result)

    def test_caller_claim_of_complete_source_does_not_qualify_authority(self):
        observation = self._observation(
            ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),
            ExternalAssignmentEvent("next", "REROUTE", predecessor="root", owner="alice"),
        )
        result = assess_external_assignment_currentness(
            observation,
            ExternalSourceCompletenessClaim(
                source_ref="external-feed:A",
                status="COMPLETE",
                evidence_refs=("self-report:complete",),
            ),
        )
        self._assert_fail_closed(result)
        self.assertEqual(result.reason, "INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE")

    def test_missing_completeness_and_empty_observation_fail_closed(self):
        result = assess_external_assignment_currentness(self._observation())
        self._assert_fail_closed(result)
        self.assertEqual(result.reason, "SOURCE_COMPLETENESS_NOT_ESTABLISHED")

    def test_authority_claim_does_not_override_missing_source_proof(self):
        observation = ExternalAssignmentObservation(
            assignment_ref="external:assignment-123",
            events=(ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),),
            authority_binding_claim="VALID",
        )
        result = assess_external_assignment_currentness(observation)
        self._assert_fail_closed(result)

    def test_conflicting_successors_cannot_establish_owner_even_if_claimed_complete(self):
        observation = self._observation(
            ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),
            ExternalAssignmentEvent("a", "REROUTE", predecessor="root", owner="alice"),
            ExternalAssignmentEvent("b", "REROUTE", predecessor="root", owner="eve"),
        )
        result = assess_external_assignment_currentness(
            observation,
            ExternalSourceCompletenessClaim("feed:untrusted", "COMPLETE"),
        )
        self._assert_fail_closed(result)
        self.assertEqual(result.reason, "INDEPENDENT_SOURCE_QUALIFICATION_UNAVAILABLE")

    def test_privacy_filtered_visible_subset_is_not_a_controlling_graph(self):
        observation = self._observation(
            ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),
            ExternalAssignmentEvent("visible", "COMPLETE", predecessor="root", owner="bob"),
        )
        result = assess_external_assignment_currentness(
            observation,
            ExternalSourceCompletenessClaim(
                "feed:privacy-projection",
                "INCOMPLETE",
                evidence_refs=("privacy-filtered:only-visible-events",),
            ),
        )
        self._assert_fail_closed(result)
        self.assertEqual(result.reason, "SOURCE_COMPLETENESS_NOT_ESTABLISHED")

    def test_unadmitted_newer_looking_event_cannot_grant_currentness(self):
        observation = self._observation(
            ExternalAssignmentEvent("root", "ASSIGN", owner="bob"),
            ExternalAssignmentEvent(
                "sequence-999999",
                "REROUTE",
                predecessor="root",
                owner="mallory",
                admitted=False,
            ),
        )
        result = assess_external_assignment_currentness(
            observation,
            ExternalSourceCompletenessClaim("feed:untrusted", "COMPLETE"),
        )
        self._assert_fail_closed(result)


if __name__ == "__main__":
    unittest.main()
