"""Synthetic-only regression and hostile tests for the private Ingest bridge."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ingest import BytesSource, FileSystemStore, Ingestor

from tools.local_training.adapter_prep import build_plan
from tools.local_training.ingest_bridge import plan_ingest_export, write_ingest_export


@unittest.skipIf(os.name == "nt", "private POSIX filesystem required")
class IngestTrainingBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / "intake"
        self.selections = []
        ingestor = Ingestor(FileSystemStore(self.store))
        for i in range(8):
            messages = [
                {"role": "user", "content": f"Private synthetic prompt {i}"},
                {"role": "assistant", "content": f"Private synthetic response {i}"},
            ]
            data = json.dumps({"messages": messages}).encode("utf-8")
            result = ingestor.ingest(BytesSource(data, locator=f"urn:test:training:{i}", media_type="application/json"))
            self.assertEqual(result.status, "ACCEPTED")
            self.selections.append({
                "ingest_id": result.ingest_id,
                "normalized_sha256": result.normalized_artifact.sha256,
                "example_id": f"example-{i}",
                "group_id": f"source-{i // 2}",
                "consent": "owner-approved-local-training",
                "approval_reference": f"synthetic-review-{i}",
            })
        # The normal Ingest store does not assert private-directory semantics.
        for directory in self.store.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o700)
        self.store.chmod(0o700)
        self.selection_path = self.root / "reviewed.jsonl"
        self._write_selection()

    def _write_selection(self):
        self.selection_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in self.selections),
            encoding="utf-8",
        )
        self.selection_path.chmod(0o600)

    def _record_path(self, index=0):
        return self.store / "records" / (self.selections[index]["ingest_id"] + ".json")

    def _change_record(self, callback):
        path = self._record_path()
        value = json.loads(path.read_text(encoding="utf-8"))
        callback(value)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)

    def test_approved_records_export_into_existing_private_training_plan(self):
        plan = plan_ingest_export(self.store, self.selection_path)
        self.assertEqual(plan.examples, 8)
        self.assertEqual(plan.source_groups, 4)
        dest = self.root / "corpus.jsonl"
        exported = write_ingest_export(self.store, self.selection_path, dest)
        self.assertEqual(exported, plan)
        self.assertEqual(hashlib.sha256(dest.read_bytes()).hexdigest(), plan.corpus_sha256)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
        rows = [json.loads(line) for line in dest.read_text().splitlines()]
        self.assertTrue(all(row["provenance"].startswith("ingest:") for row in rows))
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 1,
            "base_model": {
                "hf_repo": "owner/reviewed-model", "revision_sha": "a" * 40,
                "tokenizer_revision_sha": "a" * 40, "chat_template_sha256": "b" * 64,
                "license_review": "synthetic-only", "gguf_base_sha256": "c" * 64,
            },
            "data": {"path": str(dest), "sha256": plan.corpus_sha256,
                     "classification": "private-local-only", "approval_reference": "synthetic-test"},
            "split": {"seed": 1, "evaluation_fraction": 0.25},
            "execution": {"allow_network": False, "allow_weight_update": False},
        }), encoding="utf-8")
        manifest.chmod(0o600)
        prepared = build_plan(manifest)
        self.assertEqual(prepared.training_count + prepared.evaluation_count, 8)
        self.assertFalse(set(prepared.training_group_ids) & set(prepared.evaluation_group_ids))

    def test_ingest_accepted_does_not_imply_local_training_consent(self):
        self.selections[0]["consent"] = "source-only"
        self._write_selection()
        with self.assertRaisesRegex(ValueError, "consent"):
            plan_ingest_export(self.store, self.selection_path)

    def test_rejected_or_quarantined_ingest_record_never_exports(self):
        self._change_record(lambda rec: rec.update(status="QUARANTINED"))
        with self.assertRaisesRegex(ValueError, "not accepted"):
            plan_ingest_export(self.store, self.selection_path)

    def test_ingest_warnings_require_review(self):
        self._change_record(lambda rec: rec.update(warnings=["media_type_mismatch"]))
        with self.assertRaisesRegex(ValueError, "warnings"):
            plan_ingest_export(self.store, self.selection_path)

    def test_blob_tamper_fails_sha_binding(self):
        digest = self.selections[0]["normalized_sha256"]
        path = self.store / "blobs" / "sha256" / digest[:2] / digest
        path.write_bytes(b'{"messages": []}')
        path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "SHA-256/size"):
            plan_ingest_export(self.store, self.selection_path)

    def test_forged_normalize_receipt_cannot_pass(self):
        record = json.loads(self._record_path().read_text())
        for receipt_id in record["receipt_ids"]:
            path = self.store / "receipts" / (receipt_id + ".json")
            receipt = json.loads(path.read_text())
            if receipt["stage"] == "normalize":
                receipt["outcome"] = "PASS_FORGED"
                path.write_text(json.dumps(receipt), encoding="utf-8")
                path.chmod(0o600)
                break
        with self.assertRaisesRegex(ValueError, "receipt digest"):
            plan_ingest_export(self.store, self.selection_path)

    def test_duplicate_review_or_duplicate_artifact_fails(self):
        self.selections[1]["example_id"] = self.selections[0]["example_id"]
        self._write_selection()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            plan_ingest_export(self.store, self.selection_path)

    def test_record_id_traversal_rejected_before_open(self):
        self.selections[0]["ingest_id"] = "../../other"
        self._write_selection()
        with self.assertRaisesRegex(ValueError, "digests"):
            plan_ingest_export(self.store, self.selection_path)

    def test_duplicate_json_keys_in_operator_selection_fail_closed(self):
        first = json.dumps(self.selections[0])
        first = first[:-1] + ',"consent":"owner-approved-local-training"}'
        rest = "".join(json.dumps(row) + "\n" for row in self.selections[1:])
        self.selection_path.write_text(first + "\n" + rest, encoding="utf-8")
        self.selection_path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "duplicate JSON fields"):
            plan_ingest_export(self.store, self.selection_path)

    def test_inconsistent_receipt_with_recomputed_hash_still_fails_stage_gate(self):
        from ingest.canonical import canonical_digest

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        for receipt_id in record["receipt_ids"]:
            path = self.store / "receipts" / (receipt_id + ".json")
            receipt = json.loads(path.read_text())
            if receipt["stage"] == "normalize":
                receipt["outcome"] = "SKIPPED_OPAQUE"
                receipt.pop("receipt_digest")
                receipt["receipt_digest"] = canonical_digest(receipt)
                path.write_text(json.dumps(receipt), encoding="utf-8")
                path.chmod(0o600)
                break
        with self.assertRaisesRegex(ValueError, "normalization and record-ready"):
            plan_ingest_export(self.store, self.selection_path)

    def test_insecure_source_store_permissions_fail_closed(self):
        self.store.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "owner-only"):
            plan_ingest_export(self.store, self.selection_path)

    def test_insecure_approval_file_permissions_fail_closed(self):
        self.selection_path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "private file permissions"):
            plan_ingest_export(self.store, self.selection_path)

    def test_no_existing_output_is_overwritten(self):
        path = self.root / "corpus.jsonl"
        path.write_text("KEEP", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "new absolute"):
            write_ingest_export(self.store, self.selection_path, path)
        self.assertEqual(path.read_text(encoding="utf-8"), "KEEP")

    def test_cli_plan_reports_no_private_training_sample_text(self):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "packages/vera_ingest/src")}
        proc = subprocess.run(
            [sys.executable, "-m", "tools.local_training.ingest_bridge", "plan", str(self.store), str(self.selection_path)],
            cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["examples"], 8)
        self.assertNotIn("Private synthetic", proc.stdout)
        self.assertNotIn(str(self.root), proc.stdout)


if __name__ == "__main__":
    unittest.main()
