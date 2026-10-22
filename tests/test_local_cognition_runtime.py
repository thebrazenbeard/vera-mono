"""Integration: selected QualifiedVeraRuntime consumes opt-in local text and reopens its receipt."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vera_core import QualifiedVeraRuntime, VeraStateDirectory
from vera_core.local_cognition import InferencePermit, LocalTextReceipt


MODEL = "qwen3:4b-instruct"
DIGEST = "a" * 64
SCOPE = "SYNTHETIC_LOCAL_INFERENCE_TEST"


class SyntheticModel:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, *, permit=None, max_tokens=64):
        self.calls.append((prompt, permit, max_tokens))
        return LocalTextReceipt(
            text="SYNTHETIC INERT RESPONSE", model=MODEL,
            reported_model_digest=DIGEST,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            response_sha256=hashlib.sha256(b"SYNTHETIC INERT RESPONSE").hexdigest(),
        )


class LocalCognitionRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Native Vera stores retain SQLite handles for the lifetime of the runtime.
        # On Windows they cannot be removed before those objects are closed.
        self.root = Path(tempfile.mkdtemp(prefix="qvr-cognition-test-")) / "state"
        self.permit = InferencePermit(model=MODEL, digest=DIGEST, scope=SCOPE)

    def construct(self, transport=None):
        state = VeraStateDirectory(
            self.root, project_id="synthetic-model-consumer",
            identity_id="synthetic-vera",
        )
        return QualifiedVeraRuntime.from_state_directory(
            state, local_cognition_transport=transport,
            local_cognition_route_ref="LOCAL_QVR_TEST",
        )

    def test_default_disarmed_before_any_model_use(self):
        runtime = self.construct()
        with self.assertRaises(RuntimeError):
            runtime.consume_local_cognition(
                "synthetic", permit=self.permit, invocation_id="inv-1",
            )

    def test_selected_runtime_consumes_fake_and_records_metadata_only(self):
        fake = SyntheticModel()
        runtime = self.construct(fake)
        result = runtime.consume_local_cognition(
            "hello", permit=self.permit, invocation_id="inv-1", max_tokens=13,
        )
        self.assertEqual(fake.calls, [("hello", self.permit, 13)])
        self.assertEqual(result.text, "SYNTHETIC INERT RESPONSE")
        records = runtime.local_cognition_history()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["model"], MODEL)
        self.assertEqual(records[0]["reported_model_digest"], DIGEST)
        self.assertEqual(records[0]["route_ref"], "LOCAL_QVR_TEST")
        self.assertEqual(records[0]["invocation_id"], "inv-1")
        self.assertTrue(records[0]["runtime_pid"] > 0)
        serialized = json.dumps(records)
        self.assertNotIn("hello", serialized)
        self.assertNotIn("SYNTHETIC INERT RESPONSE", serialized)
        self.assertFalse(records[0]["model_byte_identity_verified"])

    def test_separate_runtime_reopens_same_persistent_record(self):
        runtime = self.construct(SyntheticModel())
        runtime.consume_local_cognition(
            "1 + 1?", permit=self.permit, invocation_id="inv-2",
        )
        first = runtime.local_cognition_history()
        reopened = self.construct()
        self.assertEqual(reopened.local_cognition_history(), first)
        self.assertEqual(len(first), 1)

    def test_duplicate_invocation_denied_without_two_network_calls(self):
        fake = SyntheticModel()
        runtime = self.construct(fake)
        runtime.consume_local_cognition(
            "first", permit=self.permit, invocation_id="inv-fixed",
        )
        with self.assertRaises(ValueError):
            runtime.consume_local_cognition(
                "second", permit=self.permit, invocation_id="inv-fixed",
            )
        self.assertEqual(len(fake.calls), 1)

    def test_failure_does_not_commit_receipt(self):
        class Failure:
            def generate(self, *args, **kwargs):
                raise RuntimeError("model failed")
        runtime = self.construct(Failure())
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            runtime.consume_local_cognition(
                "test", permit=self.permit, invocation_id="inv-3",
            )
        self.assertEqual(runtime.local_cognition_history(), [])

    def test_malformed_permit_does_not_invoke_even_fake_transport(self):
        fake = SyntheticModel()
        runtime = self.construct(fake)
        with self.assertRaises(RuntimeError):
            runtime.consume_local_cognition(
                "hello", permit="not-a-permit", invocation_id="inv-invalid",
            )
        self.assertEqual(fake.calls, [])
        self.assertEqual(runtime.local_cognition_history(), [])

    def test_invalid_route_ref_rejected_before_inference(self):
        state = VeraStateDirectory(
            self.root, project_id="synthetic-model-consumer",
            identity_id="synthetic-vera",
        )
        with self.assertRaises(ValueError):
            QualifiedVeraRuntime.from_state_directory(
                state, local_cognition_transport=SyntheticModel(),
                local_cognition_route_ref="../other-system",
            )

    def test_wrong_response_model_never_persisted(self):
        class Swapped(SyntheticModel):
            def generate(self, prompt, *, permit=None, max_tokens=64):
                from dataclasses import replace
                return replace(
                    super().generate(prompt, permit=permit, max_tokens=max_tokens),
                    model="vera-local:latest",
                )
        fake = Swapped()
        runtime = self.construct(fake)
        with self.assertRaises(RuntimeError):
            runtime.consume_local_cognition(
                "hello", permit=self.permit, invocation_id="inv-swap",
            )
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(runtime.local_cognition_history(), [])

    def test_corrupt_persistent_receipt_is_rejected(self):
        runtime = self.construct(SyntheticModel())
        runtime.consume_local_cognition(
            "test", permit=self.permit, invocation_id="inv-corrupt",
        )
        import sqlite3
        with sqlite3.connect(self.root / "cognition/local-inference.sqlite") as db:
            db.execute(
                "UPDATE invocations SET response_sha256=? WHERE invocation_id=?",
                ("0" * 64, "inv-corrupt"),
            )
        with self.assertRaises(ValueError):
            self.construct()


if __name__ == "__main__":
    unittest.main()
