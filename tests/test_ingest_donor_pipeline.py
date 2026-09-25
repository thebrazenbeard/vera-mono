import json
import tempfile
import unittest
from pathlib import Path

from ingest import FileSystemStore, IngestStatus, Ingestor, TextSource


class PipelineTests(unittest.TestCase):
    def test_repeat_same_source_is_duplicate_with_stable_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = Ingestor(FileSystemStore(Path(tmp) / ".ingest"))
            source = TextSource("hello\r\nworld", locator="urn:test:hello")
            first = ingestor.ingest(source)
            second = ingestor.ingest(source)
            self.assertEqual(first.status, IngestStatus.ACCEPTED)
            self.assertEqual(second.status, IngestStatus.DUPLICATE)
            self.assertEqual(first.ingest_id, second.ingest_id)
            self.assertEqual(first.raw_artifact.sha256, second.raw_artifact.sha256)

    def test_same_bytes_from_distinct_sources_share_artifact_not_ingest_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = Ingestor(FileSystemStore(Path(tmp) / ".ingest"))
            a = ingestor.ingest(TextSource("same", locator="urn:a"))
            b = ingestor.ingest(TextSource("same", locator="urn:b"))
            self.assertNotEqual(a.ingest_id, b.ingest_id)
            self.assertEqual(a.raw_artifact.sha256, b.raw_artifact.sha256)

    def test_receipts_are_persisted_and_digest_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileSystemStore(Path(tmp) / ".ingest")
            result = Ingestor(store).ingest(TextSource("receipt", locator="urn:r"))
            self.assertTrue(result.receipt_ids)
            receipt = store.get_receipt(result.receipt_ids[-1])
            digest = receipt.pop("receipt_digest")
            from ingest.canonical import canonical_digest
            self.assertEqual(digest, canonical_digest(receipt))

    def test_accepted_result_receipts_are_bound_into_persisted_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileSystemStore(Path(tmp) / ".ingest")
            result = Ingestor(store).ingest(TextSource("commit", locator="urn:commit"))
            record = store.get_record(result.ingest_id)
            self.assertEqual(record["status"], "ACCEPTED")
            self.assertEqual(record["receipt_ids"], list(result.receipt_ids))
            final_receipt = store.get_receipt(result.receipt_ids[-1])
            self.assertEqual(final_receipt["stage"], "record")
            self.assertEqual(final_receipt["outcome"], "READY")


if __name__ == "__main__":
    unittest.main()
