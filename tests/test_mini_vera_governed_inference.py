"""Contract tests for an optional actually-wired host/donor/model route."""
import dataclasses
from dataclasses import dataclass
from types import SimpleNamespace
import json
import unittest

from tools.mini_vera import compose, local_session, loopback
from tools.mini_vera import governed_inference as governed


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    referent: str
    value: str
    confidence: float
    source: str
    scope_person_id: str
    active: bool
    evidence_id: str


@dataclass(frozen=True, slots=True)
class Assessment:
    person_id: str
    current_evidence: tuple[Evidence, ...]
    historical_evidence: tuple = ()
    hypotheses: tuple = ()
    stakes: str = "low"


class HostCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        identity, ir = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, br = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        cls.request = local_session.compose_local_turn(
            text="A draft PR exists. Is it installed?",
            turn_id="test-governed-current-001", history=[],
            identity=identity, identity_raw=ir, behavior=behavior, behavior_raw=br,
            state=state, key=key, revision=0, model="gemma3:1b", model_digest="a"*64)

    def observation(self, kind="task_request", referent="task", value=None, *,
                    revision=7, request=None, person="host-session-1", fact_tags=()):
        req=request or self.request
        value = value if value is not None else json.loads(req["inference"]["messages"][-1]["content"])["local_user_turn"]
        evidence=Evidence(kind,referent,value,0.95,"current",person,True,"ev_"+"1"*32)
        return governed.HostObservation(
            req["request_sha256"], req["provenance"]["turn_sha256"],
            person, revision, "nonce-0000000000000001",
            Assessment(person,(evidence,)), fact_tags)

    def dependencies(self, obs):
        calls = {"eval":0,"candidate":0,"transport":0,"observe":0}
        def observe():
            calls["observe"]+=1
            return obs
        def evaluate(assessment):
            calls["eval"]+=1
            ev=assessment.current_evidence[0]
            policy={"task_request":"TASK_DIRECT","direct_correction":"STOP_PLAY",
                    "unsupported_claim":"TRUTHFUL_CHALLENGE"}[ev.kind]
            return SimpleNamespace(policy=policy, reason_code="EXPLICIT_TASK" if policy=="TASK_DIRECT" else "BOUND",
                    authority="NONE",effect_authority=False,memory_admission="NONE",
                    supporting_evidence_ids=(ev.evidence_id,))
        def make_candidate(assessment,text):
            calls["candidate"]+=1
            candidate={
                "schema":"VERA_UNTRUSTED_EMPATHY_PROMPT_CANDIDATE_V1",
                "provenance":"CALLER_REPORTED_UNVERIFIED","authority":"NONE",
                "advisory_policy":"TASK_DIRECT","advisory_reason":"EXPLICIT_TASK",
                "causal_evidence_digest":"b"*64
            }
            return SimpleNamespace(status="CANDIDATE_PROMPT_DATA_NOT_EXECUTED",
                authority="NONE",effect_authority=False,memory_admission="NONE",model_generated=False,
                input_sha256="a"*64,prompt_data=json.dumps(candidate))
        def transport(request):
            calls["transport"]+=1
            loopback.validate_candidate(request)
            return {"schema":"MINI_VERA_UNVERIFIED_LOOPBACK_RESULT_V1","status":"UNVERIFIED_LOCAL_MODEL_OUTPUT",
                    "response":{"text":"A draft alone is not deployment.","finish_reason":"stop"},
                    "provenance":{"composed_request_sha256":request["request_sha256"]},
                    "evidence":{"class":"REAL_LOOPBACK_HTTP_RESPONSE_ONLY","http_calls":1,
                                "memory_admission":"NOT_PERFORMED","authority_effect":"NONE"}}
        return calls,observe,evaluate,make_candidate,transport

    def test_default_disabled_never_invokes_observer_or_model(self):
        counts,observe,evaluate,make_candidate,transport=self.dependencies(self.observation())
        result=governed.run_governed_turn(self.request,observe=observe,evaluate=evaluate,
             make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(result.status,"DISABLED")
        self.assertEqual(counts["transport"],0)
        self.assertEqual(counts["observe"],0)

    def test_task_uses_actual_donor_route_and_revalidates_before_send(self):
        obs=self.observation(fact_tags=("PR_STATUS",))
        counts,observe,evaluate,make_candidate,transport=self.dependencies(obs)
        seen=[]
        def recorded_transport(req):
            seen.append(req)
            return transport(req)
        result=governed.run_governed_turn(self.request,enabled=True,observe=observe,
             evaluate=evaluate,make_donor_candidate=make_candidate,transport=recorded_transport,
             claim_invocation=lambda _: True)
        self.assertEqual(result.status,"MODEL_OUTPUT_UNVERIFIED")
        self.assertEqual(result.selected_policy,"TASK_DIRECT")
        self.assertEqual(result.http_calls,1)
        self.assertEqual(counts["eval"],1)
        self.assertEqual(counts["candidate"],1)
        self.assertEqual(counts["transport"],1)
        self.assertGreaterEqual(counts["observe"],3)
        self.assertEqual(result.source_request_sha256,self.request["request_sha256"])
        self.assertNotEqual(result.sent_request_sha256,self.request["request_sha256"])
        self.assertIn("neither installation",seen[0]["inference"]["messages"][0]["content"])
        self.assertEqual(seen[0]["inference"]["messages"][-1],
                         self.request["inference"]["messages"][-1])
        self.assertEqual(result.result["response"]["text"],"A draft alone is not deployment.")

    def test_stop_must_prevent_transport_even_with_task_in_same_assessment(self):
        obs=self.observation(kind="direct_correction",referent="play_frame",value="stop")
        counts,observe,evaluate,make_candidate,transport=self.dependencies(obs)
        result=governed.run_governed_turn(self.request,enabled=True,observe=observe,
             evaluate=evaluate,make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(result.status,"DONOR_STOP_HOLD")
        self.assertEqual(result.http_calls,0)
        self.assertEqual(counts["transport"],0)
        self.assertEqual(counts["candidate"],0)

    def test_unsupported_claim_is_not_promoted_to_model_fact(self):
        obs=self.observation(kind="unsupported_claim",referent="external_fact",value="unsupported")
        counts,observe,evaluate,make_candidate,transport=self.dependencies(obs)
        result=governed.run_governed_turn(self.request,enabled=True,observe=observe,
             evaluate=evaluate,make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(result.status,"UNSUPPORTED_EVIDENCE_HOLD")
        self.assertEqual(result.http_calls,0)
        self.assertEqual(counts["transport"],0)

    def test_changed_host_revision_before_call_holds_without_transport(self):
        original=self.observation()
        changed=dataclasses.replace(original,revision=8)
        counts,_,evaluate,make_candidate,transport=self.dependencies(original)
        values=iter((original,changed))
        result=governed.run_governed_turn(self.request,enabled=True,
               observe=lambda:next(values),evaluate=evaluate,
               make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(result.status,"HOST_CHANGED_HOLD")
        self.assertEqual(counts["transport"],0)

    def test_change_while_model_generates_withholds_output(self):
        original=self.observation()
        changed=dataclasses.replace(original,revision=8)
        counts,_,evaluate,make_candidate,transport=self.dependencies(original)
        # Pre-claim, post-claim, then after model generation.
        values=iter((original,original,original,changed))
        result=governed.run_governed_turn(self.request,enabled=True,
               observe=lambda:next(values),evaluate=evaluate,
               make_donor_candidate=make_candidate,transport=transport,
               claim_invocation=lambda _: True)
        self.assertEqual(result.status,"OUTPUT_WITHHELD_HOST_CHANGED")
        self.assertIsNone(result.result)
        self.assertEqual(result.http_calls,1)
        self.assertEqual(counts["transport"],1)

    def test_forged_task_direct_does_not_override_direct_stop(self):
        stop=self.observation(kind="direct_correction",referent="play_frame",value="stop")
        counts,observe,_,make_candidate,transport=self.dependencies(stop)
        result=governed.run_governed_turn(self.request,enabled=True,
              observe=observe,evaluate=lambda _: SimpleNamespace(
                  policy="TASK_DIRECT",reason_code="EXPLICIT_TASK",
                  supporting_evidence_ids=(stop.assessment.current_evidence[0].evidence_id,),
                  authority="NONE",effect_authority=False,memory_admission="NONE"),
              make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(result.status,"CURRENT_STOP_HOLD")
        self.assertEqual(counts["transport"],0)

    def test_cross_person_observation_rejected(self):
        o=self.observation()
        wrong=dataclasses.replace(o,assessment=dataclasses.replace(o.assessment,person_id="other"))
        counts,observe,evaluate,make_candidate,transport=self.dependencies(wrong)
        with self.assertRaises(governed.GovernedRejected):
            governed.run_governed_turn(self.request,enabled=True,observe=observe,
              evaluate=evaluate,make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(counts["transport"],0)

    def test_other_turn_replay_rejected(self):
        o=self.observation()
        wrong=dataclasses.replace(o,turn_sha256="c"*64)
        counts,observe,evaluate,make_candidate,transport=self.dependencies(wrong)
        with self.assertRaises(governed.GovernedRejected):
            governed.run_governed_turn(self.request,enabled=True,observe=observe,
              evaluate=evaluate,make_donor_candidate=make_candidate,transport=transport)
        self.assertEqual(counts["transport"],0)

    def test_forged_task_policy_without_task_support_is_rejected(self):
        o=self.observation()
        counts,observe,_,make_candidate,transport=self.dependencies(o)
        def forged(_):
            return SimpleNamespace(policy="TASK_DIRECT",reason_code="EXPLICIT_TASK",
                  supporting_evidence_ids=(),authority="NONE",effect_authority=False,
                  memory_admission="NONE")
        with self.assertRaises(governed.GovernedRejected):
            governed.run_governed_turn(
                self.request,enabled=True,observe=observe,evaluate=forged,
                make_donor_candidate=make_candidate,transport=transport,
                claim_invocation=lambda _: True)
        self.assertEqual(counts["transport"],0)

    def test_nonce_replay_cannot_invoke_the_model_twice(self):
        current = self.observation()
        counts, observe, evaluate, make_candidate, transport = self.dependencies(current)
        consumed = set()
        def admit_once(snapshot):
            if snapshot.nonce in consumed:
                return False
            consumed.add(snapshot.nonce)
            return True
        first = governed.run_governed_turn(
            self.request, enabled=True, observe=observe, evaluate=evaluate,
            make_donor_candidate=make_candidate, transport=transport,
            claim_invocation=admit_once)
        second = governed.run_governed_turn(
            self.request, enabled=True, observe=observe, evaluate=evaluate,
            make_donor_candidate=make_candidate, transport=transport,
            claim_invocation=admit_once)
        self.assertEqual(first.status, "MODEL_OUTPUT_UNVERIFIED")
        self.assertEqual(second.status, "REPLAY_HOLD")
        self.assertEqual(counts["transport"], 1)

    def test_host_revocation_inside_claim_blocks_transport(self):
        original = self.observation()
        state = {"current": original}
        counts, _, evaluate, make_candidate, transport = self.dependencies(original)
        def claim(_snapshot):
            state["current"] = dataclasses.replace(original, revision=8)
            return True
        result = governed.run_governed_turn(
            self.request, enabled=True, observe=lambda: state["current"],
            evaluate=evaluate, make_donor_candidate=make_candidate,
            transport=transport, claim_invocation=claim)
        self.assertEqual(result.status, "HOST_CHANGED_AFTER_CLAIM_HOLD")
        self.assertEqual(result.http_calls, 0)
        self.assertEqual(counts["transport"], 0)

    def test_invalid_transport_provenance_does_not_display_model_output(self):
        o=self.observation()
        counts,observe,evaluate,make_candidate,_=self.dependencies(o)
        def forged(_req):
            return {"schema":"MINI_VERA_UNVERIFIED_LOOPBACK_RESULT_V1","status":"UNVERIFIED_LOCAL_MODEL_OUTPUT",
                    "provenance":{"composed_request_sha256":"f"*64},
                    "response":{"text":"fictional memory","finish_reason":"stop"},
                    "evidence":{"class":"REAL_LOOPBACK_HTTP_RESPONSE_ONLY","http_calls":1,
                                "memory_admission":"NOT_PERFORMED","authority_effect":"NONE"}}
        with self.assertRaises(governed.GovernedRejected):
            governed.run_governed_turn(self.request,enabled=True,observe=observe,
                evaluate=evaluate,make_donor_candidate=make_candidate,transport=forged,
                claim_invocation=lambda _: True)


if __name__=="__main__":
    unittest.main()
