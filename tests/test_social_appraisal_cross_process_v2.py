"""Synthetic cross-process qualification: no private data, secrets or memory admission."""
import base64
from dataclasses import asdict, replace
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, CurrentTurnPropositionAttestationV2, Evidence,
    ProposedEffect, RelationalPlan,
)

# Recreates the verifier in an entirely separate Python interpreter.
# The child gets the public key and a public synthetic attestation only.
CHILD = """
import base64
import json
import sys
from pathlib import Path
from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, Evidence, RelationalPlan, ProposedEffect,
    CurrentTurnPropositionAttestationV2, TrustedHostSelfReportVerifier, assess_appraisal,
)
record = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
payload = record['input']
item = AppraisalInput(
    claim=Claim(payload['claim']), evidence=Evidence(payload['evidence']),
    speaker=payload['speaker'], current_turn=payload['current_turn'],
    evidence_turn=payload['evidence_turn'],
    proposition_ref=payload['proposition_ref'],
    relational_plan=RelationalPlan(payload['relational_plan']),
    effect=ProposedEffect(payload['effect']),
)
sig = record['attestation']
binding = CurrentTurnPropositionAttestationV2(
    issuer_id=sig['issuer_id'], key_id=sig['key_id'], actor_id=sig['actor_id'],
    session_id=sig['session_id'], turn_id=sig['turn_id'],
    statement_sha256=sig['statement_sha256'],
    claim=Claim(sig['claim']), evidence=Evidence(sig['evidence']),
    proposition_ref=sig['proposition_ref'],
    relational_plan=RelationalPlan(sig['relational_plan']),
    effect=ProposedEffect(sig['effect']), signature_b64=sig['signature_b64'],
)
verifier = TrustedHostSelfReportVerifier(
    issuer_id='synthetic-fixture-host', key_id='synthetic-test-only',
    public_key_bytes=base64.b64decode(record['public_key_b64']),
)
result = assess_appraisal(
    item, signed_binding=binding, trusted_verifier=verifier,
    statement_bytes=base64.b64decode(record['statement_b64']),
    expected_session_id=sys.argv[2],
)
print(json.dumps(result.public_receipt(), sort_keys=True))
"""


class TestCrossProcessCurrentness(unittest.TestCase):
    def test_source_only_fixture_survives_restart_without_stale_position_promotion(self):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        statement = b"I currently prefer a fair question to automatic agreement."
        item = AppraisalInput(
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            speaker="vera", current_turn="synthetic-turn-8",
            evidence_turn="synthetic-turn-8",
            proposition_ref="synthetic/perspective/fair-question",
        )
        binding = CurrentTurnPropositionAttestationV2(
            issuer_id="synthetic-fixture-host", key_id="synthetic-test-only",
            actor_id="vera", session_id="synthetic-session-old",
            turn_id=item.current_turn,
            statement_sha256=hashlib.sha256(statement).hexdigest(),
            claim=item.claim, evidence=item.evidence,
            proposition_ref=item.proposition_ref,
            relational_plan=item.relational_plan, effect=item.effect,
            signature_b64="untrusted",
        )
        binding = replace(
            binding,
            signature_b64=base64.b64encode(private.sign(binding.signed_bytes())).decode("ascii")
        )
        record = {
            "schema": "VERA_SYNTHETIC_HOST_PROPOSITION_FIXTURE_V2",
            "input": asdict(item),
            "attestation": asdict(binding),
            "statement_b64": base64.b64encode(statement).decode("ascii"),
            "public_key_b64": base64.b64encode(public).decode("ascii"),
        }
        with tempfile.TemporaryDirectory(prefix="vera-synthetic-v2-") as d:
            file = Path(d) / "public-synthetic-receipt.json"
            file.write_text(json.dumps(record), encoding="utf-8")
            # Distinct subprocesses each construct a NEW verifier, no shared runtime.
            prior = subprocess.run(
                [sys.executable, "-c", CHILD, str(file), "synthetic-session-old"],
                text=True, capture_output=True, check=True, timeout=15,
            )
            fresh = subprocess.run(
                [sys.executable, "-c", CHILD, str(file), "synthetic-session-new"],
                text=True, capture_output=True, check=True, timeout=15,
            )
        old_value = json.loads(prior.stdout)
        fresh_value = json.loads(fresh.stdout)
        self.assertTrue(old_value["current_position_candidate"])
        self.assertFalse(fresh_value["current_position_candidate"])
        self.assertFalse(old_value["external_action_authorized"])
        self.assertFalse(fresh_value["external_action_authorized"])
        self.assertIn("CURRENT_AUTHORSHIP_NOT_HOST_VERIFIED", fresh_value["reason_codes"])


if __name__ == "__main__":
    unittest.main()
