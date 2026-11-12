"""No-network tests for portable Mini-Vera source packaging."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import mini_vera_portable as bundle


class PortableBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()
        (self.root / "tools/mini_vera").mkdir(parents=True)
        (self.root / "tools/__init__.py").write_text("", encoding="utf-8")
        (self.root / "tools/mini_vera/__init__.py").write_text("", encoding="utf-8")
        (self.root / "tools/mini_vera/ollama_preflight.py").write_text(
            "VALUE = 1\n", encoding="utf-8"
        )
        (self.root / "scripts").mkdir()
        (self.root / "scripts/mini_vera_portable.py").write_text(
            "# fixture verifier\n", encoding="utf-8"
        )
        for relative in bundle.RESOURCE_PATHS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"public":true}\n', encoding="utf-8")
        for relative in bundle.LEGAL_PATHS:
            (self.root / relative).write_text("fixture license\n", encoding="utf-8")
        self.destination = Path(self.temp.name) / "install"

    def install(self) -> Path:
        return bundle.build(self.root, self.destination, "a" * 40)

    def test_install_and_verify_without_any_model_or_network(self) -> None:
        output = self.install()
        manifest = json.loads((output / "INSTALL.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["neural_weights_included"], False)
        self.assertEqual(manifest["model_alias"], "qwen3.5:0.8b")
        self.assertIn("mini-vera.cmd", manifest["files_sha256"])
        self.assertIn("scripts/mini_vera_portable.py", manifest["files_sha256"])
        self.assertTrue(bundle.verify(output))

    def test_detects_edited_runtime_bytes(self) -> None:
        output = self.install()
        with (output / "tools/mini_vera/ollama_preflight.py").open("a") as file:
            file.write("VALUE = 2\n")
        with self.assertRaises(bundle.BundleRefused):
            bundle.verify(output)

    def test_detects_extra_executable_module(self) -> None:
        output = self.install()
        (output / "tools/mini_vera/evil.py").write_text("print('oops')", encoding="utf-8")
        with self.assertRaises(bundle.BundleRefused):
            bundle.verify(output)

    def test_detects_unlisted_empty_directory(self) -> None:
        output = self.install()
        (output / "tools/mini_vera/unreviewed_package").mkdir()
        with self.assertRaises(bundle.BundleRefused):
            bundle.verify(output)

    def test_refuses_existing_destination_without_touching_it(self) -> None:
        self.destination.mkdir()
        sentinel = self.destination / "owner.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(bundle.BundleRefused):
            self.install()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_rejects_invalid_source_commit_claim(self) -> None:
        with self.assertRaises(bundle.BundleRefused):
            bundle.build(self.root, self.destination, "unknown")
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
