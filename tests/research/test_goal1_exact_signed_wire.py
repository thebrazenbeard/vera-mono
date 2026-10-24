from __future__ import annotations
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from research.goal1_gateway.sole_route import (
    GatewayAttemptStore, GatewayDispatch, GatewayHold, ModelObservation,
)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def reservation(prompt: str = "bounded prompt") -> dict[str, str]:
    return {
        "reservation_id": "res1", "run_id": "run1", "arm": "FROZEN",
        "challenge_id": "case1", "challenge_view_digest": sha(b"view1"),
        "model_prompt_sha256": sha(prompt.encode()), "model_identity": "qwen3:4b-instruct",
        "model_artifact_sha256": sha(b"test-model-artifact-not-attested"),
    }

class Endpoint:
    def claim_reservation(self, *, reservation, gateway_id, invocation_id):
        return {**reservation, "gateway_id": gateway_id, "invocation_id": invocation_id,
                "status": "CLAIMED", "claim_id": "claim-" + invocation_id}

def claim_helper(client, *, reservation, gateway_id, invocation_id):
    return client.claim_reservation(reservation=reservation, gateway_id=gateway_id,
                                    invocation_id=invocation_id)

class Backend:
    def __init__(self, fails=False):
        self.fails = fails
        self.calls = 0
    def generate(self, prompt, *, model, max_tokens):
        self.calls += 1
        if self.fails:
            raise TimeoutError("inference could have happened")
        return ModelObservation(text="OK", model=model, prompt_tokens=3,
                                output_tokens=2, backend_wall_ms=12)

class Signer:
    key_id = "test-key-only"
    def __init__(self):
        self.private = Ed25519PrivateKey.generate()
    def sign(self, data: bytes) -> bytes:
        return self.private.sign(data)
    def public(self):
        return self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

class ExactWireTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "attempts.sqlite"
        self.store = GatewayAttemptStore(self.file)
        self.signer = Signer()
        self.backend = Backend()
        self.gateway = GatewayDispatch(store=self.store, gateway_id="gateway1",
            endpoint_client=Endpoint(), claim_authorization=claim_helper,
            backend=self.backend, signer=self.signer)

    def test_exact_signed_bytes_survive_cold_store_reopen(self):
        payload, signature = self.gateway.execute(
            reservation=reservation(), invocation_id="inv1",
            prompt="bounded prompt", max_tokens=2)
        artifact = GatewayAttemptStore(self.file).signed_terminal("inv1")
        self.assertEqual(artifact.payload_bytes,
            json.dumps(payload, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False).encode())
        self.assertEqual(artifact.signature, signature)
        self.assertEqual(artifact.payload_sha256, sha(artifact.payload_bytes))
        self.assertFalse(artifact.independent_claim_verified)
        self.assertFalse(artifact.qualified)
        self.signer.private.public_key().verify(artifact.signature, artifact.payload_bytes)

    def test_locally_tampered_terminal_bytes_are_rejected(self):
        self.gateway.execute(reservation=reservation(), invocation_id="inv1",
                             prompt="bounded prompt", max_tokens=2)
        with closing(sqlite3.connect(self.file)) as db, db:
            db.execute("UPDATE attempts SET terminal_bytes=? WHERE invocation_id='inv1'",
                       (b'{"forged":true}',))
        with self.assertRaises(GatewayHold):
            GatewayAttemptStore(self.file).signed_terminal("inv1")

    def test_signed_terminal_must_match_durable_reservation_metadata(self):
        self.gateway.execute(reservation=reservation(), invocation_id="inv1",
                             prompt="bounded prompt", max_tokens=2)
        clean = GatewayAttemptStore(self.file).signed_terminal("inv1")
        self.signer.private.public_key().verify(clean.signature, clean.payload_bytes)
        for column, value in (
            ("reservation_id", "swapped-reservation"),
            ("run_id", "swapped-run"),
            ("arm", "LEARNED"),
            ("challenge_id", "swapped-case"),
            ("gateway_id", "swapped-gateway"),
            ("binding_sha256", sha(b"swapped-binding")),
        ):
            with self.subTest(column=column):
                with closing(sqlite3.connect(self.file)) as db, db:
                    db.execute(f"UPDATE attempts SET {column}=? WHERE invocation_id='inv1'",
                               (value,))
                with self.assertRaisesRegex(GatewayHold, "inconsistent"):
                    GatewayAttemptStore(self.file).signed_terminal("inv1")
                with closing(sqlite3.connect(self.file)) as db, db:
                    original = reservation()
                    original_column = {
                        "reservation_id": original["reservation_id"],
                        "run_id": original["run_id"], "arm": original["arm"],
                        "challenge_id": original["challenge_id"],
                        "gateway_id": "gateway1",
                        "binding_sha256": sha(json.dumps(original, sort_keys=True,
                            ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()),
                    }[column]
                    db.execute(f"UPDATE attempts SET {column}=? WHERE invocation_id='inv1'",
                               (original_column,))
                restored = GatewayAttemptStore(self.file).signed_terminal("inv1")
                self.assertEqual(restored.payload_bytes, clean.payload_bytes)

    def test_unknown_terminal_must_match_original_reservation_metadata(self):
        self.backend.fails=True
        with self.assertRaises(TimeoutError):
            self.gateway.execute(reservation=reservation(), invocation_id="inv1",
                                 prompt="bounded prompt", max_tokens=2)
        with closing(sqlite3.connect(self.file)) as db, db:
            db.execute("UPDATE attempts SET run_id='substituted' WHERE invocation_id='inv1'")
        with self.assertRaises(GatewayHold):
            GatewayAttemptStore(self.file).signed_terminal("inv1")

    def test_missing_original_wire_bytes_cannot_be_reconstructed(self):
        self.gateway.execute(reservation=reservation(), invocation_id="inv1",
                             prompt="bounded prompt", max_tokens=2)
        with closing(sqlite3.connect(self.file)) as db, db:
            db.execute("UPDATE attempts SET terminal_bytes=NULL WHERE invocation_id='inv1'")
        with self.assertRaises(GatewayHold):
            GatewayAttemptStore(self.file).signed_terminal("inv1")

    def test_claimed_without_terminal_cannot_be_read_as_completed(self):
        self.store.reserve(reservation(), "gateway1", "inv1")
        self.store.claim("inv1", "claim-inv1")
        with self.assertRaises(GatewayHold):
            self.store.signed_terminal("inv1")

    def test_unknown_wire_is_signed_nonretryable_and_preserves_nulls(self):
        self.backend.fails = True
        with self.assertRaises(TimeoutError):
            self.gateway.execute(reservation=reservation(), invocation_id="inv1",
                                 prompt="bounded prompt", max_tokens=2)
        artifact = GatewayAttemptStore(self.file).signed_terminal("inv1")
        data = json.loads(artifact.payload_bytes)
        self.assertEqual(artifact.status, "OUTCOME_UNKNOWN")
        self.assertIsNone(data["response_sha256"])
        for k in ("prompt_tokens","output_tokens","gateway_wall_ms","backend_wall_ms"):
            self.assertIsNone(data[k])
        self.signer.private.public_key().verify(artifact.signature, artifact.payload_bytes)
        with self.assertRaises(GatewayHold):
            self.gateway.execute(reservation=reservation(), invocation_id="inv2",
                                 prompt="bounded prompt", max_tokens=2)
        self.assertEqual(self.backend.calls, 1)

if __name__ == "__main__":
    unittest.main()
