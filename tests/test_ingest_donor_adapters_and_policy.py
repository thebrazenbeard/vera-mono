import tempfile
import unittest
from pathlib import Path

from ingest import (
    BytesSource,
    FileSource,
    FileSystemStore,
    GitHubFileSource,
    IngestPolicy,
    IngestStatus,
    Ingestor,
    MessageSource,
)
from ingest.adapters import FileAdapter, GitHubAdapter, MessageAdapter, TextBytesAdapter


class FakeGitHubTransport:
    def resolve_ref(self, owner, repository, ref):
        self.resolve_args = (owner, repository, ref)
        return "a" * 40

    def fetch_file(self, owner, repository, commit, path, max_bytes):
        self.fetch_args = (owner, repository, commit, path, max_bytes)
        return b"hello from github\n", "text/plain", {"git_blob_sha": "b" * 40, "size": 18}


class AdapterPolicyTests(unittest.TestCase):
    def test_parser_driving_media_type_is_part_of_ingest_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = Ingestor(FileSystemStore(Path(tmp) / ".ingest"), adapters=[TextBytesAdapter()])
            text = ingestor.ingest(BytesSource(b'{"a":1}', locator="urn:same", media_type="text/plain"))
            structured = ingestor.ingest(BytesSource(b'{"a":1}', locator="urn:same", media_type="application/json"))
            self.assertEqual(text.status, IngestStatus.ACCEPTED)
            self.assertEqual(structured.status, IngestStatus.ACCEPTED)
            self.assertNotEqual(text.ingest_id, structured.ingest_id)

    def test_file_root_confinement_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("nope", encoding="utf-8")
            ingestor = Ingestor(FileSystemStore(Path(tmp) / ".ingest"), adapters=[FileAdapter()])
            result = ingestor.ingest(
                FileSource(str(outside)),
                IngestPolicy(allowed_roots=(str(root),)),
            )
            self.assertEqual(result.status, IngestStatus.REJECTED)
            self.assertIn("outside allowed_roots", result.error)

    def test_invalid_json_file_is_quarantined_but_raw_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"broken":', encoding="utf-8")
            store = FileSystemStore(Path(tmp) / ".ingest")
            result = Ingestor(store, adapters=[FileAdapter()]).ingest(FileSource(str(path)))
            self.assertEqual(result.status, IngestStatus.QUARANTINED)
            self.assertIsNotNone(result.raw_artifact)
            self.assertTrue((store.root / result.raw_artifact.storage_locator).is_file())

    def test_jsonl_file_is_canonicalized_line_by_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            path.write_text('{"b":2,"a":1}\n\n{"z":0}\n', encoding="utf-8")
            store = FileSystemStore(Path(tmp) / ".ingest")
            result = Ingestor(store, adapters=[FileAdapter()]).ingest(FileSource(str(path)))
            self.assertEqual(result.status, IngestStatus.ACCEPTED)
            self.assertIsNotNone(result.normalized_artifact)
            normalized = (store.root / result.normalized_artifact.storage_locator).read_bytes()
            self.assertEqual(normalized, b'{"a":1,"b":2}\n{"z":0}\n')

    def test_github_ref_is_resolved_to_exact_commit_in_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = FakeGitHubTransport()
            ingestor = Ingestor(
                FileSystemStore(Path(tmp) / ".ingest"),
                adapters=[GitHubAdapter(transport)],
            )
            result = ingestor.ingest(GitHubFileSource("o", "r", "main", "README.md"))
            self.assertEqual(result.status, IngestStatus.ACCEPTED)
            self.assertIn("@" + "a" * 40 + "/README.md", result.source.locator)
            self.assertEqual(result.source.claimed_metadata["requested_ref"], "main")
            self.assertEqual(result.source.source_identity["commit"], "a" * 40)

    def test_message_event_time_is_claimed_metadata_not_observation_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            ingestor = Ingestor(
                FileSystemStore(Path(tmp) / ".ingest"),
                adapters=[MessageAdapter()],
            )
            result = ingestor.ingest(
                MessageSource("m1", {"text": "hello"}, source="bus", event_time="2026-09-20T12:00:00Z")
            )
            self.assertEqual(result.source.claimed_metadata["event_time"], "2026-09-20T12:00:00Z")
            self.assertNotEqual(result.source.observed_at, "2026-09-20T12:00:00Z")
            self.assertEqual(
                result.source.observed_metadata["ingestion_time_semantics"],
                "OBSERVATION_TIME_NOT_EVENT_TIME",
            )


if __name__ == "__main__":
    unittest.main()
