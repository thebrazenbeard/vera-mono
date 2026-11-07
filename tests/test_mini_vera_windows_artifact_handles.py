"""Windows-native model witness tests; tiny synthetic GGUF only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.mini_vera import artifact_binding, compose, windows_artifact_handles


DATA = b"GGUF" + b"w" * 64
HASH = hashlib.sha256(DATA).hexdigest()


class CrossPlatformGuardTests(unittest.TestCase):
    def test_unsafe_child_names_never_enter_native_open(self):
        for bad in ("", ".", "..", "../outside", "evil\\child", "file:stream.gguf",
                    "nul", "COM1.gguf", "abc. ", "a\0b"):
            with self.subTest(bad=bad), self.assertRaises(compose.CompositionRejected):
                windows_artifact_handles._component(bad)

    @unittest.skipIf(sys.platform == "win32", "native Windows path tested separately")
    def test_non_windows_native_api_refuses_without_downshift(self):
        with self.assertRaisesRegex(compose.CompositionRejected, "unsupported"):
            windows_artifact_handles.open_relative_no_reparse(Path("/tmp"), ("file.gguf",))


@unittest.skipUnless(sys.platform == "win32" and os.name == "nt", "requires real Windows native handles")
class WindowsHandleWalkTests(unittest.TestCase):
    def verify(self, root: Path, relative: str = "models/model.gguf") -> None:
        artifact_binding._hash_local_file(root, relative, len(DATA), HASH,
                                          role="base", artifact_format="GGUF")

    def fixture(self, tmp: str) -> tuple[Path, Path]:
        root = Path(tmp) / "allowed"
        model_dir = root / "models"
        model_dir.mkdir(parents=True)
        (model_dir / "model.gguf").write_bytes(DATA)
        outside = Path(tmp) / "outside"
        outside.mkdir()
        (outside / "model.gguf").write_bytes(DATA)  # hostile identical SHA
        return root, outside

    def make_junction(self, link: Path, target: Path) -> None:
        # `mklink /J` is available to normal Windows users on NTFS. If the CI
        # runner's temp volume forbids junctions, report the attack test skipped.
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            self.skipTest("Windows temporary filesystem cannot create a junction")

    def test_native_walk_opens_tiny_file_with_no_reparse(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            self.verify(root)

    def test_parent_junction_to_identical_outside_bytes_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, outside = self.fixture(temp)
            (root / "models").rename(root / "models-original")
            self.make_junction(root / "models", outside)
            with self.assertRaisesRegex(compose.CompositionRejected, "reparse"):
                self.verify(root)

    def test_model_root_ancestor_junction_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, outside = self.fixture(temp)
            alias = Path(temp) / "alias"
            self.make_junction(alias, root)
            with self.assertRaisesRegex(compose.CompositionRejected, "reparse"):
                self.verify(alias)

    def test_final_model_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, outside = self.fixture(temp)
            (root / "models" / "model.gguf").unlink()
            try:
                (root / "models" / "model.gguf").symlink_to(outside / "model.gguf")
            except OSError:
                self.skipTest("Windows runner lacks symlink capability")
            with self.assertRaisesRegex(compose.CompositionRejected, "reparse"):
                self.verify(root)

    def test_unc_and_device_roots_fail_closed(self):
        for pathname in (r"\\server\share\models", r"\\?\C:\models"):
            with self.subTest(path=pathname), self.assertRaisesRegex(
                    compose.CompositionRejected, "UNC/device"):
                windows_artifact_handles._drive_and_components(Path(pathname), ("model.gguf",))


if __name__ == "__main__":
    unittest.main()
