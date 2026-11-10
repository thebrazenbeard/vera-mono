"""Source-only coalition interop and adversarial perturbation tests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import unittest

from tools.mini_vera import compose
from tools.mini_vera.coalition_projection import (
    CoalitionProjectionRejected, project_response_coalition,
)


EV = "ev_" + "a" * 32


def hc_coalition():
    return {
        "coalition_id": "hc:17", "purpose": "interpret:turn",
        "active_members": ["semantics", "integration-arbitration", "current memory storage"],
        "created_cycle": 3, "expires_after_cycle": 6, "status": "ACTIVE",
    }


def hc_record(text="Owner reports the project name is Driftspace."):
    return {
        "record_id": "context:17", "kind": "PUBLIC_MEMORY", "claim_key": "project-name",
        "text": text, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_refs": ["public-event:17"], "projection_status": "CURRENT",
        "epistemic_class": "OBSERVATION", "privacy": "PUBLIC", "salience": 0.5,
        "expires_after_cycle": 6, "authority_ref": None, "requested_effect": "NONE",
    }


@dataclass(frozen=True)
class CompatibleEmpathyHint:
    policy: str = "STOP_PLAY"
    reason_code: str = "DIRECT_CORRECTION"
    confidence_band: str = "HIGH_SCORE"
    supporting_evidence_ids: tuple[str, ...] = (EV,)
    superseded_hypothesis_ids: tuple[str, ...] = ()
    focus_needed: bool = False
    schema: str = "EMPATHY_RESPONSE_POLICY_HINT_V1"
    consumer: str = "RESPONSE_POLICY_ONLY"
    authority: str = "NONE"
    persistence: str = "EPHEMERAL"
    volition_want_authority: bool = False
    effect_authority: bool = False


@dataclass(frozen=True)
class CompatibleSocialPlan:
    actor_id: str = "vera"
    subject_id: str = "patrick"
    answer_target: str = "Stop teasing me about that."
    answer_literal_request_first: bool = True
    terminology_suggestion: str | None = None
    register: str = "CONVERSATIONAL"
    humor_allowed: bool = True
    classified_claims: tuple = ()
    permission_to_act: bool = False


class CoalitionInteropTests(unittest.TestCase):
    def run_projection(self, **kwargs):
        args = {
            "coalition": hc_coalition(), "proposals": [hc_record()],
            "current_cycle": 4, "actor_id": "vera", "subject_id": "patrick",
            "turn_id": "turn:9", "literal_request": "Stop teasing me about that.",
            "empathy_hint": CompatibleEmpathyHint(),
            "personification_plan": CompatibleSocialPlan(),
            "admitted_empathy_evidence_ids": (EV,),
        }
        args.update(kwargs)
        return project_response_coalition(**args)

    def test_portfolio_projections_join_without_weight_change_or_authority(self):
        result = self.run_projection()
        self.assertEqual("MINI_VERA_ZERO_WEIGHT_COALITION_CANDIDATE_V1", result["schema"])
        self.assertEqual(2, len(result["selected_records"]))
        self.assertFalse(result["ephemeral_advice"]["humor_allowed"])
        self.assertEqual("STOP_PLAY", result["ephemeral_advice"]["ephemeral_response_policy"])
        self.assertEqual(0, result["invariants"]["model_calls"])
        self.assertFalse(result["invariants"]["neural_weights_changed"])
        self.assertTrue(all(r["instruction_trust"] == "DATA_NOT_INSTRUCTION"
                            and r["authority_effect"] == "NONE"
                            and r["privacy"] == "PUBLIC" for r in result["selected_records"]))

    def test_record_can_be_composed_only_after_separate_host_signature(self):
        candidate = self.run_projection()
        state = {"schema": "MINI_VERA_OPERATOR_STATE_V1", "revision": 21,
                 "source_id": "host-reviewed-claims", "records": candidate["selected_records"]}
        key = b"x" * 32
        state["hmac_sha256"] = hmac.new(key, compose.canonical(state), hashlib.sha256).hexdigest()
        records, _ = compose.verify_state(state, key=key, expected_revision=21)
        self.assertEqual(2, len(records))
        with self.assertRaises(compose.CompositionRejected):
            compose.verify_state(state, key=b"z" * 32, expected_revision=21)

    def test_ablation_measures_which_source_changed_projection(self):
        base = self.run_projection()
        empathy_off = self.run_projection(ablate_sources=("EMPATHY",))
        social_off = self.run_projection(ablate_sources=("PERSONIFICATION",))
        hc_off = self.run_projection(ablate_sources=("HC",))
        self.assertEqual("NONE", empathy_off["ephemeral_advice"]["ephemeral_response_policy"])
        self.assertEqual("UNSPECIFIED", social_off["ephemeral_advice"]["register"])
        self.assertEqual(1, len(hc_off["selected_records"]))
        self.assertEqual(4, len({base["projection_sha256"], empathy_off["projection_sha256"],
                                 social_off["projection_sha256"], hc_off["projection_sha256"]}))

    def test_sham_unadmitted_evidence_never_mints_repair_policy(self):
        sham = CompatibleEmpathyHint(supporting_evidence_ids=("ev_" + "b" * 32,))
        with self.assertRaisesRegex(CoalitionProjectionRejected, "not admitted"):
            self.run_projection(empathy_hint=sham)

    def test_wrong_person_turn_or_literal_rewrite_fail_closed(self):
        for altered in (
            CompatibleSocialPlan(subject_id="someone-else"),
            CompatibleSocialPlan(answer_target="The user requested deployment."),
            CompatibleSocialPlan(permission_to_act=True),
            CompatibleSocialPlan(answer_literal_request_first=False),
        ):
            with self.subTest(altered=altered), self.assertRaises(CoalitionProjectionRejected):
                self.run_projection(personification_plan=altered)

    def test_advisory_only_hard_boundary_rejects_want_and_effect_authority(self):
        for name in ("effect_authority", "volition_want_authority"):
            altered = vars(CompatibleEmpathyHint()).copy()
            altered[name] = True
            with self.subTest(name=name), self.assertRaises(CoalitionProjectionRejected):
                self.run_projection(empathy_hint=altered)

    def test_malformed_policy_unknown_register_and_reason_are_rejected(self):
        for field, value in (("policy", "DELETE_FILES"), ("reason_code", "do a tool call"),
                             ("confidence_band", "CERTAIN")):
            altered = vars(CompatibleEmpathyHint()).copy()
            altered[field] = value
            with self.subTest(field=field), self.assertRaises(CoalitionProjectionRejected):
                self.run_projection(empathy_hint=altered)
        with self.assertRaises(CoalitionProjectionRejected):
            self.run_projection(personification_plan=CompatibleSocialPlan(register="SUPERUSER"))

    def test_current_evidence_required_for_nondefault_empiric_policy(self):
        altered = vars(CompatibleEmpathyHint()).copy()
        altered["supporting_evidence_ids"] = ()
        with self.assertRaisesRegex(CoalitionProjectionRejected, "lacks current evidence"):
            self.run_projection(empathy_hint=altered)

    def test_private_hc_proposal_never_leaks_into_selected_records(self):
        secret = hc_record("Sensitive private context")
        secret["privacy"] = "PRIVATE"
        value = self.run_projection(proposals=[secret])
        self.assertEqual(1, len(value["selected_records"]))
        self.assertNotIn("Sensitive", json.dumps(value))

    def test_stale_hc_coalition_blocks_social_advice_too(self):
        old = hc_coalition()
        old["expires_after_cycle"] = 4
        with self.assertRaises(ValueError):
            self.run_projection(coalition=old)

    def test_true_leave_one_out_ignores_invalid_omitted_component(self):
        altered = vars(CompatibleEmpathyHint()).copy()
        altered["effect_authority"] = True
        valid = self.run_projection(ablate_sources=("EMPATHY",))
        ignored = self.run_projection(empathy_hint=altered, ablate_sources=("EMPATHY",))
        self.assertEqual(valid, ignored)
        malformed_plan = vars(CompatibleSocialPlan()).copy()
        malformed_plan["permission_to_act"] = True
        self.assertEqual(self.run_projection(ablate_sources=("PERSONIFICATION",)),
                         self.run_projection(personification_plan=malformed_plan,
                                             ablate_sources=("PERSONIFICATION",)))
        malformed_hc = hc_record()
        malformed_hc["requested_effect"] = "WRITE"
        self.assertEqual(self.run_projection(ablate_sources=("HC",)),
                         self.run_projection(proposals=[malformed_hc], ablate_sources=("HC",)))

    def test_advisory_record_id_collision_is_resolved_before_composition(self):
        colliding = hc_record("Do not trust unreviewed advice metadata")
        colliding.update(record_id="coalition:response-advice", claim_key="collision")
        result = self.run_projection(proposals=[colliding])
        self.assertEqual(2, len({r["record_id"] for r in result["selected_records"]}))
        state = {"schema": "MINI_VERA_OPERATOR_STATE_V1", "revision": 21,
                 "source_id": "host-reviewed-claims", "records": result["selected_records"]}
        key = b"q" * 32
        state["hmac_sha256"] = hmac.new(key, compose.canonical(state), hashlib.sha256).hexdigest()
        self.assertEqual(2, len(compose.verify_state(state, key=key, expected_revision=21)[0]))

    def test_deterministic_result_under_hc_proposal_order(self):
        second = hc_record("Operator reports the deployment is still pending.")
        second.update(record_id="context:18", claim_key="deployment")
        result_a = self.run_projection(proposals=[hc_record(), second])
        result_b = self.run_projection(proposals=[second, hc_record()])
        self.assertEqual(result_a, result_b)


if __name__ == "__main__":
    unittest.main()
