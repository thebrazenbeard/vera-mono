from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.local_training.adapter_prep import build_plan, write_private_splits


@unittest.skipIf(os.name == "nt", "POSIX private-file semantics unavailable on Windows")
class AdapterPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "approved_private_dataset.jsonl"
        self.records = [
            {
                "example_id": f"case-{i}",
                "group_id": f"shared-source-{i // 2}",
                "provenance": f"human-reviewed-{i}",
                "consent": "owner-approved-local-training",
                "messages": [
                    {"role": "user", "content": f"Question {i}?"},
                    {"role": "assistant", "content": f"Verified answer {i}."},
                ],
            }
            for i in range(10)
        ]
        self._set_records(self.records)
        self.manifest = self.root / "manifest.json"
        self.config = {
            "schema_version": 1,
            "base_model": {
                "hf_repo": "owner/reviewed-model",
                "revision_sha": "a" * 40,
                "tokenizer_revision_sha": "a" * 40,
                "chat_template_sha256": "b" * 64,
                "license_review": "local-use-reviewed-20261025",
                "gguf_base_sha256": "c" * 64,
            },
            "data": {
                "path": str(self.dataset),
                "sha256": hashlib.sha256(self.dataset.read_bytes()).hexdigest(),
                "classification": "private-local-only",
                "approval_reference": "patrick-local-20261025",
            },
            "split": {"seed": 12345, "evaluation_fraction": 0.2},
            "execution": {"allow_network": False, "allow_weight_update": False},
        }
        self._write_manifest()

    def _write_manifest(self):
        self.manifest.write_text(json.dumps(self.config), encoding="utf-8")
        self.manifest.chmod(0o600)

    def _set_records(self, records):
        self.dataset.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        self.dataset.chmod(0o600)

    def _fake_mount_info(self, extra_mount: str, filesystem: str = "9p") -> str:
        # Linux mountinfo: longest containing mount controls the real backing FS.
        return (
            "1 0 0:1 / / rw - ext4 /dev/sda rw\n"
            "2 1 0:2 / /tmp rw - overlay overlay rw\n"
            f"3 2 0:3 / {extra_mount} rw - {filesystem} C: rw\n"
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo guard")
    def test_rejects_private_corpus_on_wsl_windows_mount_despite_0600(self):
        with patch.object(
            Path, "read_text", autospec=True,
            side_effect=lambda path, *a, **k: self._fake_mount_info(str(self.root))
            if str(path) == "/proc/self/mountinfo" else self.fail(f"Unexpected file read: {path}"),
        ):
            with self.assertRaisesRegex(ValueError, "filesystem"):
                build_plan(self.manifest)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo guard")
    def test_rejects_drvfs_and_ntfs_backing_even_when_stat_reports_0600(self):
        for filesystem in ("drvfs", "ntfs3", "cifs", "fuseblk"):
            with self.subTest(filesystem=filesystem), patch.object(
                Path, "read_text", autospec=True,
                side_effect=lambda path, *a, **k: self._fake_mount_info(str(self.root), filesystem)
                if str(path) == "/proc/self/mountinfo" else self.fail(f"Unexpected file read: {path}"),
            ):
                with self.assertRaisesRegex(ValueError, "filesystem"):
                    build_plan(self.manifest)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo guard")
    def test_rejects_conflicting_stacked_mounts_at_same_path(self):
        conflicting = (
            self._fake_mount_info(str(self.root), "ext4")
            + f"4 3 0:4 / {self.root} rw - 9p C: rw\n"
        )
        with patch.object(
            Path, "read_text", autospec=True,
            side_effect=lambda path, *a, **k: conflicting
            if str(path) == "/proc/self/mountinfo" else self.fail(f"Unexpected file read: {path}"),
        ):
            with self.assertRaisesRegex(ValueError, "filesystem"):
                build_plan(self.manifest)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo guard")
    def test_accepts_private_ext4_backing_in_wsl(self):
        with patch.object(
            Path, "read_text", autospec=True,
            side_effect=lambda path, *a, **k: self._fake_mount_info(str(self.root), "ext4")
            if str(path) == "/proc/self/mountinfo" else self.fail(f"Unexpected file read: {path}"),
        ):
            self.assertEqual(build_plan(self.manifest).training_count, 8)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo guard")
    def test_unavailable_mountinfo_refuses_before_private_open(self):
        with (
            patch.object(Path, "read_text", side_effect=FileNotFoundError("mountinfo missing")),
            patch("tools.local_training.adapter_prep.os.open", side_effect=AssertionError("opened private file")),
        ):
            with self.assertRaisesRegex(ValueError, "filesystem qualification unavailable"):
                build_plan(self.manifest)

    def test_rejects_input_parent_symlink(self):
        alias = self.root.parent / (self.root.name + "-alias")
        alias.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(alias.unlink)
        with self.assertRaisesRegex(ValueError, "symlink"):
            build_plan(alias / self.manifest.name)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux mountinfo guard")
    def test_rejects_private_output_on_wsl_windows_mount_before_creation(self):
        other_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(other_tmp.cleanup)
        other_parent = Path(other_tmp.name)
        destination = other_parent / "prepared"
        with patch.object(
            Path, "read_text", autospec=True,
            side_effect=lambda path, *a, **k: self._fake_mount_info(str(other_parent))
            if str(path) == "/proc/self/mountinfo" else self.fail(f"Unexpected file read: {path}"),
        ):
            with self.assertRaisesRegex(ValueError, "filesystem"):
                write_private_splits(self.manifest, destination)
        self.assertFalse(destination.exists())

    def test_exact_source_and_dataset_yield_disjoint_reproducible_splits(self):
        first = build_plan(self.manifest)
        second = build_plan(self.manifest)
        self.assertEqual(first, second)
        self.assertEqual(first.source_revision, "a" * 40)
        self.assertEqual(first.training_count, 8)
        self.assertEqual(first.evaluation_count, 2)
        self.assertFalse(set(first.training_ids) & set(first.evaluation_ids))
        self.assertEqual(set(first.training_ids) | set(first.evaluation_ids), {f"case-{i}" for i in range(10)})
        self.assertFalse(set(first.training_group_ids) & set(first.evaluation_group_ids))

    def test_model_identity_cannot_collide_under_same_revision_string(self):
        first = build_plan(self.manifest)
        self.config["base_model"]["hf_repo"] = "another-owner/another-model"
        self._write_manifest()
        second = build_plan(self.manifest)
        self.assertNotEqual(first.base_model_binding_sha256, second.base_model_binding_sha256)
        self.assertNotEqual(first.manifest_sha256, second.manifest_sha256)

    def test_rejects_publicly_readable_private_corpus(self):
        self.dataset.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "private file permissions"):
            build_plan(self.manifest)

    def test_rejects_input_or_output_inside_any_git_checkout(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Git checkout"):
            build_plan(self.manifest)
        (self.root / ".git" / "HEAD").unlink()
        (self.root / ".git").rmdir()
        repository = self.root / "public-checkout"
        repository.mkdir()
        (repository / ".git").mkdir()
        (repository / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Git checkout"):
            write_private_splits(self.manifest, repository / "prepared")

    def test_tampered_corpus_fails_closed_before_output(self):
        self.dataset.write_text(self.dataset.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest"):
            write_private_splits(self.manifest, self.root / "prepared")
        self.assertFalse((self.root / "prepared").exists())

    def test_forbids_public_or_unauthorized_training_data(self):
        self.config["data"]["classification"] = "public-github-issue"
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "private-local-only"):
            build_plan(self.manifest)
        self.config["data"]["classification"] = "private-local-only"
        self.config["data"]["approval_reference"] = ""
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "approval"):
            build_plan(self.manifest)

    def test_rejects_unpinned_base_or_network_execution(self):
        self.config["base_model"]["revision_sha"] = "main"
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "revision"):
            build_plan(self.manifest)
        self.config["base_model"]["revision_sha"] = "a" * 40
        self.config["execution"]["allow_network"] = True
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "network"):
            build_plan(self.manifest)

    def test_rejects_dot_segments_in_model_id(self):
        self.config["base_model"]["hf_repo"] = "../model"
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "hf_repo"):
            build_plan(self.manifest)

    def test_cli_plan_is_offline_and_prints_no_sample_content(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tools.local_training", "plan", str(self.manifest)],
            text=True, capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=5,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PREPARED_ONLY_NOT_TRAINED_OR_QUALIFIED", proc.stdout)
        self.assertNotIn("Verified answer", proc.stdout)
        self.assertNotIn("owner-approved-local-training", proc.stdout)

    def test_rejects_duplicate_examples_even_with_unique_ids(self):
        self.records[-1]["messages"] = self.records[0]["messages"]
        self._set_records(self.records)
        self.config["data"]["sha256"] = hashlib.sha256(self.dataset.read_bytes()).hexdigest()
        self._write_manifest()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_plan(self.manifest)

    def test_private_write_is_exclusive_and_contains_no_model_weights(self):
        output_dir = self.root / "prepared"
        plan = write_private_splits(self.manifest, output_dir)
        self.assertEqual(len((output_dir / "train.jsonl").read_text().splitlines()), plan.training_count)
        self.assertEqual(len((output_dir / "eval.jsonl").read_text().splitlines()), plan.evaluation_count)
        self.assertTrue((output_dir / "PLAN.json").exists())
        self.assertFalse(any(path.suffix in {".safetensors", ".gguf"} for path in output_dir.iterdir()))
        before = (output_dir / "train.jsonl").read_bytes()
        with self.assertRaises(FileExistsError):
            write_private_splits(self.manifest, output_dir)
        self.assertEqual((output_dir / "train.jsonl").read_bytes(), before)

    def test_refuses_world_writable_output_parent_before_creating_private_files(self):
        output_dir = self.root / "prepared"
        self.root.chmod(0o777)
        try:
            with self.assertRaisesRegex(ValueError, "owner-only|private permissions"):
                write_private_splits(self.manifest, output_dir)
            self.assertFalse(output_dir.exists())
        finally:
            self.root.chmod(0o700)


@unittest.skipUnless(os.name == "nt", "Windows fail-closed behavior")
class WindowsPrivateACLHoldTests(unittest.TestCase):
    def test_private_preparation_refuses_before_file_probe_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_manifest = root / "private-manifest-does-not-exist.json"
            output = root / "prepared"
            # The Windows hold must run before reading even an operator-named
            # manifest, and no output directory may be created.
            with (
                patch.object(Path, "is_file", side_effect=AssertionError("private file probed")),
                patch("tools.local_training.adapter_prep.os.open", side_effect=AssertionError("private file opened")),
            ):
                with self.assertRaisesRegex(ValueError, "Windows private ACL qualification"):
                    build_plan(missing_manifest)
                with self.assertRaisesRegex(ValueError, "Windows private ACL qualification"):
                    write_private_splits(missing_manifest, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
