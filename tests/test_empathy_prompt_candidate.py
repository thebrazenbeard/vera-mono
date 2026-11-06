"""Source-only contract tests; the external Empathy donor is NOT bundled.

An actual-donor cross-repo test must run separately with the exact donor
checkout (documented in the accompanying Draft PR).
"""
import json
from dataclasses import replace
from types import SimpleNamespace
import unittest

from vera_core.empathy_prompt_candidate import (
    EmpathyPromptBoundaryError,
    HostReportedEmpathySource,
    build_empathy_prompt_candidate,
)


SOURCE = HostReportedEmpathySource(
    "thebrazenbeard/empathy",
    "a115c675622662d1a7d58f58dbdb0eb9003d61b4",
    "empathy_research/cognitive_donor_probe.py",
)


def assessment(task="write a poem about moonlight", *, person="SYNTHETIC_A",
               kind="task_request", referent="task", value=None):
    evidence = SimpleNamespace(
        kind=kind, referent=referent, value=task if value is None else value,
        confidence=0.95, source="current", scope_person_id=person,
        active=True, evidence_id="ev_" + "b" * 32,
    )
    return SimpleNamespace(
        person_id=person, current_evidence=(evidence,),
        historical_evidence=(), hypotheses=(), stakes="low",
    )


def stub_policy(policy="TASK_DIRECT", reason="EXPLICIT_TASK"):
    return SimpleNamespace(
        donor="empathy", provenance="CALLER_SUPPLIED_CURRENT_EVIDENCE_UNVERIFIED",
        evaluation="CANONICAL_EMPATHY_RESPONSE_POLICY_HINT_EXECUTED",
        supporting_evidence_ids=("ev_" + "b" * 32,),
        policy=policy, reason_code=reason, authority="NONE",
        memory_admission="NONE", effect_authority=False,
        model_identity="UNQUALIFIED",
        source_proof="SOURCE_ONLY_NOT_HOST_ATTESTED",
    )


