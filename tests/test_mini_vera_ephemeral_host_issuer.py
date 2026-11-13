"""One-shot external issuer tests. No installed host service or persistent keys."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import unittest

from tools.mini_vera import ephemeral_host_issuer as issuer
from tools.mini_vera import host_read_probe, signed_host_receipt as signed


def expected_source() -> str:
    return hashlib.sha256(
        Path(host_read_probe.__file__).with_name("compose.py").read_bytes()
    ).hexdigest()


class EphemeralIssuerTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "schema": "MINI_VERA_EPHEMERAL_ISSUE_REQUEST_V1",
            "request_sha256": "a" * 64,
            "turn_sha256": "b" * 64,
            "expected_source_sha256": expected_source(),
            "challenge_hex": secrets.token_hex(16),
        }

    def spawn(self, request=None, *, raw=None):
        if raw is None:
            raw = json.dumps(
                self.request if request is None else request,
                sort_keys=True, separators=(",", ":")).encode() + b"\n"
        return subprocess.run(
            [sys.executable, "-B", "-m",
             "tools.mini_vera.ephemeral_host_issuer", "--issue-once"],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parents[1]), timeout=10,
            check=False,
        )

    def test_real_process_read_sign_verify_without_private_key_export(self):
        child = self.spawn()
        self.assertEqual(0, child.returncode, child.stderr)
        self.assertEqual(1, len(child.stdout.splitlines()))
        envelope = json.loads(child.stdout)
        self.assertEqual("MINI_VERA_EPHEMERAL_ISSUE_RESULT_V1", envelope["schema"])
        self.assertEqual("UNPINNED_EPHEMERAL_KEY_NOT_HOST_TRUST", envelope["key_trust"])
        self.assertFalse(envelope["host_issuer_qualified"])
        self.assertNotEqual(os.getpid(), envelope["issuer_process_id"])
        self.assertNotIn(b"private_key", child.stdout)
        public_key = bytes.fromhex(envelope["ephemeral_public_key_hex"])
        self.assertEqual(hashlib.sha256(public_key).hexdigest(),
                         envelope["ephemeral_public_key_sha256"])
        receipt = envelope["signed_receipt"]
        self.assertEqual("READ_ONLY_SOURCE_SHA256", receipt["payload"]["operation"])
        self.assertEqual(expected_source(), receipt["payload"]["source_sha256"])
        self.assertEqual(self.request["challenge_hex"], receipt["payload"]["challenge_hex"])
        verifier = signed.OneShotSignedHostVerifier(
            trusted_public_key=public_key,
            expected_public_key_sha256=envelope["ephemeral_public_key_sha256"],
            expected_request_sha256=self.request["request_sha256"],
            expected_turn_sha256=self.request["turn_sha256"],
            expected_source_sha256=self.request["expected_source_sha256"],
            challenge_hex=self.request["challenge_hex"],
            now=datetime.now(timezone.utc),
        )
        proof = verifier.accept(json.dumps(receipt).encode())
        self.assertEqual("VALID_ED25519_PINNED_KEY", proof["signature_status"])
        self.assertFalse(proof["host_issuer_qualified"])
        with self.assertRaises(signed.ReceiptRefused):
            verifier.accept(json.dumps(receipt).encode())

    def test_bad_expected_source_refuses_unsigned_and_signing(self):
        wrong = {**self.request, "expected_source_sha256": "0" * 64}
        child = self.spawn(wrong)
        self.assertEqual(2, child.returncode)
        self.assertEqual(b"", child.stdout)
        self.assertIn(b"REFUSED", child.stderr)

    def test_wrong_input_fields_and_wrong_operations_refuse(self):
        for item in (
            {**self.request, "operation": "WRITE"},
            {**self.request, "request_sha256": "unknown"},
            {**self.request, "turn_sha256": "f" * 63},
            {**self.request, "challenge_hex": "f" * 31},
            {**self.request, "schema": "FAKE"},
        ):
            with self.subTest(item=item):
                child = self.spawn(item)
                self.assertEqual(2, child.returncode)
                self.assertEqual(b"", child.stdout)

    def test_noncanonical_duplicate_json_and_oversized_refuse(self):
        data = json.dumps(self.request, separators=(",", ":"))
        for raw in (
            (data[:-1] + ',"request_sha256":"' + "a"*64 + '"}').encode() + b"\n",
            b" " * 5000 + b"\n",
            b"{}\n",
            b"\n",
        ):
            with self.subTest(sample=raw[:20]):
                child = self.spawn(raw=raw)
                self.assertEqual(2, child.returncode)
                self.assertEqual(b"", child.stdout)

    def test_multiple_input_records_never_produce_a_signature(self):
        one = json.dumps(self.request, sort_keys=True, separators=(",", ":")).encode()
        child = self.spawn(raw=one + b"\n" + one + b"\n")
        self.assertEqual(2, child.returncode)
        self.assertEqual(b"", child.stdout)

    def test_two_processes_use_distinct_ephemeral_public_keys_and_challenges(self):
        one = self.spawn()
        self.assertEqual(0, one.returncode, one.stderr)
        new_request = {**self.request, "challenge_hex": secrets.token_hex(16)}
        two = self.spawn(new_request)
        self.assertEqual(0, two.returncode, two.stderr)
        first = json.loads(one.stdout)
        second = json.loads(two.stdout)
        self.assertNotEqual(first["ephemeral_public_key_hex"],
                            second["ephemeral_public_key_hex"])
        self.assertNotEqual(first["signed_receipt"]["payload"]["challenge_hex"],
                            second["signed_receipt"]["payload"]["challenge_hex"])
        # A new session and challenge cannot accept an older signature.
        verifier = signed.OneShotSignedHostVerifier(
            trusted_public_key=bytes.fromhex(second["ephemeral_public_key_hex"]),
            expected_public_key_sha256=second["ephemeral_public_key_sha256"],
            expected_request_sha256=new_request["request_sha256"],
            expected_turn_sha256=new_request["turn_sha256"],
            expected_source_sha256=new_request["expected_source_sha256"],
            challenge_hex=new_request["challenge_hex"],
            now=datetime.now(timezone.utc),
        )
        with self.assertRaises(signed.ReceiptRefused):
            verifier.accept(json.dumps(first["signed_receipt"]).encode())


if __name__ == "__main__":
    unittest.main()
