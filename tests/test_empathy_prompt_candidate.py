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


def stub_policy(policy="TASK_DIRECT", reason="EXPLICIT_TASK"):
    return SimpleNamespace(
        policy=policy, reason_code=reason, authority="NONE",
        memory_admission="NONE", effect_authority=False,
        model_identity="UNQUALIFIED",
        source_proof="SOURCE_ONLY_NOT_HOST_ATTESTED",
    )


class CandidateContractTests(unittest.TestCase):
    def call(self, evaluator, **kwargs):
        return build_empathy_prompt_candidate(
            "write a poem about moonlight", enabled=True,
            host_admitted_assessment=object(), empathy_evaluator=evaluator,
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
        value = self.call(lambda _: stub_policy("STOP_PLAY", "DIRECT_PLAY_STOP"))
        self.assertEqual(json.loads(value.prompt_data)["advisory_policy"], "STOP_PLAY")
        self.assertEqual(value.authority, "NONE")

    def test_forced_effect_claim_is_rejected(self):
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "effectless"):
            self.call(lambda _: SimpleNamespace(
                **{**stub_policy().__dict__, "effect_authority": True}
            ))

    def test_fake_repository_is_rejected_before_evaluator(self):
        def bomb(_): raise AssertionError("source must reject first")
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "unexpected source"):
            build_empathy_prompt_candidate(
                "task", enabled=True,
                host_admitted_assessment=object(),
                empathy_evaluator=bomb,
                host_reported_source=replace(SOURCE, repository="someone/empathy"),
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
                host_admitted_assessment=object(),
                empathy_evaluator=lambda _: stub_policy(),
                host_reported_source=SOURCE,
            )

    def test_nonboolean_enable_rejected(self):
        with self.assertRaisesRegex(EmpathyPromptBoundaryError, "literal bool"):
            build_empathy_prompt_candidate("task", enabled=1)


if __name__ == "__main__":
    unittest.main()
