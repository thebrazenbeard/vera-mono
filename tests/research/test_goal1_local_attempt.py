"""Host-local reservation evidence tests; NOT independent dispatch attestation."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore


def h(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def params(invocation="inv-test-1", case="case-001", prompt="An unseen question"):
    return dict(
        invocation_id=invocation, run_id="research-run-001",
        arm="FROZEN", challenge_id=case,
        challenge_view_digest=h("public features"),
        route_ref="LAPPY_RESEARCH_ONLY", model="qwen3:4b-instruct",
        reported_model_digest="a"*64, prompt_sha256=h(prompt),
        max_tokens=16,
    )


class FakeModel:
    def __init__(self, *, answer="A", failure=None, bad_digest=False):
        self.calls = 0
        self.answer = answer
        self.failure = failure
        self.bad_digest = bad_digest

    def generate(self, prompt, *, permit, max_tokens):
        self.calls += 1
        if self.failure:
            raise self.failure
        return SimpleNamespace(
            text=self.answer, model="qwen3:4b-instruct",
            reported_model_digest="a"*64, prompt_sha256=h(prompt),
            response_sha256="b"*64 if self.bad_digest else h(self.answer),
        )


class TestLocalAttemptStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="goal1-local-attempt-")
        self.path = Path(self.temp.name) / "attempts.sqlite3"
        self.store = LocalAttemptStore(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_reservation_precedes_outbound_and_reopens_metadata_only(self):
        fake = FakeModel(answer="ALPHA SECRET OUTPUT")
        receipt, text = self.store.execute(
            **params(), prompt="An unseen question", transport=fake, permit=object())
        self.assertEqual(fake.calls, 1)
        self.assertEqual(text, "ALPHA SECRET OUTPUT")
        self.assertEqual(receipt["status"], "COMPLETED")
        self.assertEqual(receipt["response_sha256"], h(text))
        self.assertEqual(receipt["model_identity_level"], "REGISTRY_SELF_REPORTED")
        self.assertEqual(receipt["independent_attestation"], False)
        reopened = LocalAttemptStore(self.path)
        self.assertEqual(reopened.history(), [receipt])
        self.assertNotIn(text, str(reopened.history()))
        self.assertNotIn("An unseen question", str(reopened.history()))
        with self.assertRaises(ValueError):
            reopened.execute(**params(), prompt="An unseen question",
                             transport=fake, permit=object())
        self.assertEqual(fake.calls, 1)

    def test_timeout_is_durable_unknown_with_no_same_id_retry(self):
        fake = FakeModel(failure=TimeoutError("response timeout"))
        with self.assertRaises(TimeoutError):
            self.store.execute(**params(), prompt="An unseen question",
                               transport=fake, permit=object())
        self.assertEqual(fake.calls, 1)
        self.assertEqual(LocalAttemptStore(self.path).history()[0]["status"], "OUTCOME_UNKNOWN")
        with self.assertRaises(ValueError):
            self.store.execute(**params(), prompt="An unseen question",
                               transport=fake, permit=object())
        self.assertEqual(fake.calls, 1)

    def test_crash_after_reservation_stays_undispatchable_on_reopen(self):
        self.store.reserve(**params())
        reopened = LocalAttemptStore(self.path)
        self.assertEqual(reopened.history()[0]["status"], "RESERVED")
        with self.assertRaises(ValueError):
            reopened.reserve(**params())
        with self.assertRaises(ValueError):
            reopened.reserve(**params(invocation="other-id"))

    def test_malformed_response_cannot_complete(self):
        fake = FakeModel(answer="A", bad_digest=True)
        with self.assertRaises(ValueError):
            self.store.execute(**params(), prompt="An unseen question",
                               transport=fake, permit=object())
        self.assertEqual(self.store.history()[0]["status"], "OUTCOME_UNKNOWN")

    def test_wrong_prompt_does_not_dispatch(self):
        fake = FakeModel()
        with self.assertRaises(ValueError):
            self.store.execute(**params(), prompt="different", transport=fake, permit=object())
        self.assertEqual(fake.calls, 0)
        self.assertEqual(self.store.history(), [])

    def test_duplicate_reservation_across_independent_python_processes(self):
        # Same SQLite file; unique constraints and BEGIN IMMEDIATE decide race.
        script = (
            "from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore;"
            "import hashlib,sys;"
            "h=lambda x:hashlib.sha256(x.encode()).hexdigest();"
            "s=LocalAttemptStore(sys.argv[1]);"
            "s.reserve(invocation_id='inv-proc',run_id='run-proc',arm='FROZEN',"
            "challenge_id='case-proc',challenge_view_digest=h('view'),"
            "route_ref='RESEARCH',model='qwen3:4b-instruct',"
            "reported_model_digest='a'*64,prompt_sha256=h('prompt'),max_tokens=16)"
        )
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
        p1 = subprocess.Popen([sys.executable, "-c", script, str(self.path)], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p2 = subprocess.Popen([sys.executable, "-c", script, str(self.path)], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p1.communicate(timeout=12)
        p2.communicate(timeout=12)
        self.assertEqual(sorted((p1.returncode, p2.returncode)), [0, 1])
        self.assertEqual(len(LocalAttemptStore(self.path).history()), 1)


if __name__ == "__main__":
    unittest.main()
