"""Synthetic-only tests: no personal export data or host filesystem access."""

from dataclasses import replace
from hashlib import sha256
import unittest

from vera_memory.historical_evidence import HistoricalEvidenceAccessError
from vera_memory.historical_export_projection import (
    ExportProjectionError,
    StagedExportEvidence,
    project_staged_exports,
)


def fields(**changes):
    values = dict(
        source_id="private-source:1", source_sha256="a" * 64,
        item_id="row-1", privacy_scope="OWNER_PRIVATE",
        review_authority_ref="reviewer:external", review_receipt_ref="review:1",
        text="A historically reported observation, not current truth.",
        event_time="2025-01-01T00:00:00Z", recorded_at=None,
        effective_from=None,
    )
    values.update(changes)
    return values


def candidate(**changes):
    return StagedExportEvidence(**fields(**changes))


def project(rows, *, scopes=("OWNER_PRIVATE",), source_ids=("private-source:1",)):
    return project_staged_exports(
        rows, authorized_privacy_scopes=scopes, authorized_source_ids=source_ids,
        retrieved_at="2026-11-02T00:00:00Z",
    )


class HistoricalExportProjectionTests(unittest.TestCase):
    def test_evidence_is_unverified_historical_only(self):
        result = project((candidate(),))
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.source_ids, ("private-source:1",))
        self.assertEqual(record.privacy_scope, "OWNER_PRIVATE")
        self.assertEqual(record.provenance_ceiling, "UNVERIFIED_EXPORT_SOURCE")
        self.assertEqual(record.currentness_rule, "HISTORICAL_ONLY_NO_CURRENTNESS_CLAIM")
        self.assertEqual(record.historical_canonicity, "UNRESOLVED_HISTORY")
        self.assertIsNone(record.recorded_at)
        self.assertEqual(record.recorded_at_status, "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW")
        self.assertEqual(record.effective_from_status, "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW")
        self.assertEqual(record.content["text"], candidate().text)
        self.assertEqual(record.content["review_receipt_status"], "REFERENCE_ONLY_UNVERIFIED")
        self.assertEqual(record.content["review_authority_ref"], "reviewer:external")
        self.assertEqual(result.current_memory_effect, "NONE")
        self.assertEqual(result.authorization_effect, "NONE")
        self.assertEqual(result.result_semantics, "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY")
        with self.assertRaises(TypeError):
            record.content["text"] = "changed"
        with self.assertRaises((TypeError, AttributeError)):
            record.privacy_scope = "PROJECT"

    def test_retrieval_scopes_and_source_ids_required_and_narrow(self):
        other = candidate(source_id="private-source:2", item_id="row-2", privacy_scope="PROJECT")
        result = project((candidate(), other))
        self.assertEqual([r.content["text"] for r in result.records], [candidate().text])
        with self.assertRaises(HistoricalEvidenceAccessError):
            project((candidate(),), scopes=())
        with self.assertRaises(TypeError):
            project((candidate(privacy_scope="P"),), scopes="PROJECT")
        with self.assertRaises(ExportProjectionError):
            project((candidate(),), source_ids=())
        self.assertEqual(project((candidate(),), source_ids=("private-source:2",)).records, ())

    def test_missing_provenance_privacy_review_or_claimed_approval_rejected(self):
        for field in ("source_id", "source_sha256", "item_id", "privacy_scope", "review_authority_ref", "review_receipt_ref"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                candidate(**{field: ""})
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            candidate(source_sha256="not-a-digest")
        with self.assertRaises(TypeError):
            StagedExportEvidence(**{**fields(), "status": "approved"})

    def test_collisions_detected_and_source_namespaced(self):
        first = candidate()
        with self.assertRaisesRegex(ExportProjectionError, "duplicate"):
            project((first, first))
        second = replace(first, source_id="private-source:2")
        different = project((first, second), source_ids=("private-source:1", "private-source:2"))
        self.assertEqual(len({r.memory_id for r in different.records}), 2)
        with self.assertRaisesRegex(ExportProjectionError, "rebinds"):
            project((first, replace(first, item_id="row-2", source_sha256="b" * 64)))

    def test_cross_batch_source_revision_does_not_reuse_memory_identity(self):
        # A revised source digest can arrive in a later bounded batch, outside
        # the within-batch collision check. The historical evidence identities
        # must not silently alias across those distinct source revisions.
        original = candidate()
        revised = replace(original, source_sha256="b" * 64)
        original_id = project((original,)).records[0].memory_id
        revised_id = project((revised,)).records[0].memory_id
        self.assertTrue(original_id.startswith("staged-export:v2:"))
        self.assertTrue(revised_id.startswith("staged-export:v2:"))
        self.assertNotEqual(original_id, revised_id)
        self.assertEqual(original_id, project((original,)).records[0].memory_id)
        # Legacy v1 IDs excluded the corpus digest and are intentionally not
        # treated as aliases; migration requires separate authority.
        legacy_v1_id = "staged-export:" + sha256(
            (original.source_id + "\x00" + original.item_id).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(original_id, legacy_v1_id)

    def test_large_rows_and_untrusted_shapes_rejected(self):
        with self.assertRaisesRegex(ValueError, "text"):
            candidate(text="x" * 8193)
        with self.assertRaisesRegex(ExportProjectionError, "limit"):
            project((candidate(),) * 1025)
        with self.assertRaises(TypeError):
            project(({"source_id": "bad"},))
        with self.assertRaises(ExportProjectionError):
            project((candidate(),), source_ids=("private-source:1", "private-source:1"))
        with self.assertRaises(ValueError):
            candidate(source_id="source\x00row")

    def test_identifier_review_privacy_and_time_byte_caps(self):
        for field in ("source_id", "item_id", "review_authority_ref", "review_receipt_ref"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                candidate(**{field: "x" * 1_000_000})
        with self.assertRaisesRegex(ValueError, "source_id"):
            candidate(source_id="é" * 257)  # UTF-8 size, not characters
        with self.assertRaisesRegex(ValueError, "source_id"):
            candidate(source_id="\ud800")  # unpaired surrogate cannot encode as UTF-8
        with self.assertRaisesRegex(ValueError, "text"):
            candidate(text="\ud800")
        with self.assertRaisesRegex(ValueError, "privacy_scope"):
            candidate(privacy_scope="P" * 129)
        for field in ("event_time", "recorded_at", "effective_from"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                candidate(**{field: "t" * 65})
        with self.assertRaisesRegex(ValueError, "authorized_source_ids"):
            project((), source_ids=tuple(f"source:{index}" for index in range(257)))
        with self.assertRaises(HistoricalEvidenceAccessError):
            project((), scopes=tuple(f"scope:{index}" for index in range(65)))
        with self.assertRaisesRegex(ValueError, "authorized_privacy_scopes"):
            project((), scopes=("P" * 129,))
        with self.assertRaisesRegex(ValueError, "retrieved_at"):
            project_staged_exports(
                (), authorized_privacy_scopes=("OWNER_PRIVATE",),
                authorized_source_ids=("private-source:1",), retrieved_at="T" * 65,
            )


if __name__ == "__main__":
    unittest.main()
