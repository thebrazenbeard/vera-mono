"""Model inquiry binding has no tool, feedback, or authorization effects."""
import hashlib
import json
import unittest

from vera_assurance.inquiry_binding import bind_inquiry_from_model_output
from vera_assurance.evaluation_commitment import verify_prediction_commitment


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def proposal(gap="g1", label="A"):
    return {
        "gap_id": gap, "question": "Which uncertain rule applies?",
        "uncertainty": 0.9, "expected_information_gain": 0.8,
        "probe_cost": 2, "predicted_label": label,
    }


def fixture(response=None, prompt="State a possible uncertainty."):
    if response is None:
        response = json.dumps({"inquiries": [proposal()]})
    record = {
        "invocation_id": "qvr-test-1", "route_ref": "LOCAL_QVR_TEST",
        "runtime_pid": 1234, "model": "qwen3:4b-instruct",
        "reported_model_digest": "a" * 64,
        "prompt_sha256": digest(prompt), "response_sha256": digest(response),
        "observed_utc": "2026-10-23T12:00:00Z",
        "model_byte_identity_verified": False, "independent_attestation": False,
        "sequence": 1, "entry_digest": "b" * 64,
    }
    args = {
        "prompt": prompt, "response_text": response,
        "observed_record": record, "invocation_id": "qvr-test-1",
        "case_id": "case-opaque", "learner_candidate_id": "learner-v1",
        "step": 1, "probe_budget": 2,
    }
    return args


class InquiryBindingTests(unittest.TestCase):
    def test_selects_model_text_and_binds_preoutcome_prediction(self):
        result = bind_inquiry_from_model_output(**fixture())
        self.assertEqual(result.selected.selected_gap_id, "g1")
        self.assertEqual(dict(result.prediction.prediction),
                         {"case_id": "case-opaque", "label": "A"})
        self.assertTrue(verify_prediction_commitment(result.prediction))
        self.assertEqual(result.authorization_effect, "NONE")
        self.assertFalse(result.independently_witnessed)
        self.assertFalse(result.model_bytes_verified)
        self.assertFalse(result.self_learning_verified)
        self.assertEqual(len(result.preoutcome_subject_sha256), 64)

    def test_response_mismatch_denies_posthoc_substitution(self):
        args = fixture()
        args["response_text"] = args["response_text"].replace("g1", "g2")
        with self.assertRaisesRegex(ValueError, "digest"):
            bind_inquiry_from_model_output(**args)

    def test_prompt_mismatch_denies_changed_prior_information(self):
        args = fixture()
        args["prompt"] = "DIFFERENT PROMPT"
        with self.assertRaisesRegex(ValueError, "digest"):
            bind_inquiry_from_model_output(**args)

    def test_invocation_mismatch_and_malformed_receipts(self):
        for mutate in (
            {"invocation_id": "different"},
            {"runtime_pid": True},
            {"sequence": 0},
            {"entry_digest": "not-a-digest"},
            {"model": "../model"},
        ):
            args = fixture()
            args["observed_record"].update(mutate)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                bind_inquiry_from_model_output(**args)

    def test_untrusted_tool_commands_and_duplicate_keys_denied(self):
        bodies = (
            '{"inquiries":[],"execute":"delete"}',
            '{"inquiries":[],"inquiries":[]}',
            json.dumps({"inquiries": [{**proposal(), "shell": "run"}]}),
            '{"inquiries":[{"gap_id":"g1","gap_id":"g2"}]}',
            '{"inquiries":[{"gap_id":"g1","question":"Q","uncertainty":NaN,'
            '"expected_information_gain":0.8,"probe_cost":2,"predicted_label":"A"}]}',
        )
        for body in bodies:
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    bind_inquiry_from_model_output(**fixture(response=body))

    def test_invalid_duplicate_and_inflated_candidate_values_denied(self):
        for items in (
            [proposal("same"), proposal("same")],
            [{**proposal(), "probe_cost": True}],
            [{**proposal(), "uncertainty": 1.5}],
            [{**proposal(), "predicted_label": " "}],
            [proposal(str(i)) for i in range(33)],
        ):
            with self.subTest(items=items), self.assertRaises(ValueError):
                bind_inquiry_from_model_output(
                    **fixture(response=json.dumps({"inquiries": items})),
                )

    def test_budget_zero_returns_no_prediction(self):
        args = fixture()
        args["probe_budget"] = 0
        result = bind_inquiry_from_model_output(**args)
        self.assertIsNone(result.prediction)
        self.assertIsNone(result.selected.selected_gap_id)

    def test_commit_changes_when_prediction_label_changes(self):
        one = bind_inquiry_from_model_output(**fixture())
        two = bind_inquiry_from_model_output(
            **fixture(response=json.dumps({"inquiries": [proposal(label="B")]})))
        self.assertNotEqual(one.prediction.commitment, two.prediction.commitment)
        self.assertNotEqual(one.preoutcome_subject_sha256, two.preoutcome_subject_sha256)


if __name__ == "__main__":
    unittest.main()
