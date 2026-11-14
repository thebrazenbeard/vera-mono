"""Actual multi-interpreter synthetic signed-correction host-assertion check."""
from __future__ import annotations

from dataclasses import asdict, replace
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vera_core.social_revision_ledger import (
    CorrectionEntry, CorrectionLedger, PropositionType, SourceKind, ROOT_HEAD,
)
from vera_core.social_user_correction_witness import SignedUserCorrectionV1

CHILD = """
import base64
import json
from pathlib import Path
import sys
from vera_core.social_revision_ledger import (
    CorrectionEntry, CorrectionLedger, PropositionType, SourceKind, ROOT_HEAD,
)
from vera_core.social_user_correction_witness import (
    SignedUserCorrectionV1, TrustedCorrectionVerifier,
)
fixture = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
e = fixture['entry']
entry = CorrectionEntry(
    **{**e,
       'proposition_type': PropositionType(e['proposition_type']),
       'source_kind': SourceKind(e['source_kind'])},
)
w = fixture['witness']
witness = SignedUserCorrectionV1(
    **{**w,
       'proposition_type': PropositionType(w['proposition_type']),
       'source_kind': SourceKind(w['source_kind'])},
)
verifier = TrustedCorrectionVerifier(
    issuer_id='ephemeral-host',
    key_id='transient-correction-key',
    public_key_bytes=base64.b64decode(sys.argv[2]),
)
result = verifier.verify(
    witness, ledger=CorrectionLedger(), entry=entry,
    expected_session_id=sys.argv[3], expected_turn_id='turn1',
    expected_previous_head=ROOT_HEAD,
)
receipt = verifier.public_receipt(
    witness, ledger=CorrectionLedger(), entry=entry,
    expected_session_id=sys.argv[3], expected_turn_id='turn1',
    expected_previous_head=ROOT_HEAD,
)
assert receipt['signer_assertion_valid'] is result
print(json.dumps({'witness_valid':result,
                  'receipt':receipt},sort_keys=True))
"""


class TestSignedCorrectionCrossProcess(unittest.TestCase):
    def test_ephemeral_signature_current_context_only_across_three_processes(self):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        entry = CorrectionEntry(
            event_id="event1", session_id="fictional-session1", turn_id="turn1",
            subject_ref="synthetic/greeting/meaning",
            proposition_type=PropositionType.DEFINITION,
            source_kind=SourceKind.CURRENT_USER,
            statement="A greeting is not permission to modify a repository.",
            supersedes=None,
        )
        next_head = CorrectionLedger().append(
            entry, expected_head=ROOT_HEAD,
        ).head
        unsigned = SignedUserCorrectionV1(
            issuer_id="ephemeral-host",
            key_id="transient-correction-key",
            actor_id="authenticated_user",
            session_id=entry.session_id,
            turn_id=entry.turn_id,
            subject_ref=entry.subject_ref,
            proposition_type=entry.proposition_type,
            source_kind=entry.source_kind,
            event_id=entry.event_id,
            supersedes=entry.supersedes,
            statement_sha256=hashlib.sha256(entry.statement.encode("utf-8")).hexdigest(),
            expected_previous_head=ROOT_HEAD,
            resulting_head=next_head,
            signature_b64="",
        )
        signed = replace(
            unsigned,
            signature_b64=base64.b64encode(
                private.sign(unsigned.signed_bytes())
            ).decode("ascii"),
        )
        payload = json.dumps(
            {"entry": asdict(entry), "witness": asdict(signed)},
            sort_keys=True,
        )
        public_b64 = base64.b64encode(public).decode("ascii")
        with tempfile.TemporaryDirectory(prefix="synthetic-correction-witness-") as tmp:
            file = Path(tmp) / "public-test-witness.json"
            file.write_text(payload, encoding="utf-8")
            # Private key has never been serialized, written, or sent to child.
            self.assertNotIn("PRIVATE KEY", file.read_text(encoding="utf-8"))
            results = []
            for session in (
                "fictional-session1", "fictional-session2", "fictional-session1"
            ):
                proc = subprocess.run(
                    [sys.executable, "-c", CHILD, str(file), public_b64, session],
                    capture_output=True, text=True, timeout=20, check=True,
                )
                results.append(json.loads(proc.stdout))
        self.assertEqual(
            [row["witness_valid"] for row in results],
            [True, False, True],
        )
        for row in results:
            receipt = json.dumps(row["receipt"])
            self.assertNotIn(entry.statement, receipt)
            self.assertNotIn(entry.subject_ref, receipt)
            self.assertNotIn(entry.session_id, receipt)
            self.assertFalse(row["receipt"]["external_effect_authorized"])
            self.assertFalse(row["receipt"]["verified_user_identity"])
            self.assertFalse(row["receipt"]["canonical_memory_admitted"])


if __name__ == "__main__":
    unittest.main()
