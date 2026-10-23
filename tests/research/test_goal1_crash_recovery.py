"""Cold-process crash matrix for host-local Goal 1 claim/dispatch seam.

All child processes use synthetic endpoint/model stubs and isolated temp SQLite.
No real provider, verifier, credentials or private label is contacted.
"""
from __future__ import annotations

import os
from contextlib import closing
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore

ROOT = Path(__file__).resolve().parents[2]

CHILD = r'''
import hashlib, json, os, pathlib, sys
from types import SimpleNamespace
from research.goal1_acceptance_bridge.local_attempt import LocalAttemptStore
from research.goal1_acceptance_bridge.endpoint_claim_dispatch import EndpointClaimedLocalDispatcher

base = pathlib.Path(sys.argv[1])
phase = sys.argv[2]
store = LocalAttemptStore(base / "attempts.sqlite")
h = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()
view = {"challenge_id": "case-crash", "features": "synthetic-only"}
prompt = "A synthetic transport check; no external model."
reservation = {
    "reservation_id": "reservation-crash", "run_id": "run-crash",
    "arm": "FROZEN", "challenge_id": view["challenge_id"],
    "challenge_view_digest": h(json.dumps(view, sort_keys=True, separators=(",", ":"), allow_nan=False)),
    "model_prompt_sha256": h(prompt),
    "model_identity": "test-model", "model_artifact_sha256": "a" * 64,
}
class Endpoint:
    def claim_reservation(self, *, reservation, gateway_id, invocation_id):
        if phase == "before_remote_claim":
            os._exit(77)
        (base / "remote-claim-observed").write_text("SYNTHETIC_CLAIMED")
        if phase == "after_remote_claim":
            os._exit(77)
        return {**reservation, "gateway_id": gateway_id, "invocation_id": invocation_id,
                "status": "CLAIMED", "claim_id": "synthetic-claim"}
class Transport:
    def generate(self, prompt, *, permit, max_tokens):
        if phase == "after_local_claim":
            os._exit(77)
        (base / "model-effect-observed").write_text("SYNTHETIC_MODEL_EFFECT")
        if phase == "after_model_effect":
            os._exit(77)
        return SimpleNamespace(text="A", model="test-model",
            reported_model_digest="b" * 64,
            prompt_sha256=h(prompt), response_sha256=h("A"))
def contract(client, *, reservation, gateway_id, invocation_id):
    return client.claim_reservation(reservation=reservation, gateway_id=gateway_id,
                                    invocation_id=invocation_id)
dispatcher = EndpointClaimedLocalDispatcher(
    store=store, gateway_id="test-gateway", selected_model="test-model",
    reported_registry_digest="b" * 64,
    expected_model_artifact_sha256="a" * 64,
    claim_authorization=contract, reservation_client=Endpoint())
dispatcher.dispatch(reservation=reservation, challenge_view=view,
    invocation_id="inv-crash", route_ref="LAB",
    prompt=prompt, max_tokens=8, transport=Transport(), permit=object())
'''


class TestHardCrashRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="goal1-crash-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def hard_exit(self, phase):
        child = subprocess.run(
            [sys.executable, "-c", CHILD, str(self.base), phase],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=12)
        self.assertEqual(child.returncode, 77,
                         f"Expected child-only hard exit at {phase}: {child.stderr[-400:]}")

    def test_each_hard_crash_point_is_visible_and_nonretryable_after_reopen(self):
        cases = (
            ("before_remote_claim", False, False, None,
             "RESERVED_REMOTE_CLAIM_UNKNOWN"),
            ("after_remote_claim", True, False, None,
             "RESERVED_REMOTE_CLAIM_UNKNOWN"),
            ("after_local_claim", True, False, "synthetic-claim",
             "CLAIM_RECORDED_OUTCOME_UNKNOWN"),
            ("after_model_effect", True, True, "synthetic-claim",
             "CLAIM_RECORDED_OUTCOME_UNKNOWN"),
        )
        for phase, remote_claimed, model_effect, claim_id, stage in cases:
            with self.subTest(phase=phase):
                with tempfile.TemporaryDirectory(prefix="goal1-crash-case-") as child_dir:
                    self.base = Path(child_dir)
                    self.hard_exit(phase)
                    self.assertEqual((self.base / "remote-claim-observed").exists(), remote_claimed)
                    self.assertEqual((self.base / "model-effect-observed").exists(), model_effect)
                    opened = LocalAttemptStore(self.base / "attempts.sqlite")
                    report = opened.recovery_report()
                    self.assertEqual(len(report), 1)
                    self.assertEqual(report[0]["recovery_class"], stage)
                    self.assertEqual(report[0]["claim_id"], claim_id)
                    self.assertEqual(report[0]["status"], "RESERVED")
                    self.assertFalse(report[0]["automatic_retry_permitted"])
                    self.assertTrue(report[0]["independent_reconciliation_required"])
                    self.assertFalse(report[0]["independent_attestation"])
                    raw = opened.history()[0]
                    self.assertEqual(raw["status"], "RESERVED")
                    with self.assertRaises(ValueError):
                        opened.reserve(
                            invocation_id="inv-new", reservation_id="res-new",
                            run_id=raw["run_id"], arm=raw["arm"], challenge_id=raw["challenge_id"],
                            challenge_view_digest=raw["challenge_view_digest"],
                            route_ref=raw["route_ref"], model=raw["model"],
                            reported_model_digest=raw["reported_model_digest"],
                            prompt_sha256=raw["prompt_sha256"], max_tokens=8)

    def test_forged_local_attestation_bit_cannot_promote_recovery_report(self):
        store = LocalAttemptStore(self.base / "attempts.sqlite")
        h = "a" * 64
        store.reserve(invocation_id="forged-1", reservation_id="res-forged",
            run_id="run-forged", arm="FROZEN", challenge_id="case-forged",
            challenge_view_digest=h, route_ref="TEST", model="model",
            reported_model_digest=h, prompt_sha256=h, max_tokens=8)
        # Deliberate same-user SQLite tampering. Local flags are not witnesses.
        with closing(sqlite3.connect(store.path)) as db, db:
            db.execute("UPDATE attempts SET independent_attestation=1")
        self.assertTrue(store.history()[0]["independent_attestation"])
        report = LocalAttemptStore(store.path).recovery_report()
        self.assertFalse(report[0]["independent_attestation"])
        self.assertEqual(report[0]["recovery_class"], "RESERVED_REMOTE_CLAIM_UNKNOWN")
        self.assertTrue(report[0]["independent_reconciliation_required"])

    def test_completed_and_unknown_locals_never_pretend_to_be_attested(self):
        store = LocalAttemptStore(self.base / "attempts.sqlite")
        h = "a" * 64
        params = dict(invocation_id="done-1", reservation_id="res-done", run_id="run-done",
                      arm="FROZEN", challenge_id="case-done", challenge_view_digest=h,
                      route_ref="TEST", model="model", reported_model_digest=h,
                      prompt_sha256=h, max_tokens=8)
        store.reserve(**params)
        store.record_claim("done-1", "claim-done")
        store._finish("done-1", status="COMPLETED", response_sha256=h, elapsed_ms=4)
        report = LocalAttemptStore(store.path).recovery_report()[0]
        self.assertEqual(report["recovery_class"], "LOCAL_COMPLETION_UNATTESTED")
        self.assertFalse(report["independent_attestation"])
        self.assertFalse(report["automatic_retry_permitted"])
        self.assertTrue(report["independent_reconciliation_required"])


if __name__ == "__main__":
    unittest.main()
