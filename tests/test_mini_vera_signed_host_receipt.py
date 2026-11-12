"""Signed host evidence verifier: rejects forged signatures, replay, stale evidence."""
from __future__ import annotations

import hashlib
import json
import secrets
import unittest
from datetime import datetime, timedelta, timezone

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None

from tools.mini_vera import signed_host_receipt as signed


@unittest.skipIf(Ed25519PrivateKey is None, "optional cryptography dependency missing")
class SignedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        self.pin = hashlib.sha256(self.public).hexdigest()
        self.now = datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc)
        self.request_sha = "a" * 64
        self.turn_sha = "b" * 64
        self.source_sha = "c" * 64
        self.challenge = secrets.token_hex(16)
        self.payload = {
            "schema": "MINI_VERA_HOST_READ_SIGNED_PAYLOAD_V1",
            "issuer_id": "host-issuer-test",
            "operation": "READ_ONLY_SOURCE_SHA256",
            "source_name": "tools/mini_vera/compose.py",
            "source_sha256": self.source_sha,
            "source_size_bytes": 15800,
            "effect": "NONE",
            "request_sha256": self.request_sha,
            "turn_sha256": self.turn_sha,
            "challenge_hex": self.challenge,
            "issued_at_utc": self.now.isoformat(),
        }

    def envelope(self, payload=None, private=None):
        payload = self.payload if payload is None else payload
        signer = self.private if private is None else private
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode()
        signature = signer.sign(canonical)
        return json.dumps({
            "schema": "MINI_VERA_SIGNED_HOST_RECEIPT_V1",
            "payload": payload,
            "signature_ed25519_hex": signature.hex(),
        }, sort_keys=True, separators=(",", ":")).encode()

    def verifier(self, **kw):
        return signed.OneShotSignedHostVerifier(
            trusted_public_key=self.public,
            expected_public_key_sha256=self.pin,
            expected_request_sha256=self.request_sha,
            expected_turn_sha256=self.turn_sha,
            expected_source_sha256=self.source_sha,
            challenge_hex=self.challenge,
            now=self.now, **kw)

    def test_real_ed25519_signature_separate_from_model_data(self):
        result = self.verifier().accept(self.envelope())
        self.assertEqual(result["signature_status"], "VALID_ED25519_PINNED_KEY")
        self.assertEqual(result["source_sha256"], self.source_sha)
        self.assertEqual(result["source_name"], "tools/mini_vera/compose.py")
        self.assertEqual(result["evidence_class"], "EXTERNAL_SIGNED_PAYLOAD_NOT_HOST_QUALIFICATION")
        self.assertEqual(result["host_issuer_qualified"], False)
        self.assertNotIn("signature_ed25519_hex", result)

    def test_external_synthetic_signer_process_and_verifier_boundary(self):
        """Private key exists only in a separate disposable signer process."""
        import subprocess
        import sys
        signer_code = """
import sys, json, hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
payload = json.loads(sys.stdin.read())
key = Ed25519PrivateKey.generate()
public = key.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
raw = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                 ensure_ascii=False, allow_nan=False).encode('utf-8')
signed = {
    'schema': 'MINI_VERA_SIGNED_HOST_RECEIPT_V1',
    'payload': payload,
    'signature_ed25519_hex': key.sign(raw).hex()
}
print(json.dumps({'trusted_public_hex': public.hex(), 'envelope': signed},
                 sort_keys=True, separators=(',', ':')))
"""
        proc = subprocess.run(
            [sys.executable, "-c", signer_code],
            input=json.dumps(self.payload), capture_output=True,
            text=True, check=True, timeout=10)
        handed = json.loads(proc.stdout)
        public = bytes.fromhex(handed["trusted_public_hex"])
        verifier = signed.OneShotSignedHostVerifier(
            trusted_public_key=public,
            expected_public_key_sha256=hashlib.sha256(public).hexdigest(),
            expected_request_sha256=self.request_sha,
            expected_turn_sha256=self.turn_sha,
            expected_source_sha256=self.source_sha,
            challenge_hex=self.challenge, now=self.now)
        evidence = verifier.accept(json.dumps(handed["envelope"]).encode())
        self.assertEqual(evidence["signature_status"], "VALID_ED25519_PINNED_KEY")
        self.assertFalse(evidence["host_issuer_qualified"])

    def test_replay_same_challenge_refused(self):
        verifier = self.verifier()
        signed_bytes = self.envelope()
        verifier.accept(signed_bytes)
        with self.assertRaises(signed.ReceiptRefused):
            verifier.accept(signed_bytes)

    def test_concurrent_signature_replay_accepts_only_one(self):
        from concurrent.futures import ThreadPoolExecutor
        verifier = self.verifier()
        receipt = self.envelope()
        def attempt(_):
            try:
                verifier.accept(receipt)
                return True
            except signed.ReceiptRefused:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(pool.map(attempt, range(8)))
        self.assertEqual(1, accepted.count(True))
        self.assertEqual(7, accepted.count(False))

    def test_replay_across_restart_new_challenge_refused(self):
        previous = self.envelope()
        next_challenge = secrets.token_hex(16)
        other = signed.OneShotSignedHostVerifier(
            trusted_public_key=self.public,
            expected_public_key_sha256=self.pin,
            expected_request_sha256=self.request_sha,
            expected_turn_sha256=self.turn_sha,
            expected_source_sha256=self.source_sha,
            challenge_hex=next_challenge,
            now=self.now)
        with self.assertRaises(signed.ReceiptRefused):
            other.accept(previous)

    def test_signature_and_key_pin_tampering_refused(self):
        e = json.loads(self.envelope())
        e["payload"]["source_sha256"] = "0" * 64
        with self.assertRaises(signed.ReceiptRefused):
            self.verifier().accept(json.dumps(e).encode())
        alt = Ed25519PrivateKey.generate()
        with self.assertRaises(signed.ReceiptRefused):
            self.verifier().accept(self.envelope(private=alt))
        with self.assertRaises(signed.ReceiptRefused):
            signed.OneShotSignedHostVerifier(
                trusted_public_key=self.public,
                expected_public_key_sha256="f" * 64,
                expected_request_sha256=self.request_sha,
                expected_turn_sha256=self.turn_sha,
                expected_source_sha256=self.source_sha,
                challenge_hex=self.challenge,
                now=self.now)

    def test_cross_turn_and_source_rebinding_refused(self):
        for field in ("request_sha256", "turn_sha256", "source_sha256"):
            payload = {**self.payload, field: "d" * 64}
            with self.subTest(field=field), self.assertRaises(signed.ReceiptRefused):
                self.verifier().accept(self.envelope(payload=payload))

    def test_expiry_future_and_duplicate_json_keys_refused(self):
        for dt in (self.now - timedelta(minutes=3), self.now + timedelta(minutes=1)):
            payload = {**self.payload, "issued_at_utc": dt.isoformat()}
            with self.subTest(dt=str(dt)), self.assertRaises(signed.ReceiptRefused):
                self.verifier().accept(self.envelope(payload=payload))
        good = self.envelope().decode()
        duplicate = good.replace('"payload":', '"payload":{},"payload":', 1)
        with self.assertRaises(signed.ReceiptRefused):
            self.verifier().accept(duplicate.encode())

    def test_wrong_shape_and_oversized_receipt_refused(self):
        cases = [b'{}', b'{', b'[]', b' ' * 12000,
                 self.envelope().replace(b'"effect":"NONE"', b'"effect":"WRITE"')]
        for blob in cases:
            with self.subTest(blob=blob[:20]), self.assertRaises(signed.ReceiptRefused):
                self.verifier().accept(blob)


if __name__ == "__main__":
    unittest.main()
