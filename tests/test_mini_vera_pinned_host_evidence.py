"""Adversarial tests for caller-pinned signature plus durable *unprotected* replay gate."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.mini_vera import host_read_probe, signed_host_receipt
from tools.mini_vera import pinned_host_evidence as pinned


class PinnedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mini-vera-ledger-")
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "accepted-receipts.sqlite"
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        self.pin = hashlib.sha256(self.pub).hexdigest()
        self.request = "a" * 64
        self.turn = "b" * 64
        self.challenge = "c" * 32
        self.source = host_read_probe._read_fixed_source()
        self.source_sha = hashlib.sha256(self.source).hexdigest()
        self.payload = {
            "schema": signed_host_receipt.PAYLOAD_SCHEMA,
            "issuer_id": "synthetic-caller-pinned-issuer",
            "operation": "READ_ONLY_SOURCE_SHA256",
            "source_name": "tools/mini_vera/compose.py",
            "source_sha256": self.source_sha,
            "source_size_bytes": len(self.source),
            "effect": "NONE",
            "request_sha256": self.request,
            "turn_sha256": self.turn,
            "challenge_hex": self.challenge,
            "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def receipt(self, *, payload=None, private=None):
        payload = self.payload if payload is None else payload
        key = self.key if private is None else private
        return json.dumps({
            "schema": signed_host_receipt.SCHEMA,
            "payload": payload,
            "signature_ed25519_hex": key.sign(
                signed_host_receipt.canonical(payload)).hex(),
        }, sort_keys=True, separators=(",", ":")).encode()

    def gate(self, *, pin=None, public=None, ledger=None, challenge=None):
        return pinned.PinnedHostEvidence(
            ledger_path=self.ledger if ledger is None else ledger,
            trusted_public_key=self.pub if public is None else public,
            expected_public_key_sha256=self.pin if pin is None else pin,
            expected_request_sha256=self.request,
            expected_turn_sha256=self.turn,
            expected_source_sha256=self.source_sha,
            challenge_hex=self.challenge if challenge is None else challenge,
        )

    def test_one_signed_receipt_is_durably_recorded_and_restart_replay_refused(self):
        candidate = self.receipt()
        result = self.gate().accept(candidate)
        self.assertEqual("PINNED_SIGNATURE_LOCAL_SOURCE_LEDGER_CONSISTENT", result["status"])
        self.assertEqual(self.source_sha, result["source_sha256"])
        self.assertEqual(self.pin, result["public_key_sha256"])
        self.assertTrue(result["durable_replay_recorded"])
        self.assertFalse(result["host_issuer_qualified"])
        self.assertEqual("CALLER_PIN_NOT_INDEPENDENTLY_ATTESTED", result["pin_provenance"])
        self.assertEqual("UNPROTECTED_LOCAL_SQLITE_ROLLBACK_POSSIBLE",
                         result["replay_protection"])
        self.assertTrue(self.ledger.is_file())
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate().accept(candidate)
        db = sqlite3.connect(self.ledger)
        try:
            row = db.execute("SELECT COUNT(*) FROM accepted").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(1, row)

    def test_wrong_key_pin_and_forged_signature_refuse_without_ledger_writes(self):
        wrong = Ed25519PrivateKey.generate()
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate().accept(self.receipt(private=wrong))
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate(pin="f"*64)
        self.assertFalse(self.ledger.exists())
        forged = json.loads(self.receipt())
        forged["payload"]["source_sha256"] = "0"*64
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate().accept(json.dumps(forged).encode())
        self.assertFalse(self.ledger.exists())
        self.gate().accept(self.receipt())

    def test_wrong_source_size_refused_even_with_valid_signature(self):
        bogus = {**self.payload, "source_size_bytes": len(self.source)-1}
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate().accept(self.receipt(payload=bogus))
        self.assertFalse(self.ledger.exists())

    def test_corrupt_ledger_fail_closed_without_reset_or_overwrite(self):
        self.ledger.write_bytes(b"NOT_A_SQLITE_DATABASE")
        before = self.ledger.read_bytes()
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate().accept(self.receipt())
        self.assertEqual(before, self.ledger.read_bytes())

    def test_path_must_be_outside_source_tree_and_parent_must_exist(self):
        missing_parent = self.ledger.parent / "does-not-exist" / "db.sqlite"
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate(ledger=missing_parent).accept(self.receipt())
        self.assertFalse(missing_parent.exists())

    def test_two_independent_python_processes_cannot_both_admit_same_challenge(self):
        py = sys.executable
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from tools.mini_vera.pinned_host_evidence import PinnedHostEvidence,AdmissionRefused\n"
            "try:\n"
            " PinnedHostEvidence(ledger_path=Path(sys.argv[1]),"
            "trusted_public_key=bytes.fromhex(sys.argv[2]),"
            "expected_public_key_sha256=sys.argv[3],"
            "expected_request_sha256=sys.argv[4],"
            "expected_turn_sha256=sys.argv[5],"
            "expected_source_sha256=sys.argv[6],"
            "challenge_hex=sys.argv[7]).accept(bytes.fromhex(sys.argv[8]))\n"
            " print('ACCEPT')\n"
            "except AdmissionRefused:\n"
            " print('REFUSE')\n"
        )
        args = [py, "-B", "-c", code, str(self.ledger), self.pub.hex(),
                self.pin, self.request, self.turn, self.source_sha,
                self.challenge, self.receipt().hex()]
        procs = [subprocess.Popen(
            args, cwd=str(Path(__file__).resolve().parents[1]),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        results = []
        for p in procs:
            out, err = p.communicate(timeout=12)
            self.assertEqual(p.returncode, 0, err)
            results.append(out.decode().strip())
        self.assertCountEqual(["ACCEPT", "REFUSE"], results)

    def test_hostile_valid_database_rollback_allows_replay_and_is_not_attestation(self):
        candidate = self.receipt()
        first = self.gate().accept(candidate)
        self.assertFalse(first["host_issuer_qualified"])
        # A same-user attacker who can erase the unprotected ledger can
        # defeat rollback resistance. Preserve this negative finding.
        self.ledger.unlink()
        second = self.gate().accept(candidate)
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        self.assertFalse(second["host_issuer_qualified"])

    def test_duplicate_json_receipt_refused_before_writing(self):
        raw = self.receipt().decode()
        duplicate = raw.replace('"payload":', '"payload":{},"payload":', 1)
        with self.assertRaises(pinned.AdmissionRefused):
            self.gate().accept(duplicate.encode())
        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
