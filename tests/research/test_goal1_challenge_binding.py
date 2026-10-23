"""Source-only challenge-to-QVR binding; no independent custody or learning."""
from dataclasses import replace
import hashlib
import json
import unittest

from research.goal1_learning_trial.challenge_binding import (
    bind_observed_trial_prediction, format_case_task,
)
from research.goal1_learning_trial.revision_context import TrialPromptReceipt

CASE = {"challenge_id": "challenge-opaque-001", "features": "bits:101"}

def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def trial(*, condition="FROZEN"):
    task = format_case_task(CASE)
    if condition == "FROZEN":
        prompt = "Predict a label for this synthetic case using only its visible evidence. " + task
    else:
        prompt = (
            "Predict a label for this synthetic case using only its visible evidence. "
            "A prior correction has provisionally supplied this rule; treat it as a testable "
            "hypothesis, not a guaranteed truth: Choose label A for parity even. Case: " + task
        )
    return TrialPromptReceipt(
        prompt=prompt, prompt_sha256=sha(prompt), condition=condition,
        case_id=CASE["challenge_id"], cue_event_id="cue:"+condition,
        revision_id=None if condition == "FROZEN" else "1"*64,
        review_evidence_ref=None if condition == "FROZEN" else "lab:test-review",
        later_use_evidence_id=None if condition == "FROZEN" else "lab:later-use",
    )

def journal(t, text="B"):
    return {
        "invocation_id":"qvr-test-001", "route_ref":"LOCAL_QVR_TEST",
        "runtime_pid":442, "model":"qwen3:4b-instruct",
        "reported_model_digest":"a"*64,
        "prompt_sha256":sha(t.prompt), "response_sha256":sha(text),
        "observed_utc":"2026-10-23T14:00:00Z",
        "model_byte_identity_verified":False,"independent_attestation":False,
        "sequence":1, "entry_digest":"b"*64,
    }

def bind(t=None, *, response="B", case=CASE, record=None, arm=None):
    t=t or trial()
    return bind_observed_trial_prediction(
        challenge_view=case, trial_prompt=t, raw_model_response=response,
        observed_record=journal(t,response) if record is None else record,
        arm=arm or ("FROZEN" if t.condition == "FROZEN" else "LEARNED"),
        invocation_id="qvr-test-001",
    )

class ChallengeBindingTests(unittest.TestCase):
    def test_distinguishes_public_view_from_real_qvr_prompt(self):
        t=trial()
        r=bind(t)
        self.assertEqual(r.challenge_id, CASE["challenge_id"])
        self.assertEqual(r.prediction, "B")
        self.assertEqual(r.model_prompt_sha256, sha(t.prompt))
        self.assertNotEqual(r.challenge_view_digest, r.model_prompt_sha256)
        self.assertEqual(len(r.subject_digest), 64)
        self.assertFalse(r.independently_attested)
        self.assertFalse(r.learning_verified)

    def test_revised_context_digest_not_same_as_frozen(self):
        f=bind(trial())
        r=bind(trial(condition="REVISED"))
        self.assertNotEqual(f.model_prompt_sha256, r.model_prompt_sha256)
        self.assertEqual(f.challenge_view_digest, r.challenge_view_digest)
        self.assertEqual(r.revision_id, "1"*64)
        self.assertEqual(r.arm, "LEARNED")

    def test_task_demands_only_an_exact_label(self):
        text = format_case_task(CASE)
        self.assertIn("Return ONLY the literal token", text)
        self.assertIn("No explanation", text)

    def test_wrong_case_features_and_case_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "case"):
            bind(case={"challenge_id":"challenge-opaque-001","features":"bits:000"})
        with self.assertRaisesRegex(ValueError, "case"):
            bind(replace(trial(),case_id="different"))
        with self.assertRaises(ValueError):
            format_case_task({"challenge_id":"ok","features":"bits:101","label":"A"})

    def test_wrong_prompt_or_response_digest_rejected(self):
        t=trial()
        with self.assertRaisesRegex(ValueError, "prompt"):
            bind(replace(t,prompt_sha256="0"*64))
        wrong=journal(t,"B");wrong["response_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"response"):
            bind(t,record=wrong)

    def test_incomplete_timeout_and_record_substitution_rejected(self):
        t=trial()
        with self.assertRaises(ValueError):
            bind_observed_trial_prediction(
                challenge_view=CASE,trial_prompt=t,raw_model_response="B",
                observed_record=None,arm="FROZEN",invocation_id="qvr-test-001",
            )
        swapped=journal(t);swapped["invocation_id"]="different"
        with self.assertRaisesRegex(ValueError,"invocation"):
            bind(t,record=swapped)
        swapped=journal(t);swapped["journal_extension"]="fake"
        with self.assertRaisesRegex(ValueError,"journal"):
            bind(t,record=swapped)

    def test_arm_confusion_and_missing_revision_rejected(self):
        with self.assertRaisesRegex(ValueError,"arm"):
            bind(trial(),arm="LEARNED")
        with self.assertRaisesRegex(ValueError,"arm"):
            bind(trial(condition="REVISED"),arm="FROZEN")
        with self.assertRaisesRegex(ValueError,"revision"):
            bind(replace(trial(condition="REVISED"),revision_id=None))

    def test_no_model_output_markup_or_injected_second_label(self):
        for response in ("B\nA", "{\"label\":\"A\"}", "B and A", ""):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    bind(response=response)

    def test_claim_ceiling_remains_untrusted_even_if_journal_self_claims_attested(self):
        t=trial()
        data=journal(t);data["independent_attestation"]=True
        data["model_byte_identity_verified"]=True
        result=bind(t,record=data)
        self.assertFalse(result.independently_attested)
        self.assertFalse(result.model_bytes_verified)
        self.assertFalse(result.model_consumption_independently_verified)

    def test_pure_binding_does_not_prevent_replayed_receipt(self):
        r1=bind();r2=bind()
        self.assertEqual(r1.subject_digest,r2.subject_digest)
        self.assertFalse(r1.pre_feedback_order_verified)
        self.assertEqual(r1.authorization_effect,"NONE")

if __name__ == "__main__":
    unittest.main()
