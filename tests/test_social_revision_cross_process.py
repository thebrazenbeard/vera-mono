"""Restart adversary: a synthetically persisted correction never rebinds as current."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from vera_core.social_revision_ledger import (
    CorrectionEntry, CorrectionLedger, PropositionType, SourceKind, ROOT_HEAD,
    RevisionConflict,
)

CHILD = """
import json
from dataclasses import replace
from pathlib import Path
import sys
from vera_core.social_revision_ledger import CorrectionLedger, PropositionType
snap = Path(sys.argv[1]).read_text(encoding='utf-8')
ledger = CorrectionLedger.restore(snap, expected_head=sys.argv[2])
reconstructed = CorrectionLedger(entries=ledger.entries)
relabeled = replace(ledger, archive_status='LOCAL_EPHEMERAL_SOURCE_CLAIMS_ONLY')
event = ledger.latest('synthetic/concept/life', PropositionType.DEFINITION)
print(json.dumps({
    'head':ledger.head,
    'event_count':len(ledger.entries),
    'statement':event.statement,
    'status':ledger.archive_status,
    'current_claim':ledger.current_turn_evidence('S-1','T-2') is not None,
    'reconstructed_current':reconstructed.current_turn_evidence('S-1','T-2') is not None,
    'relabeled_current':relabeled.current_turn_evidence('S-1','T-2') is not None,
    'authority':ledger.external_action_authorized,
    'memory_admitted':ledger.public_receipt()['memory_admitted'],
},sort_keys=True))
"""


class TestSocialRevisionCrossProcess(unittest.TestCase):
    def setUp(self):
        self.first = CorrectionEntry(
            event_id="E-1", session_id="S-1", turn_id="T-1",
            subject_ref="synthetic/concept/life",
            proposition_type=PropositionType.DEFINITION,
            source_kind=SourceKind.CURRENT_USER,
            statement="I did not claim biological life.",
            supersedes=None,
        )
        self.second = CorrectionEntry(
            event_id="E-2", session_id="S-1", turn_id="T-2",
            subject_ref="synthetic/concept/life",
            proposition_type=PropositionType.DEFINITION,
            source_kind=SourceKind.CURRENT_USER,
            statement="I meant a nonbiological self-maintaining process.",
            supersedes="E-1",
        )

    def test_fresh_interpreter_treats_snapshot_as_historical_even_same_turn(self):
        a = CorrectionLedger().append(self.first, expected_head=ROOT_HEAD)
        b = a.append(self.second, expected_head=a.head)
        self.assertIsNone(b.current_turn_evidence("S-1", "T-2"))
        self.assertEqual(
            b.latest(self.second.subject_ref, PropositionType.DEFINITION).statement,
            self.second.statement,
        )
        with tempfile.TemporaryDirectory(prefix="vera-synthetic-revisions-") as tmp:
            file = Path(tmp) / "synthetic-only.json"
            file.write_text(b.snapshot(allow_sensitive_export=True), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-c", CHILD, str(file), b.head],
                capture_output=True, text=True, check=True, timeout=15
            )
        restored = json.loads(result.stdout)
        self.assertEqual(restored["head"], b.head)
        self.assertEqual(restored["event_count"], 2)
        self.assertEqual(restored["statement"], self.second.statement)
        self.assertEqual(restored["status"], "ANCHORED_HISTORICAL_EVIDENCE_ONLY")
        self.assertFalse(restored["current_claim"])
        self.assertFalse(restored["reconstructed_current"])
        self.assertFalse(restored["relabeled_current"])
        self.assertFalse(restored["authority"])
        self.assertFalse(restored["memory_admitted"])

    def test_recomputed_forged_history_cannot_match_previously_pinned_head(self):
        first = CorrectionLedger().append(self.first, expected_head=ROOT_HEAD)
        second = first.append(self.second, expected_head=first.head)
        from dataclasses import replace
        forged_first = replace(
            self.first, statement="This source has been altered!"
        )
        forged = CorrectionLedger().append(forged_first, expected_head=ROOT_HEAD)
        forged = forged.append(self.second, expected_head=forged.head)
        self.assertNotEqual(forged.head, second.head)
        self.assertEqual(
            CorrectionLedger.restore(forged.snapshot(allow_sensitive_export=True)).archive_status,
            "UNANCHORED_HISTORICAL_EVIDENCE_ONLY"
        )
        with self.assertRaises(RevisionConflict):
            CorrectionLedger.restore(forged.snapshot(allow_sensitive_export=True), expected_head=second.head)


if __name__ == "__main__":
    unittest.main()
