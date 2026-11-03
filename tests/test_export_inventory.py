import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile

from ingest import export_inventory
from ingest.export_inventory_cli import main
from ingest.export_inventory import inventory_exports, _is_cloud_or_reparse


# These tests require an actual descriptor-pinned metadata inventory. Windows,
# WSL, and POSIX runtimes missing fd-scandir/relative-stat intentionally HOLD.
# Keep platform-independent fail-closed assertions running on every platform.
requires_pinned_metadata = unittest.skipUnless(
    export_inventory._has_nofollow_metadata_walk(),
    "requires qualified POSIX descriptor-pinned metadata inventory",
)


class ExportInventoryTests(unittest.TestCase):
    def test_windows_metadata_inventory_holds_before_native_filesystem_access(self):
        # Simulate fd capabilities being available so os.name='nt' alone must
        # enforce HOLD. Replacing os.open/os.scandir with mocks here would
        # accidentally remove them from supports_* and give a false pass.
        with patch.object(export_inventory.os, "name", "nt"), \
                patch.object(export_inventory.os, "supports_dir_fd", frozenset({os.open, os.stat})), \
                patch.object(export_inventory.os, "supports_fd", frozenset({os.scandir})), \
                patch.object(export_inventory.os, "O_NOFOLLOW", 0x20000, create=True), \
                patch.object(export_inventory.os, "O_DIRECTORY", 0x10000, create=True), \
                patch.object(export_inventory, "Path", side_effect=lambda _: object()):
            self.assertFalse(export_inventory._has_nofollow_metadata_walk())
            with self.assertRaisesRegex(ValueError, "no-follow local directory"):
                inventory_exports("C:\\synthetic\\not-accessed", hash_local=True, include_names=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_queued_directory_symlink_retarget_never_leaks_metadata_names(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "source"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (nested / "safe.txt").write_text("local")
            outside = home / "outside"
            outside.mkdir()
            sentinel = "SYNTHETIC_PRIVATE_SENTINEL.txt"
            (outside / sentinel).write_text("do not inventory")
            real_scandir = os.scandir
            changed = False

            def retarget_on_nested_enumeration(folder):
                nonlocal changed
                if not changed and (folder == nested or (isinstance(folder, int) and calls[0] > 0)):
                    # For the original path-based implementation this acts on
                    # its queued directory. A dirfd-based implementation may
                    # already have pinned the directory: the same mutation
                    # must not redirect its enumeration.
                    changed = True
                    nested.rename(root / "nested_saved")
                    nested.symlink_to(outside, target_is_directory=True)
                calls[0] += 1
                return real_scandir(folder)

            calls = [0]
            with patch("ingest.export_inventory.os.scandir", side_effect=retarget_on_nested_enumeration), \
                    patch("ingest.export_inventory._has_nofollow_metadata_walk", return_value=True):
                try:
                    payload = inventory_exports(root, max_depth=2, include_names=True)
                except ValueError:
                    payload = {"files": []}  # fail-closed rejection is acceptable
            self.assertTrue(changed)
            self.assertNotIn(sentinel, json.dumps(payload))

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_metadata_root_symlink_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            actual = home / "actual"
            actual.mkdir()
            (actual / "private.txt").write_text("synthetic")
            (home / "alias").symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "local directory|no-follow"):
                inventory_exports(home / "alias", include_names=True)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_two_level_queued_directory_swap_cannot_scan_outside(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "source"
            nested = root / "level1" / "level2"
            nested.mkdir(parents=True)
            (nested / "safe.txt").write_text("safe")
            outside = home / "outside"
            outside.mkdir()
            sentinel = "SYNTHETIC_PRIVATE_SENTINEL.txt"
            (outside / sentinel).write_text("synthetic")
            real_scandir = os.scandir
            calls = 0

            def retarget_before_leaf_scan(folder):
                nonlocal calls
                calls += 1
                if calls == 3:
                    nested.rename(root / "level1" / "level2_saved")
                    nested.symlink_to(outside, target_is_directory=True)
                return real_scandir(folder)

            with patch("ingest.export_inventory.os.scandir", side_effect=retarget_before_leaf_scan), \
                    patch("ingest.export_inventory._has_nofollow_metadata_walk", return_value=True):
                try:
                    result = inventory_exports(root, max_depth=2, include_names=True)
                except ValueError:
                    result = {"files": []}
            self.assertEqual(calls, 3)
            self.assertNotIn(sentinel, json.dumps(result))

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_metadata_root_descriptor_is_pinned_before_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "source"
            root.mkdir()
            (root / "safe.txt").write_text("safe")
            outside = home / "outside"
            outside.mkdir()
            sentinel = "SYNTHETIC_PRIVATE_SENTINEL.txt"
            (outside / sentinel).write_text("synthetic")
            real_scandir = os.scandir

            def retarget_root(folder):
                root.rename(home / "source_saved")
                root.symlink_to(outside, target_is_directory=True)
                return real_scandir(folder)

            with patch("ingest.export_inventory.os.scandir", side_effect=retarget_root), \
                    patch("ingest.export_inventory._has_nofollow_metadata_walk", return_value=True):
                result = inventory_exports(root, include_names=True)
            self.assertEqual([item["relative_path"] for item in result["files"]], ["safe.txt"])

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_queued_identity_replacement_before_reopen_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "source"
            nested = root / "queued"
            nested.mkdir(parents=True)
            (nested / "safe.txt").write_text("safe")
            outside = home / "outside"
            outside.mkdir()
            (outside / "SYNTHETIC_PRIVATE_SENTINEL.txt").write_text("synthetic")
            original = export_inventory._open_pinned_subdirectory
            altered = False

            def retarget_before_reopen(root_fd, components):
                nonlocal altered
                if components and not altered:
                    altered = True
                    nested.rename(root / "queued_saved")
                    nested.symlink_to(outside, target_is_directory=True)
                return original(root_fd, components)

            with patch("ingest.export_inventory._open_pinned_subdirectory", side_effect=retarget_before_reopen):
                with self.assertRaisesRegex(ValueError, "directory changed"):
                    inventory_exports(root, max_depth=1, include_names=True)
            self.assertTrue(altered)

    def test_metadata_walk_requires_fd_scandir_and_relative_stat(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(export_inventory.os, "supports_fd", frozenset()):
                with self.assertRaisesRegex(ValueError, "no-follow local directory"):
                    inventory_exports(temp)
            with patch.object(export_inventory.os, "supports_dir_fd", frozenset({os.open})):
                with self.assertRaisesRegex(ValueError, "no-follow local directory"):
                    inventory_exports(temp)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_direct_hash_cannot_follow_symlinked_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            secret = outside / "data.bin"
            secret.write_bytes(b"synthetic-outside-private-bytes")
            (root / "alias").symlink_to(outside, target_is_directory=True)
            result = export_inventory._hash_small_local(
                root / "alias" / "data.bin", secret.stat().st_size, 4096
            )
            self.assertIsNone(result, "ancestor symlinks cannot be a byte-read path")

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_direct_zip_metadata_cannot_follow_symlinked_ancestor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            private_zip = outside / "private.zip"
            with zipfile.ZipFile(private_zip, "w") as archive:
                archive.writestr("synthetic.txt", b"synthetic-outside-private-bytes")
            (root / "alias").symlink_to(outside, target_is_directory=True)
            result = export_inventory._inspect_zip_local(
                root / "alias" / "private.zip", private_zip.stat().st_size
            )
            self.assertNotEqual(result["status"], "STRUCTURE_BOUNDED")

    def test_wsl_never_qualifies_for_opted_in_byte_reads(self):
        with patch.dict(os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}):
            self.assertFalse(export_inventory._has_nofollow_open())
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(ValueError, "no-follow local directory"):
                    inventory_exports(temp)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_replaced_file_identity_rejected_before_hash_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            file_path = Path(temp) / "record.txt"
            file_path.write_bytes(b"synthetic-private-example")
            metadata = file_path.stat()
            with patch("ingest.export_inventory.os.read", side_effect=AssertionError("unexpected byte read")):
                digest = export_inventory._hash_small_local(
                    file_path, metadata.st_size, 4096,
                    expected_identity=(metadata.st_dev, metadata.st_ino + 1),
                )
            self.assertIsNone(digest)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "O_NOFOLLOW"), "POSIX no-follow probe")
    def test_inventory_does_not_hash_retargeted_parent_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            root = home / "source"
            nested = root / "nested"
            nested.mkdir(parents=True)
            (nested / "sample.bin").write_bytes(b"local")
            outside = home / "outside"
            outside.mkdir()
            (outside / "sample.bin").write_bytes(b"other")
            original = export_inventory._hash_small_local
            altered = False

            def retarget_then_hash(path, size, limit, **kwargs):
                nonlocal altered
                if not altered:
                    altered = True
                    nested.rename(root / "nested_saved")
                    nested.symlink_to(outside, target_is_directory=True)
                return original(path, size, limit, **kwargs)

            with patch("ingest.export_inventory._hash_small_local", side_effect=retarget_then_hash):
                result = inventory_exports(root, max_depth=1, hash_local=True)
            self.assertTrue(altered)
            row = next(item for item in result["files"] if item["extension"] == ".bin")
            self.assertEqual(row["status"], "SKIPPED_CHANGED_FILE")
            self.assertNotIn("sha256", row)
    @requires_pinned_metadata
    def test_default_is_metadata_only_redacted_and_does_not_create_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private-Ada-secret.txt").write_text("not for GitHub", encoding="utf-8")
            output = io.StringIO()
            store = root / "should-not-exist"
            with patch("pathlib.Path.open", side_effect=AssertionError("unexpected byte read")), redirect_stdout(output):
                code = main([str(root)])
            self.assertEqual(code, 0)
            self.assertFalse(store.exists())
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["file_count"], 1)
            self.assertEqual(payload["files"][0]["admission"], "NOT_GRANTED")
            self.assertNotIn("sha256", payload["files"][0])
            self.assertNotIn("relative_path", payload["files"][0])
            self.assertNotIn("Ada", output.getvalue())
            self.assertFalse(payload["public_release_authorized"])

    @requires_pinned_metadata
    def test_explicit_bounded_hashes_are_stably_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_bytes(b"same")
            (root / "b.txt").write_bytes(b"same")
            (root / "c.txt").write_bytes(b"different")
            payload = inventory_exports(root, hash_local=True, max_depth=0)
            rows = payload["files"]
            self.assertEqual(len(rows), 3)
            if export_inventory._has_nofollow_open():
                self.assertEqual(rows[1]["duplicate_of"], rows[0]["entry_id"])
                self.assertNotEqual(rows[2]["sha256"], rows[0]["sha256"])
            else:
                for row in rows:
                    self.assertEqual(row["status"], "SKIPPED_NO_SAFE_NOFOLLOW_OPEN")
                    self.assertNotIn("sha256", row)
            self.assertNotIn("relative_path", rows[0])

    @requires_pinned_metadata
    def test_large_files_skipped_without_reading_even_with_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "large.txt").write_bytes(b"0123456789")
            # Descriptor opens for metadata pinning are required, but the
            # oversized file must never reach the byte-opening helper.
            with patch("ingest.export_inventory._open_file_without_ancestor_links", side_effect=AssertionError("file read attempted")):
                payload = inventory_exports(root, hash_local=True, max_read_bytes=8)
            self.assertEqual(payload["files"][0]["status"], "SKIPPED_READ_SIZE_LIMIT")

    def test_reparse_or_offline_flags_are_rejected(self):
        for flag in (0x1000, 0x400, 0x00040000, 0x00400000):
            fake_stat = type("Stat", (), {"st_file_attributes": flag})()
            self.assertTrue(_is_cloud_or_reparse(fake_stat))

    def test_missing_windows_attribute_evidence_fails_closed(self):
        unknown = SimpleNamespace(st_mode=0, st_size=1)
        with patch.object(export_inventory, "os", SimpleNamespace(name="nt")):
            self.assertTrue(_is_cloud_or_reparse(unknown))
            self.assertFalse(_is_cloud_or_reparse(SimpleNamespace(st_file_attributes=0)))
        with patch.object(export_inventory, "os", SimpleNamespace(name="posix")):
            self.assertFalse(_is_cloud_or_reparse(unknown))

    def test_missing_nofollow_fails_closed_for_metadata_and_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "a.txt").write_bytes(b"local")
            with zipfile.ZipFile(root / "b.zip", "w") as archive:
                archive.writestr("file.txt", "local")
            with patch.object(export_inventory.os, "O_NOFOLLOW", 0, create=True):
                with patch("ingest.export_inventory.os.open", side_effect=AssertionError("unsafe os.open")):
                    with self.assertRaisesRegex(ValueError, "no-follow local directory"):
                        inventory_exports(root, hash_local=True, inspect_zip_local=True)
                    self.assertIsNone(export_inventory._hash_small_local(root / "a.txt", 5, 4096))
                    self.assertEqual(export_inventory._inspect_zip_local(root / "b.zip", 100)["status"], "REJECTED_METADATA")

    @requires_pinned_metadata
    def test_safe_and_malicious_zip_central_directory_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "a_safe.zip", "w") as archive:
                archive.writestr("source/readme.txt", "test")
            with zipfile.ZipFile(root / "b_traversal.zip", "w") as archive:
                archive.writestr("../escape.txt", "test")
            payload = inventory_exports(root, inspect_zip_local=True)
            safe, malicious = payload["files"]
            if export_inventory._has_nofollow_open():
                self.assertEqual(safe["archive"]["status"], "STRUCTURE_BOUNDED")
                self.assertEqual(malicious["archive"]["status"], "REJECTED_METADATA")
                self.assertIn("UNSAFE_MEMBER_PATH", malicious["archive"]["reasons"])
            else:
                for row in (safe, malicious):
                    self.assertEqual(row["status"], "SKIPPED_NO_SAFE_NOFOLLOW_OPEN")
                    self.assertNotIn("archive", row)
            self.assertEqual(safe["admission"], "NOT_GRANTED")
            self.assertNotIn("readme.txt", json.dumps(payload))

    @requires_pinned_metadata
    def test_nested_zip_member_requires_manual_archive_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "nested.zip", "w") as archive:
                archive.writestr("data/child.zip", b"not extracted")
            row = inventory_exports(root, inspect_zip_local=True)["files"][0]
            if export_inventory._has_nofollow_open():
                self.assertEqual(row["archive"]["status"], "REJECTED_METADATA")
                self.assertIn("NESTED_ARCHIVE_MEMBER", row["archive"]["reasons"])
            else:
                self.assertEqual(row["status"], "SKIPPED_NO_SAFE_NOFOLLOW_OPEN")
                self.assertNotIn("archive", row)

    @requires_pinned_metadata
    def test_jar_container_member_is_flagged_as_nested_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "outer.zip", "w") as archive:
                archive.writestr("lib/child.jar", b"nested archive bytes not inspected")
            row = inventory_exports(root, inspect_zip_local=True)["files"][0]
            if export_inventory._has_nofollow_open():
                self.assertEqual(row["archive"]["status"], "REJECTED_METADATA")
                self.assertIn("NESTED_ARCHIVE_MEMBER", row["archive"]["reasons"])
            else:
                self.assertEqual(row["status"], "SKIPPED_NO_SAFE_NOFOLLOW_OPEN")
                self.assertNotIn("archive", row)

    @requires_pinned_metadata
    def test_zip_size_has_absolute_cap_even_with_large_user_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "big.zip").write_bytes(b"0" * (2 * 1024 * 1024 + 1))
            with patch("ingest.export_inventory._open_file_without_ancestor_links", side_effect=AssertionError("file opened")):
                row = inventory_exports(
                    root,
                    inspect_zip_local=True,
                    max_read_bytes=100 * 1024 * 1024,
                )["files"][0]
            self.assertEqual(row["status"], "SKIPPED_READ_SIZE_LIMIT")

    @requires_pinned_metadata
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

    @requires_pinned_metadata
    def test_hard_limit_rejects_with_no_private_path_echo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "name-a.txt").touch()
            (root / "name-b.txt").touch()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([str(root), "--max-files", "1"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "REJECTED")
            self.assertNotIn("name-", output.getvalue())

    @requires_pinned_metadata
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

    @requires_pinned_metadata
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
