"""Offline binding acceptance tests; synthetic bytes are not official model weights."""

import hashlib
import io
import json
import os
import stat
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.local_training.bind_source import bind_private_model_snapshot, main
from tools.local_training.lora_runner import _model_snapshot


REV = "a" * 40
TOKEN_REV = "b" * 40
TEMPLATE = "{{ message.content }}"
TEMPLATE_SHA = hashlib.sha256(TEMPLATE.encode()).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _safetensors(payload=b"\0\0\0\0") -> bytes:
    header = json.dumps({"foo": {"dtype": "F32", "shape": [1], "data_offsets": [0, len(payload)]}}).encode()
    return struct.pack("<Q", len(header)) + header + payload


@unittest.skipUnless(sys.platform.startswith("linux"), "binding acceptance requires a private Linux filesystem")
class LocalSnapshotBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vera-binding-")
        self.addCleanup(self.temp.cleanup)
        self.model = Path(self.temp.name) / "model"
        self.model.mkdir(mode=0o700)
        _write(self.model / "config.json", b'{"model_type":"qwen3"}')
        _write(self.model / "tokenizer.json", b'{"version":"1.0"}')
        _write(self.model / "tokenizer_config.json", json.dumps({"chat_template": TEMPLATE}).encode())
        _write(self.model / "model.safetensors", _safetensors())
        self.arguments = {
            "hf_repo": "Qwen/Qwen3-0.6B", "revision_sha": REV,
            "tokenizer_revision_sha": TOKEN_REV,
            "expected_chat_template_sha256": TEMPLATE_SHA,
            "origin_evidence_ref": "sha256:" + "c" * 64,
        }

    def bind(self):
        return bind_private_model_snapshot(self.model, **self.arguments)

    def assert_rejected(self):
        with self.assertRaises((ValueError, OSError)):
            self.bind()
        self.assertFalse((self.model / "VERA_SOURCE.json").exists())

    def test_valid_private_snapshot_writes_exact_manifest_and_runner_accepts(self):
        result = self.bind()
        self.assertEqual(result.status, "DECLARED_ORIGIN_BYTES_HASHED_ONLY")
        marker = self.model / "VERA_SOURCE.json"
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        data = json.loads(marker.read_text())
        self.assertEqual(set(data), {
            "schema_version", "hf_repo", "revision_sha", "tokenizer_revision_sha",
            "chat_template_sha256", "files_sha256",
        })
        self.assertEqual(data["chat_template_sha256"], TEMPLATE_SHA)
        self.assertEqual(data["files_sha256"]["model.safetensors"],
                         hashlib.sha256((self.model / "model.safetensors").read_bytes()).hexdigest())
        self.assertEqual(result.binding_sha256,
                         _model_snapshot(self.model, {
                             "hf_repo": "Qwen/Qwen3-0.6B", "revision_sha": REV,
                             "tokenizer_revision_sha": TOKEN_REV,
                             "chat_template_sha256": TEMPLATE_SHA,
                         }))
        self.assertNotIn("origin_evidence_ref", data)

    def test_offline_cli_emits_digest_receipt_without_private_path(self):
        output = io.StringIO()
        argv = [
            "--model-dir", str(self.model),
            "--hf-repo", self.arguments["hf_repo"],
            "--revision-sha", REV,
            "--tokenizer-revision-sha", TOKEN_REV,
            "--chat-template-sha256", TEMPLATE_SHA,
            "--origin-evidence-ref", self.arguments["origin_evidence_ref"],
        ]
        with redirect_stdout(output):
            self.assertEqual(main(argv), 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "DECLARED_ORIGIN_BYTES_HASHED_ONLY")
        self.assertNotIn(str(self.model), output.getvalue())
        self.assertNotIn("origin_evidence_ref", output.getvalue())

    def test_does_not_overwrite_existing_binding(self):
        self.bind()
        with self.assertRaises(ValueError):
            self.bind()

    def test_declared_revision_and_template_hash_required(self):
        for name, value in (("revision_sha", "main"),
                            ("tokenizer_revision_sha", ""),
                            ("expected_chat_template_sha256", "0" * 64),
                            ("origin_evidence_ref", " "),
                            ("hf_repo", "unknown/model")):
            with self.subTest(name=name):
                original = self.arguments[name]
                self.arguments[name] = value
                self.assert_rejected()
                self.arguments[name] = original

    def test_rejects_unlisted_extension_and_directories(self):
        for filename in ("model.gguf", "pytorch_model.bin", "README.md"):
            with self.subTest(filename=filename):
                bad = self.model / filename
                _write(bad, b"unsupported")
                self.assert_rejected()
                bad.unlink()
        subdir = self.model / "child"
        subdir.mkdir(mode=0o700)
        self.assert_rejected()

    def test_rejects_symlinks_hardlinks_and_public_permissions(self):
        original = self.model / "model.safetensors"
        original.rename(self.model / "private-weights")
        original.symlink_to(self.model / "private-weights")
        self.assert_rejected()
        original.unlink()
        (self.model / "private-weights").rename(original)
        link = self.model / "second-copy"
        os.link(original, link)
        self.assert_rejected()
        link.unlink()
        original.chmod(0o644)
        self.assert_rejected()
        original.chmod(0o600)
        self.model.chmod(0o755)
        self.assert_rejected()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_rejects_nonregular_fifo_without_blocking(self):
        os.mkfifo(self.model / "vocab.json", 0o600)
        self.assert_rejected()

    def test_rejects_fake_and_malformed_safetensors(self):
        path = self.model / "model.safetensors"
        for payload in (
            b"version https://git-lfs.github.com/spec/v1\n",
            b"GGUF" + b"x" * 80,
            b"too short",
            struct.pack("<Q", 10) + b"{}",
            struct.pack("<Q", 2) + b"{}" + b"garbage",
            struct.pack("<Q", 999_999_999) + b"{}",
            _safetensors().replace(b'"data_offsets": [0, 4]', b'"data_offsets": [0, 9]'),
        ):
            with self.subTest(payload=payload[:8]):
                _write(path, payload)
                self.assert_rejected()

    def test_rejects_overlapping_and_duplicate_safetensors_descriptors(self):
        path = self.model / "model.safetensors"
        for header in (
            b'{"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]},"b":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}',
            b'{"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]},"a":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}',
        ):
            with self.subTest(header=header[-32:]):
                _write(path, struct.pack("<Q", len(header)) + header + b"\0\0\0\0")
                self.assert_rejected()

    def test_rejects_unknown_dtype_and_shape_size_mismatch(self):
        path = self.model / "model.safetensors"
        for dtype, shape in (("EVIL", [1]), ("F32", [200]), ("BF16", [3]), ("F32", [])):
            with self.subTest(dtype=dtype, shape=shape):
                header = json.dumps({
                    "foo": {"dtype": dtype, "shape": shape, "data_offsets": [0, 4]},
                }).encode()
                _write(path, struct.pack("<Q", len(header)) + header + b"\0\0\0\0")
                if dtype == "F32" and shape == []:
                    # Valid scalar tensor is accepted.
                    self.bind()
                    (self.model / "VERA_SOURCE.json").unlink()
                else:
                    self.assert_rejected()

    def test_post_write_verification_failure_removes_only_new_marker(self):
        with patch("tools.local_training.bind_source._model_snapshot", side_effect=ValueError("verification failed")):
            self.assert_rejected()
        self.assertTrue((self.model / "model.safetensors").exists())

    def test_bad_architecture_and_missing_required_files_rejected(self):
        config = self.model / "config.json"
        _write(config, b'{"model_type":"other"}')
        self.assert_rejected()
        _write(config, b'{"model_type":"qwen3"}')
        config.unlink()
        self.assert_rejected()

    def test_unqualified_filesystem_rejected(self):
        with patch("tools.local_training.bind_source._require_private_filesystem", side_effect=ValueError("DrVFs")):
            self.assert_rejected()


class NativeWindowsSafetyHoldTests(unittest.TestCase):
    """Runs on every CI OS; simulates Windows without touching private files."""

    def test_windows_fails_closed_before_any_filesystem_access(self):
        with (patch("tools.local_training.bind_source.sys.platform", "win32"),
              patch("tools.local_training.bind_source._require_private_filesystem") as filesystem_probe,
              patch("tools.local_training.bind_source._reject_git_checkout") as checkout_probe,
              patch("tools.local_training.bind_source.os.open") as private_open,
              patch("tools.local_training.bind_source._model_snapshot") as snapshot_probe):
            with self.assertRaisesRegex(ValueError, "qualified local Linux filesystem"):
                bind_private_model_snapshot(
                    Path("/never-read-source-files"),
                    hf_repo="Qwen/Qwen3-0.6B",
                    revision_sha=REV,
                    tokenizer_revision_sha=TOKEN_REV,
                    expected_chat_template_sha256=TEMPLATE_SHA,
                    origin_evidence_ref="sha256:" + "c" * 64,
                )
            filesystem_probe.assert_not_called()
            checkout_probe.assert_not_called()
            private_open.assert_not_called()
            snapshot_probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
