"""Fail-closed synthetic corrections, not identity/consent/memory admission."""
from dataclasses import replace
import json
import unittest

from vera_core.social_revision_ledger import (
    CorrectionEntry, CorrectionLedger, PropositionType, RevisionConflict,
    SourceKind, ROOT_HEAD,
)


class TestSocialRevisionLedger(unittest.TestCase):
    def setUp(self):
        self.a = CorrectionEntry(
            event_id="c1", session_id="synthetic-s1", turn_id="t1",
            subject_ref="life/nonbiological/definition",
            proposition_type=PropositionType.DEFINITION,
            source_kind=SourceKind.CURRENT_USER,
            statement="Life does not necessarily mean biological life.",
            supersedes=None,
        )
        self.b = replace(self.a, event_id="c2", turn_id="t2",
                         statement="I mean self-maintaining nonbiological life.",
                         supersedes="c1")

    def test_empty_head_is_deterministic(self):
        self.assertEqual(CorrectionLedger().head, ROOT_HEAD)

    def test_append_exact_same_subject_and_parent(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        two = one.append(self.b, expected_head=one.head)
        self.assertEqual(two.latest("life/nonbiological/definition",
                                    PropositionType.DEFINITION), self.b)
        self.assertNotEqual(two.head, one.head)
        self.assertEqual(len(two.entries), 2)

    def test_wrong_cas_head_cannot_append(self):
        with self.assertRaises(RevisionConflict):
            CorrectionLedger().append(self.a, expected_head="0"*64)

    def test_same_event_id_replay_cannot_create_new_event(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        with self.assertRaises(RevisionConflict):
            one.append(self.a, expected_head=one.head)

    def test_different_subject_cannot_supersede_prior_referent(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        forged = replace(self.b, subject_ref="life/biological/definition")
        with self.assertRaises(RevisionConflict):
            one.append(forged, expected_head=one.head)

    def test_different_proposition_type_cannot_supersede_definition(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        forged = replace(self.b, proposition_type=PropositionType.CONSENT)
        with self.assertRaises(RevisionConflict):
            one.append(forged, expected_head=one.head)

    def test_correction_must_link_exact_latest_version(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        two = one.append(self.b, expected_head=one.head)
        forged = replace(self.b, event_id="c3", turn_id="t3",
                         statement="One more correction", supersedes="c1")
        with self.assertRaises(RevisionConflict):
            two.append(forged, expected_head=two.head)

    def test_correction_cannot_silently_omit_supersedes(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        with self.assertRaises(RevisionConflict):
            one.append(replace(self.b, supersedes=None), expected_head=one.head)

    def test_unrelated_subject_does_not_conflict(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        different = replace(self.a, event_id="other", subject_ref="coworker/intent",
                            proposition_type=PropositionType.INTENT,
                            statement="I cannot know their motives.")
        two = one.append(different, expected_head=one.head)
        self.assertEqual(two.latest("coworker/intent", PropositionType.INTENT), different)
        self.assertEqual(two.latest(self.a.subject_ref, self.a.proposition_type), self.a)

    def test_source_not_promoted_to_authoritative_position(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        self.assertIsNone(one.current_turn_evidence("synthetic-s1", "t1"))
        self.assertEqual(
            one.latest(self.a.subject_ref, self.a.proposition_type), self.a
        )
        self.assertFalse(one.current_position_authorized)
        self.assertFalse(one.external_action_authorized)

    def test_historical_or_agent_source_not_current_even_matching_session(self):
        for source in (SourceKind.HISTORICAL_RECORD, SourceKind.AGENT_INFERENCE,
                       SourceKind.FOREIGN_PERSONA):
            with self.subTest(source=source):
                entry = replace(self.a, source_kind=source)
                one = CorrectionLedger().append(entry, expected_head=ROOT_HEAD)
                self.assertIsNone(one.current_turn_evidence("synthetic-s1", "t1"))

    def test_other_session_or_turn_cannot_rehydrate_current_evidence(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        self.assertIsNone(one.current_turn_evidence("synthetic-s2", "t1"))
        self.assertIsNone(one.current_turn_evidence("synthetic-s1", "t2"))

    def test_raw_snapshot_requires_explicit_opt_in(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        with self.assertRaises(PermissionError):
            one.snapshot()
        with self.assertRaises(PermissionError):
            one.snapshot(allow_sensitive_export=False)
        self.assertIn("entries", one.snapshot(allow_sensitive_export=True))

    def test_serialization_roundtrip_is_history_only(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        two = one.append(self.b, expected_head=one.head)
        recovered = CorrectionLedger.restore(two.snapshot(allow_sensitive_export=True), expected_head=two.head)
        self.assertEqual(recovered.head, two.head)
        self.assertEqual(recovered.latest(self.a.subject_ref, self.a.proposition_type), self.b)
        self.assertIsNone(recovered.current_turn_evidence("synthetic-s1", "t2"))
        self.assertFalse(recovered.current_position_authorized)

    def test_replay_without_external_anchor_is_only_untrusted_archive(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        recovered = CorrectionLedger.restore(one.snapshot(allow_sensitive_export=True))
        self.assertEqual(recovered.archive_status, "UNANCHORED_HISTORICAL_EVIDENCE_ONLY")
        self.assertIsNone(recovered.current_turn_evidence("synthetic-s1", "t1"))

    def test_replay_wrong_anchor_rejected(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        with self.assertRaises(RevisionConflict):
            CorrectionLedger.restore(one.snapshot(allow_sensitive_export=True), expected_head="0"*64)

    def test_mutated_snapshot_content_rejected(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        payload = json.loads(one.snapshot(allow_sensitive_export=True))
        payload["entries"][0]["statement"] = "Invented different preference"
        with self.assertRaises(RevisionConflict):
            CorrectionLedger.restore(json.dumps(payload), expected_head=one.head)

    def test_reordered_snapshot_events_rejected(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        two = one.append(self.b, expected_head=one.head)
        payload = json.loads(two.snapshot(allow_sensitive_export=True))
        payload["entries"].reverse()
        with self.assertRaises(RevisionConflict):
            CorrectionLedger.restore(json.dumps(payload), expected_head=two.head)

    def test_duplicate_json_key_rejected_even_if_last_value_matches_hash(self):
        ledger = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        valid = ledger.snapshot(allow_sensitive_export=True)
        duplicated = valid.replace(
            '"statement":"Life does not necessarily mean biological life."',
            '"statement":"IMPERSONATED CLAIM",'
            '"statement":"Life does not necessarily mean biological life."',
            1,
        )
        self.assertNotEqual(duplicated, valid)
        with self.assertRaises(ValueError):
            CorrectionLedger.restore(duplicated, expected_head=ledger.head)

    def test_unknown_fields_not_auto_authority(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        payload = json.loads(one.snapshot(allow_sensitive_export=True))
        payload["trusted_host"] = True
        with self.assertRaises(ValueError):
            CorrectionLedger.restore(json.dumps(payload))

    def test_public_receipt_no_private_text_turn_ids_or_referents(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        receipt = json.dumps(one.public_receipt())
        self.assertNotIn(self.a.statement, receipt)
        self.assertNotIn(self.a.turn_id, receipt)
        self.assertNotIn(self.a.subject_ref, receipt)
        self.assertIn("SOURCE_ONLY_UNTRUSTED", receipt)

    def test_cross_session_correction_requires_explicit_history_not_retyping(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        next_session = replace(self.b, session_id="synthetic-s2",
                               source_kind=SourceKind.CURRENT_USER)
        two = one.append(next_session, expected_head=one.head)
        self.assertEqual(two.latest(self.a.subject_ref, self.a.proposition_type), next_session)
        self.assertIsNone(two.current_turn_evidence("synthetic-s1", "t2"))
        self.assertIsNone(two.current_turn_evidence("synthetic-s2", "t2"))
        restored = CorrectionLedger.restore(two.snapshot(allow_sensitive_export=True), expected_head=two.head)
        self.assertIsNone(restored.current_turn_evidence("synthetic-s2", "t2"))

    def test_reconstructed_historical_entries_do_not_become_current(self):
        one = CorrectionLedger().append(self.a, expected_head=ROOT_HEAD)
        history = CorrectionLedger.restore(
            one.snapshot(allow_sensitive_export=True), expected_head=one.head
        )
        # A caller can always reconstruct entries or spoof a public status label.
        # Neither should be mistaken for a trusted live source.
        reconstructed = CorrectionLedger(entries=history.entries)
        relabeled = replace(history, archive_status="LOCAL_EPHEMERAL_SOURCE_CLAIMS_ONLY")
        for ledger in (history, reconstructed, relabeled):
            with self.subTest(status=ledger.archive_status):
                self.assertIsNone(
                    ledger.current_turn_evidence("synthetic-s1", "t1")
                )
                self.assertFalse(ledger.current_position_authorized)

    def test_malformed_source_types_and_payload_rejected(self):
        with self.assertRaises(ValueError):
            replace(self.a, source_kind="CURRENT_USER")
        with self.assertRaises(ValueError):
            replace(self.a, statement="")
        with self.assertRaises(ValueError):
            replace(self.a, subject_ref=" ")
        with self.assertRaises(ValueError):
            replace(self.a, statement="x"*4001)
        with self.assertRaises(ValueError):
            replace(self.a, turn_id=123)


if __name__ == "__main__":
    unittest.main()
