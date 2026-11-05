from __future__ import annotations
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from research.goal1_acceptance_bridge.evaluator_claim_custody import (
    CustodyLedger, ClaimDenied,
)

def h(b): return hashlib.sha256(b.encode()).hexdigest()

RES={
    "reservation_id":"res-a","run_id":"run-a","arm":"FROZEN",
    "challenge_id":"challenge-a","challenge_view_digest":h("view"),
    "model_prompt_sha256":h("prompt"),"model_identity":"synthetic",
    "model_artifact_sha256":h("artifact"),
}

class CustodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"evaluator.sqlite"
        self.signing=Ed25519PrivateKey.generate()
        self.ledger=CustodyLedger(self.path,signing_key=self.signing,key_id="evaluator-ephemeral")
    def claim(self, ledger=None, **changes):
        row=dict(RES)
        row.update(changes)
        return (ledger or self.ledger).claim(row,gateway_id="gateway-test",invocation_id="inv-a")
    def test_reserved_claim_exactly_once_and_cold_readback(self):
        self.ledger.reserve(RES)
        claimed=self.claim()
        self.assertEqual(claimed["status"],"CLAIMED")
        self.assertEqual(claimed["reservation_id"],"res-a")
        self.assertEqual(claimed["gateway_id"],"gateway-test")
        self.assertEqual(claimed["invocation_id"],"inv-a")
        self.assertTrue(claimed["claim_id"])
        fresh=CustodyLedger(self.path,signing_key=self.signing,key_id="evaluator-ephemeral")
        with self.assertRaises(ClaimDenied): self.claim(fresh)
        self.assertEqual(fresh.read_claim(claimed["claim_id"])["claim_id"],claimed["claim_id"])
        original=fresh.evidence(claimed["claim_id"])
        self.assertIs(type(original["payload_bytes"]),bytes)
        self.assertIs(type(original["signature"]),bytes)
        self.signing.public_key().verify(original["signature"],original["payload_bytes"])
        self.assertEqual(original["response"],claimed)
    def test_unreserved_and_modified_binding_never_claims(self):
        with self.assertRaises(ClaimDenied): self.claim()
        self.ledger.reserve(RES)
        with self.assertRaises(ClaimDenied): self.claim(model_prompt_sha256=h("other"))
        self.assertEqual(self.ledger.reservation_status("res-a"),"RESERVED")
        self.assertEqual(self.claim()["status"],"CLAIMED")
    def test_concurrent_race_only_one_claim(self):
        self.ledger.reserve(RES)
        accepted=[]
        denied=[]
        def worker(i):
            ledger=CustodyLedger(self.path,signing_key=self.signing,key_id="evaluator-ephemeral")
            try: accepted.append(ledger.claim(RES,gateway_id="gateway-test",invocation_id="inv-"+str(i)))
            except ClaimDenied: denied.append(i)
        ts=[threading.Thread(target=worker,args=(i,)) for i in range(8)]
        for t in ts:t.start()
        for t in ts:t.join()
        self.assertEqual(len(accepted),1)
        self.assertEqual(len(denied),7)
    def test_duplicate_run_arm_challenge_seed_rejected(self):
        self.ledger.reserve(RES)
        with self.assertRaises(ClaimDenied):
            self.ledger.reserve({**RES,"reservation_id":"another-id"})
if __name__=="__main__": unittest.main()
