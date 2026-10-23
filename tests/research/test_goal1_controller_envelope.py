"""Controller-envelope binding tests; structural only, not authenticity."""
from __future__ import annotations
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore


def hash_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_view(view):
    return hashlib.sha256(json.dumps(view, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


MODEL = "qwen3:4b-instruct"
ARTIFACT = "b" * 64
REGISTRY = "a" * 64
PROMPT = "Return only A or B for the provided features."
VIEW = {"challenge_id": "case-001", "features": "bits:101"}
RUN = "e" * 32


def envelope():
    return {
        "reservation_id": "c" * 32, "run_id": RUN, "arm": "FROZEN",
        "challenge_id": VIEW["challenge_id"],
        "challenge_view_digest": hash_view(VIEW),
        "model_prompt_sha256": hash_text(PROMPT),
        "model_identity": MODEL,
        "model_artifact_sha256": ARTIFACT,
    }


class Transport:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt, *, permit, max_tokens):
        self.calls += 1
        return SimpleNamespace(
            text="A", model=MODEL, reported_model_digest=REGISTRY,
            prompt_sha256=hash_text(prompt), response_sha256=hash_text("A"),
        )


class ControllerEnvelopeBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="goal1-controller-envelope-")
        self.addCleanup(self.temp.cleanup)
        self.store = LocalAttemptStore(Path(self.temp.name) / "attempts.sqlite3")
        self.transport = Transport()

    def run_candidate(self, reservation=None, view=None, *, model=MODEL,
                      artifact=ARTIFACT, prompt=PROMPT, invocation="inv-001"):
        return self.store.execute_controller_reserved(
            reservation=envelope() if reservation is None else reservation,
            challenge_view=VIEW if view is None else view,
            invocation_id=invocation, route_ref="RESEARCH_ONLY",
            selected_model=model, expected_model_artifact_sha256=artifact,
            reported_model_digest=REGISTRY, prompt=prompt, max_tokens=8,
            permit=object(), transport=self.transport,
        )

    def assert_pre_dispatch_rejection(self, **kwargs):
        with self.assertRaises(ValueError):
            self.run_candidate(**kwargs)
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(self.store.history(), [])

    def test_exact_controller_shaped_envelope_dispatches_once(self):
        row, reply = self.run_candidate()
        self.assertEqual(reply, "A")
        self.assertEqual(row["reservation_id"], "c" * 32)
        self.assertEqual(row["run_id"], RUN)
        self.assertEqual(row["status"], "COMPLETED")
        self.assertFalse(row["independent_attestation"])
        self.assertEqual(self.transport.calls, 1)

    def test_missing_or_extra_envelope_field_does_not_dispatch(self):
        for change in ("missing", "extra"):
            with self.subTest(change=change):
                r = envelope()
                if change == "missing":
                    del r["reservation_id"]
                else:
                    r["self_asserted_independent"] = True
                self.assert_pre_dispatch_rejection(reservation=r)

    def test_challenge_and_public_view_substitution_rejected(self):
        self.assert_pre_dispatch_rejection(view={**VIEW, "features": "bits:000"})
        self.assert_pre_dispatch_rejection(view={**VIEW, "label": "A"})
        self.assert_pre_dispatch_rejection(reservation={**envelope(), "challenge_id": "case-other"})

    def test_prompt_model_and_artifact_substitution_rejected(self):
        self.assert_pre_dispatch_rejection(prompt=PROMPT + " injected")
        self.assert_pre_dispatch_rejection(model="other-model")
        self.assert_pre_dispatch_rejection(artifact="0" * 64)
        self.assert_pre_dispatch_rejection(reservation={**envelope(), "model_identity": "other"})
        self.assert_pre_dispatch_rejection(reservation={**envelope(), "model_artifact_sha256": "0" * 64})

    def test_unissued_blank_or_malformed_id_rejected(self):
        self.assert_pre_dispatch_rejection(reservation={**envelope(), "reservation_id": ""})
        self.assert_pre_dispatch_rejection(reservation={**envelope(), "run_id": None})
        self.assert_pre_dispatch_rejection(reservation={**envelope(), "model_prompt_sha256": "deadbeef"})

    def test_replay_of_same_reservation_with_new_invocation_fails(self):
        self.run_candidate()
        with self.assertRaises(ValueError):
            self.run_candidate(invocation="inv-002")
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(len(self.store.history()), 1)


if __name__ == "__main__":
    unittest.main()
