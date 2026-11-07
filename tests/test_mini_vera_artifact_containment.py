"""Adversarial parent-path races for artifact byte witness containment."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.mini_vera import artifact_binding, compose


DATA = b"GGUF" + b"z" * 64
HASH = hashlib.sha256(DATA).hexdigest()
POSIX_HANDLE_WALK = (os.name == "posix" and hasattr(os, "O_NOFOLLOW") and
                     hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd)


@unittest.skipUnless(POSIX_HANDLE_WALK, "requires POSIX openat and O_NOFOLLOW")
class ArtifactContainmentTests(unittest.TestCase):
    def fixture(self, tmp: str):
        folder = Path(tmp)
        root = folder / "artifacts"
        model_dir = root / "models"
        outside = folder / "outside"
        model_dir.mkdir(parents=True)
        outside.mkdir()
        (model_dir / "model.gguf").write_bytes(DATA)
        (outside / "model.gguf").write_bytes(DATA)
        return root, model_dir, outside

    def verify(self, root: Path):
        artifact_binding._hash_local_file(root, "models/model.gguf", len(DATA), HASH,
                                          role="base", artifact_format="GGUF")

    def test_normal_nested_file_is_verified_under_anchored_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _models, _outside = self.fixture(temp)
            self.verify(root)

    def test_existing_symlink_parent_rejected_even_with_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root, model_dir, outside = self.fixture(temp)
            model_dir.rename(root / "models-original")
            (root / "models").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(compose.CompositionRejected, "symlink"):
                self.verify(root)

    def test_existing_symlink_root_rejected_without_resolving_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _models, _outside = self.fixture(temp)
            root_link = Path(temp) / "root-link"
            root_link.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(compose.CompositionRejected, "symlink"):
                self.verify(root_link)

    def test_parent_swap_between_checks_and_open_cannot_escape_root(self):
        # Hostile reproduction: the outside file contains the exact EXPECTED
        # hash. A path-based is_symlink()+open approach falsely accepts it if
        # `models` is replaced after checking and before opening the file.
        with tempfile.TemporaryDirectory() as temp:
            root, model_dir, outside = self.fixture(temp)
            real_open = os.open
            substituted = False

            def racing_open(path, flags, *args, **kwargs):
                nonlocal substituted
                path_str = os.fspath(path)
                if not substituted and (path_str == "models" or
                                        path_str.endswith("/models/model.gguf")):
                    substituted = True
                    model_dir.rename(root / "models-original")
                    (root / "models").symlink_to(outside, target_is_directory=True)
                return real_open(path, flags, *args, **kwargs)

            # The patched callable still forwards true openat(dir_fd=...), so
            # preserve the platform capability check for this synthetic test.
            supports = set(os.supports_dir_fd) | {racing_open}
            with patch.object(artifact_binding.os, "open", racing_open), \
                    patch.object(artifact_binding.os, "supports_dir_fd", supports):
                with self.assertRaisesRegex(compose.CompositionRejected, "symlink"):
                    self.verify(root)
            self.assertTrue(substituted)

    def test_root_parent_swap_during_anchored_walk_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _model_dir, outside = self.fixture(temp)
            real_open = os.open
            substituted = False

            def racing_open(path, flags, *args, **kwargs):
                nonlocal substituted
                if not substituted and os.fspath(path) == "artifacts":
                    substituted = True
                    root.rename(Path(temp) / "artifacts-original")
                    root.symlink_to(outside, target_is_directory=True)
                return real_open(path, flags, *args, **kwargs)

            supports = set(os.supports_dir_fd) | {racing_open}
            with patch.object(artifact_binding.os, "open", racing_open), \
                    patch.object(artifact_binding.os, "supports_dir_fd", supports):
                with self.assertRaisesRegex(compose.CompositionRejected, "symlink"):
                    self.verify(root)
            self.assertTrue(substituted)


class UnsupportedHostTests(unittest.TestCase):
    def test_windows_filepath_verification_fails_closed_without_native_handle_walk(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(artifact_binding.os, "name", "nt"):
                with self.assertRaisesRegex(compose.CompositionRejected, "unsupported"):
                    artifact_binding._open_model_handle(root, ("model.gguf",))


if __name__ == "__main__":
    unittest.main()
