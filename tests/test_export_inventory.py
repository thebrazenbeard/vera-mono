import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ingest.cli import main
from ingest.export_inventory import inventory_exports, _is_cloud_or_reparse


class ExportInventoryTests(unittest.TestCase):
    def test_default_is_metadata_only_redacted_and_does_not_create_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private-Ada-secret.txt").write_text("not for GitHub", encoding="utf-8")
            output = io.StringIO()
            store = root / "should-not-exist"
            with patch("pathlib.Path.open", side_effect=AssertionError("unexpected byte read")), redirect_stdout(output):
                code = main(["--store", str(store), "export-inventory", str(root)])
            self.assertEqual(code, 0)
            self.assertFalse(store.exists())
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["file_count"], 1)
            self.assertEqual(payload["files"][0]["admission"], "NOT_GRANTED")
            self.assertNotIn("sha256", payload["files"][0])
            self.assertNotIn("relative_path", payload["files"][0])
            self.assertNotIn("Ada", output.getvalue())
            self.assertFalse(payload["public_release_authorized"])

    def test_explicit_bounded_hashes_are_stably_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_bytes(b"same")
            (root / "b.txt").write_bytes(b"same")
            (root / "c.txt").write_bytes(b"different")
            payload = inventory_exports(root, hash_local=True, max_depth=0)
            rows = payload["files"]
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1]["duplicate_of"], rows[0]["entry_id"])
            self.assertNotEqual(rows[2]["sha256"], rows[0]["sha256"])
            self.assertNotIn("relative_path", rows[0])

    def test_large_files_skipped_without_reading_even_with_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "large.txt").write_bytes(b"0123456789")
            with patch("ingest.export_inventory.os.open", side_effect=AssertionError("file read attempted")):
                payload = inventory_exports(root, hash_local=True, max_read_bytes=8)
            self.assertEqual(payload["files"][0]["status"], "SKIPPED_READ_SIZE_LIMIT")

    def test_reparse_or_offline_flags_are_rejected(self):
        for flag in (0x1000, 0x400, 0x00040000, 0x00400000):
            fake_stat = type("Stat", (), {"st_file_attributes": flag})()
            self.assertTrue(_is_cloud_or_reparse(fake_stat))

    def test_safe_and_malicious_zip_central_directory_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "a_safe.zip", "w") as archive:
                archive.writestr("source/readme.txt", "test")
            with zipfile.ZipFile(root / "b_traversal.zip", "w") as archive:
                archive.writestr("../escape.txt", "test")
            payload = inventory_exports(root, inspect_zip_local=True)
            safe, malicious = payload["files"]
            self.assertEqual(safe["archive"]["status"], "STRUCTURE_BOUNDED")
            self.assertEqual(malicious["archive"]["status"], "REJECTED_METADATA")
            self.assertIn("UNSAFE_MEMBER_PATH", malicious["archive"]["reasons"])
            self.assertEqual(safe["admission"], "NOT_GRANTED")
            self.assertNotIn("readme.txt", json.dumps(payload))

    def test_nested_zip_member_requires_manual_archive_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "nested.zip", "w") as archive:
                archive.writestr("data/child.zip", b"not extracted")
            row = inventory_exports(root, inspect_zip_local=True)["files"][0]
            self.assertEqual(row["archive"]["status"], "REJECTED_METADATA")
            self.assertIn("NESTED_ARCHIVE_MEMBER", row["archive"]["reasons"])

    def test_zip_size_has_absolute_cap_even_with_large_user_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "big.zip").write_bytes(b"0" * (2 * 1024 * 1024 + 1))
            with patch("ingest.export_inventory.os.open", side_effect=AssertionError("file opened")):
                row = inventory_exports(
                    root,
                    inspect_zip_local=True,
                    max_read_bytes=100 * 1024 * 1024,
                )["files"][0]
            self.assertEqual(row["status"], "SKIPPED_READ_SIZE_LIMIT")

    def test_symlink_target_outside_root_never_opened(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real.txt").write_bytes(b"internal")
            try:
                os.symlink(root / "real.txt", root / "link.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not available")
            payload = inventory_exports(root, hash_local=True)
            rows = payload["files"]
            self.assertEqual(rows[0]["status"], "SKIPPED_NONREGULAR")
            self.assertNotIn("sha256", rows[0])

    def test_hard_limit_rejects_with_no_private_path_echo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "name-a.txt").touch()
            (root / "name-b.txt").touch()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["export-inventory", str(root), "--max-files", "1"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "REJECTED")
            self.assertNotIn("name-", output.getvalue())

    def test_file_limit_counts_cumulative_directories_not_just_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for i in range(5):
                group = root / f"group{i}"
                group.mkdir()
                for j in range(5):
                    (group / f"sub{j}").mkdir()
            with self.assertRaisesRegex(ValueError, "entry limit"):
                inventory_exports(root, max_files=5, max_depth=1)

    def test_root_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            try:
                os.symlink(root, root / "link", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks not available")
            with self.assertRaisesRegex(ValueError, "local directory"):
                inventory_exports(root / "link")


if __name__ == "__main__":
    unittest.main()
