"""Controller/issuer end-to-end safety, without treating TOFU as host identity."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.mini_vera import host_read_probe
from tools.mini_vera import ephemeral_host_controller as controller


class ControllerTrialTests(unittest.TestCase):
    def setUp(self):
        self.sha = hashlib.sha256(
            Path(host_read_probe.__file__).with_name("compose.py").read_bytes()
        ).hexdigest()

    def trial(self):
        return controller.run_trial(
            request_sha256="a"*64, turn_sha256="b"*64,
            expected_source_sha256=self.sha)

    def test_live_subprocess_source_signature_is_verified_but_not_host_attested(self):
        result = self.trial()
        self.assertEqual(result["schema"], "MINI_VERA_EPHEMERAL_HOST_TRIAL_V1")
        self.assertEqual(result["source_sha256"], self.sha)
        self.assertEqual(result["status"], "EPHEMERAL_SIGNATURE_CONSISTENT_SOURCE_READ_NOT_ATTESTED")
        self.assertFalse(result["source_read_attested"])
        self.assertEqual(result["signature_status"], "VALID_ED25519_PINNED_KEY")
        self.assertEqual(result["trust_root"], "UNTRUSTED_SAME_USER_EPHEMERAL_SESSION_KEY")
        self.assertFalse(result["host_issuer_qualified"])
        self.assertEqual(result["verified_external_effects"], False)
        self.assertEqual(result["operation"], "READ_ONLY_SOURCE_SHA256")
        self.assertNotEqual(result["issuer_process_id"], os.getpid())
        self.assertEqual(len(result["challenge_hex"]), 32)
        self.assertNotIn("private_key", json.dumps(result))

    def test_source_mismatch_must_refuse_even_if_child_can_sign(self):
        with self.assertRaises(controller.TrialRefused):
            controller.run_trial(
                request_sha256="a"*64, turn_sha256="b"*64,
                expected_source_sha256="0"*64)

    def _real_issuer_packet(self):
        challenge = secrets.token_hex(16)
        request = {
            "schema": "MINI_VERA_EPHEMERAL_ISSUE_REQUEST_V1",
            "request_sha256": "a"*64,
            "turn_sha256": "b"*64,
            "expected_source_sha256": self.sha,
            "challenge_hex": challenge,
        }
        child = subprocess.run(
            [sys.executable, "-B", "-m",
             "tools.mini_vera.ephemeral_host_issuer", "--issue-once"],
            input=json.dumps(request).encode()+b"\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            cwd=str(Path(__file__).resolve().parents[1]), timeout=10)
        self.assertEqual(0, child.returncode, child.stderr)
        return json.loads(child.stdout), challenge

    def test_controller_refuses_spoofed_signature_and_pid(self):
        honest, challenge = self._real_issuer_packet()
        honest_packet = SimpleNamespace(
            returncode=0, stdout=json.dumps(honest).encode()+b"\n", stderr=b"")
        # Establish the baseline passes with the SAME bound challenge before
        # mutation; otherwise a negative test can pass for the wrong reason.
        with patch.object(controller.secrets, "token_hex", return_value=challenge), \
             patch.object(controller.subprocess, "run", return_value=honest_packet):
            self.assertEqual(self.sha, self.trial()["source_sha256"])
        broken = json.loads(json.dumps(honest))
        broken["signed_receipt"]["payload"]["source_sha256"] = "0"*64
        fake = SimpleNamespace(
            returncode=0, stdout=json.dumps(broken).encode()+b"\n", stderr=b"")
        with patch.object(controller.secrets, "token_hex", return_value=challenge), \
             patch.object(controller.subprocess, "run", return_value=fake):
            with self.assertRaises(controller.TrialRefused):
                self.trial()
        broken = json.loads(json.dumps(honest))
        broken["issuer_process_id"] = os.getpid()
        fake = SimpleNamespace(
            returncode=0, stdout=json.dumps(broken).encode()+b"\n", stderr=b"")
        with patch.object(controller.secrets, "token_hex", return_value=challenge), \
             patch.object(controller.subprocess, "run", return_value=fake):
            with self.assertRaises(controller.TrialRefused):
                self.trial()

    def test_fake_same_user_signer_can_match_claim_but_not_attest_host_read(self):
        # Hostile falsifier: a compromised sibling process can self-sign a
        # matching expected digest without opening compose.py even once.
        from datetime import datetime, timezone
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        from tools.mini_vera import signed_host_receipt as signatures
        nonce = "f" * 32
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
        payload = {
            "schema": signatures.PAYLOAD_SCHEMA,
            "issuer_id": "forged-same-user",
            "operation": "READ_ONLY_SOURCE_SHA256",
            "source_name": "tools/mini_vera/compose.py",
            "source_sha256": self.sha,
            "source_size_bytes": 1,
            "effect": "NONE",
            "request_sha256": "a"*64,
            "turn_sha256": "b"*64,
            "challenge_hex": nonce,
            "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        signature = key.sign(signatures.canonical(payload)).hex()
        packet = {
            "schema": "MINI_VERA_EPHEMERAL_ISSUE_RESULT_V1",
            "ephemeral_public_key_hex": public.hex(),
            "ephemeral_public_key_sha256": hashlib.sha256(public).hexdigest(),
            "issuer_process_id": os.getpid()+12345,
            "key_trust": "UNPINNED_EPHEMERAL_KEY_NOT_HOST_TRUST",
            "host_issuer_qualified": False,
            "signed_receipt": {
                "schema": signatures.SCHEMA,
                "payload": payload,
                "signature_ed25519_hex": signature,
            },
        }
        replacement = SimpleNamespace(
            returncode=0, stdout=json.dumps(packet).encode()+b"\n", stderr=b"")
        with patch.object(controller.secrets, "token_hex", return_value=nonce), \
             patch.object(controller.subprocess, "run", return_value=replacement):
            finding = self.trial()
        self.assertEqual(finding["signature_status"], "VALID_ED25519_PINNED_KEY")
        self.assertFalse(finding["host_issuer_qualified"])
        self.assertFalse(finding["source_read_attested"])
        self.assertEqual(finding["status"],
                         "EPHEMERAL_SIGNATURE_CONSISTENT_SOURCE_READ_NOT_ATTESTED")

    def test_real_composed_local_request_binds_source_result_without_model_call(self):
        from tools.mini_vera import compose, local_session, loopback
        identity, identity_raw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, behavior_raw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        state, key = local_session.empty_public_state()
        request = local_session.compose_local_turn(
            text="Inspect only the fixed local source", turn_id="issuer-trial-20261113",
            history=[], identity=identity, identity_raw=identity_raw,
            behavior=behavior, behavior_raw=behavior_raw,
            state=state, key=key, revision=0,
            model="qwen3.5:0.8b", model_digest="a"*64)
        loopback.validate_candidate(request)
        result = controller.run_trial(
            request_sha256=request["request_sha256"],
            turn_sha256=request["provenance"]["turn_sha256"],
            expected_source_sha256=self.sha)
        self.assertEqual(result["source_sha256"], self.sha)
        self.assertEqual(result["turn_sha256"], request["provenance"]["turn_sha256"])
        self.assertFalse(result["host_issuer_qualified"])

    def test_malformed_control_input_refused_before_subprocess(self):
        with patch.object(controller.subprocess, "run") as execute:
            with self.assertRaises(controller.TrialRefused):
                controller.run_trial(
                    request_sha256="not-hex", turn_sha256="b"*64,
                    expected_source_sha256=self.sha)
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