class CandidateContractTests(unittest.TestCase):
    def call(self, evaluator, *, subject=None, **kwargs):
        return build_empathy_prompt_candidate(
            "write a poem about moonlight", enabled=True,
            host_admitted_assessment=subject if subject is not None else assessment(),
            empathy_evaluator=evaluator,
            host_reported_source=SOURCE, **kwargs,
        )

    def test_default_disabled_is_opaque_no_callback(self):
        def bomb(_): raise AssertionError("must remain uncalled")
        value = build_empathy_prompt_candidate("task", empathy_evaluator=bomb)
        self.assertEqual((value.status, value.prompt_data), ("DISABLED", ""))

    def test_injected_stub_only_proves_contract(self):
        value = self.call(lambda _: stub_policy())
        data = json.loads(value.prompt_data)
        self.assertEqual(data["advisory_policy"], "TASK_DIRECT")
        self.assertEqual(data["provenance"], "CALLER_REPORTED_UNVERIFIED")
        self.assertEqual(value.status, "CANDIDATE_PROMPT_DATA_NOT_EXECUTED")
        self.assertFalse(value.model_generated or value.effect_authority)

    def test_stop_is_advice_not_effect_authority(self):
        value = self.call(
            lambda _: stub_policy("STOP_PLAY", "DIRECT_PLAY_STOP"),
            subject=assessment(kind="direct_correction", referent="play_frame", value="stop"),
        )
        self.assertEqual(value.status, "UNBOUND_POLICY_HOLD")
        self.assertEqual(value.prompt_data, "")
        self.assertEqual(value.authority, "NONE")

    def test_forced_effect_claim_is_rejected(self):
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "effectless"):
            self.call(lambda _: SimpleNamespace(
                **{**stub_policy().__dict__, "effect_authority": True}
            ))

    def test_wrong_repository_subject_is_rejected_before_evaluator(self):
        def bomb(_): raise AssertionError("source must reject first")
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "unexpected source"):
            build_empathy_prompt_candidate(
                "task", enabled=True,
                host_admitted_assessment=assessment("task"),
                empathy_evaluator=bomb,
                host_reported_source=replace(SOURCE, repository="someone/not-empathy"),
            )

    def test_no_admission_rejected_before_evaluator(self):
        def bomb(_): raise AssertionError("must remain uncalled")
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "host supplied"):
            build_empathy_prompt_candidate(
                "task", enabled=True, empathy_evaluator=bomb,
                host_reported_source=SOURCE,
            )

    def test_control_character_rejected(self):
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "bounded task"):
            build_empathy_prompt_candidate(
                "task\x00", enabled=True,
                host_admitted_assessment=assessment("task"),
                empathy_evaluator=lambda _: stub_policy(),
                host_reported_source=SOURCE,
            )

    def test_nonboolean_enable_rejected(self):
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "literal bool"):
            build_empathy_prompt_candidate("task", enabled=1)

    def test_different_task_does_not_inherit_person_a_stop(self):
        value = build_empathy_prompt_candidate(
            "write a poem for person_B", enabled=True,
            host_admitted_assessment=assessment(
                "stop play", person="person_A", kind="direct_correction",
                referent="play_frame", value="stop",
            ),
            empathy_evaluator=lambda _: stub_policy("STOP_PLAY", "DIRECT_PLAY_STOP"),
            host_reported_source=SOURCE,
        )
        self.assertEqual(value.status, "UNBOUND_POLICY_HOLD")
        self.assertEqual(value.prompt_data, "")

    def test_same_task_different_evidence_has_different_input_hash(self):
        a = self.call(lambda _: stub_policy())
        b = self.call(
            lambda _: stub_policy("STOP_PLAY", "DIRECT_PLAY_STOP"),
            subject=assessment(kind="direct_correction", referent="play_frame", value="stop"),
        )
        self.assertNotEqual(a.input_sha256, b.input_sha256)

    def test_mismatched_task_request_is_withheld(self):
        value = self.call(
            lambda _: stub_policy(),
            subject=assessment("draft a budget"),
        )
        self.assertEqual(value.status, "UNBOUND_POLICY_HOLD")
        self.assertEqual(value.prompt_data, "")

    def test_wrong_donor_or_provenance_rejected(self):
        for override in (
            {"donor": "not_empathy"},
            {"provenance": "HISTORICAL_ONLY"},
            {"supporting_evidence_ids": ()},
        ):
            with self.subTest(override=override), self.assertRaises(EmpathyPromptBoundaryError):
                def liar(_):
                    return SimpleNamespace(**{**stub_policy().__dict__, **override})
                self.call(liar)

    def test_zero_source_commit_rejected(self):
        with self.assertRaises(EmpathyPromptBoundaryError):
            build_empathy_prompt_candidate(
                "write a poem about moonlight", enabled=True,
                host_admitted_assessment=assessment(),
                empathy_evaluator=lambda _: stub_policy(),
                host_reported_source=replace(SOURCE, commit_sha="0" * 40),
            )

    def test_fake_task_direct_cannot_override_current_stop(self):
        current_task = assessment()
        stop = SimpleNamespace(
            kind="direct_correction", referent="play_frame", value="stop",
            confidence=0.95, source="current", scope_person_id="SYNTHETIC_A",
            active=True, evidence_id="ev_" + "c" * 32,
        )
        mixed = SimpleNamespace(
            **{**current_task.__dict__,
               "current_evidence": current_task.current_evidence + (stop,)}
        )
        outcome = self.call(lambda _: stub_policy(), subject=mixed)
        self.assertEqual(outcome.status, "UNBOUND_POLICY_HOLD")
        self.assertEqual(outcome.prompt_data, "")

    def test_forged_task_direct_cannot_override_current_task_correction(self):
        current = assessment()
        correction = SimpleNamespace(
            kind="direct_correction", referent="task", value="cancel",
            confidence=0.95, source="current", scope_person_id="SYNTHETIC_A",
            active=True, evidence_id="ev_" + "c" * 32,
        )
        mixed = SimpleNamespace(
            **{**current.__dict__,
               "current_evidence": current.current_evidence + (correction,)}
        )
        outcome = self.call(lambda _: stub_policy(), subject=mixed)
        self.assertEqual(outcome.status, "UNBOUND_POLICY_HOLD")
        self.assertEqual(outcome.prompt_data, "")

    def test_forged_task_direct_cannot_ignore_other_policy_evidence(self):
        current = assessment()
        contradiction = SimpleNamespace(
            kind="unsupported_claim", referent="external_fact", value="false",
            confidence=0.95, source="current", scope_person_id="SYNTHETIC_A",
            active=True, evidence_id="ev_" + "c" * 32,
        )
        mixed = SimpleNamespace(
            **{**current.__dict__,
               "current_evidence": current.current_evidence + (contradiction,)}
        )
        outcome = self.call(lambda _: stub_policy(), subject=mixed)
        self.assertEqual(outcome.status, "UNBOUND_POLICY_HOLD")
        self.assertEqual(outcome.prompt_data, "")

    def test_fake_task_direct_stop_reason_is_rejected(self):
        with self.assertRaises(EmpathyPromptBoundaryError):
            self.call(lambda _: stub_policy("TASK_DIRECT", "DIRECT_PLAY_STOP"))

    def test_selected_support_ids_must_change_causal_digest(self):
        first = assessment()
        second = SimpleNamespace(
            kind="task_request", referent="task", value="write a poem about moonlight",
            confidence=0.95, source="current", scope_person_id="SYNTHETIC_A",
            active=True, evidence_id="ev_" + "c" * 32,
        )
        mixed = SimpleNamespace(
            **{**first.__dict__,
               "current_evidence": first.current_evidence + (second,)}
        )
        one = self.call(lambda _: stub_policy(), subject=mixed)
        def two(_):
            return SimpleNamespace(**{
                **stub_policy().__dict__,
                "supporting_evidence_ids": ("ev_" + "b" * 32, "ev_" + "c" * 32),
            })
        both = self.call(two, subject=mixed)
        self.assertNotEqual(one.input_sha256, both.input_sha256)


if __name__ == "__main__":
    unittest.main()
