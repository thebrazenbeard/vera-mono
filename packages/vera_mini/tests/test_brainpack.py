"""Tests for explicit, immutable, bounded BrainPack document transport."""

from __future__ import annotations

import hashlib
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mini_vera.brainpack import BrainPack, BrainPackError, build_brainpack


class BrainPackTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.sources = self.base / "sources"
        self.sources.mkdir()
        self.out = self.base / "pack"

    def put(self, name: str, data: str) -> Path:
        path = self.sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        return path

    def test_tiny_public_corpus_roundtrip_provenance_and_determinism(self):
        one = self.put("public/astronomy.md", "Earth orbits the Sun.\n")
        self.put("public/biology.txt", "Plants use sunlight.\n")
        first = build_brainpack(self.sources, ["public/biology.txt", "public/astronomy.md"], self.out)
        pack = BrainPack(self.out)
        self.assertEqual(pack.paths, ("public/astronomy.md", "public/biology.txt"))
        self.assertEqual(pack.read("public/astronomy.md"), "Earth orbits the Sun.\n")
        self.assertEqual(pack.verify()["verified_documents"], 2)
        self.assertEqual(first["documents"][0]["sha256"], hashlib.sha256(one.read_bytes()).hexdigest())
        other = self.base / "pack2"
        self.assertEqual(first, build_brainpack(self.sources,
                         ["public/astronomy.md", "public/biology.txt"], other))
        self.assertEqual((self.out / "manifest.json").read_bytes(),
                         (other / "manifest.json").read_bytes())

    def test_no_ambient_discovery_and_no_unallowlisted_read(self):
        self.put("public.txt", "Selected public text")
        self.put("private.txt", "Not selected")
        build_brainpack(self.sources, ["public.txt"], self.out)
        pack = BrainPack(self.out)
        self.assertEqual(pack.paths, ("public.txt",))
        with self.assertRaises(BrainPackError):
            pack.read("private.txt")

    def test_rejects_traversal_hidden_absolute_and_duplicate_paths(self):
        self.put("ok.txt", "ok")
        for files in (["../secret.txt"], ["/etc/passwd"], [".secret.txt"],
                      ["a//b.txt"], ["a/./b.txt"], ["ok.txt", "ok.txt"]):
            with self.subTest(files=files), self.assertRaises(BrainPackError):
                build_brainpack(self.sources, files, self.out)
            self.assertFalse(self.out.exists())
        with self.assertRaises(BrainPackError):
            build_brainpack(self.sources / ".." / "sources", ["ok.txt"], self.out)

    def test_rejects_symlink_and_hardlink_sources(self):
        private = self.base / "private.txt"
        private.write_text("do not ingest", encoding="utf-8")
        (self.sources / "linked.txt").symlink_to(private)
        (self.sources / "hardlinked.txt").hardlink_to(private)
        for name in ("linked.txt", "hardlinked.txt"):
            with self.subTest(name=name), self.assertRaises(BrainPackError):
                build_brainpack(self.sources, [name], self.out)
        folder = self.base / "different"
        folder.mkdir()
        (folder / "item.txt").write_text("linked directory", encoding="utf-8")
        (self.sources / "alias").symlink_to(folder, target_is_directory=True)
        with self.assertRaises(BrainPackError):
            build_brainpack(self.sources, ["alias/item.txt"], self.out)

    def test_budget_failure_leaves_no_partial_pack(self):
        self.put("huge.txt", "X" * 500)
        with self.assertRaises(BrainPackError):
            build_brainpack(self.sources, ["huge.txt"], self.out, max_file_bytes=100)
        self.assertFalse(self.out.exists())
        with self.assertRaises(BrainPackError):
            build_brainpack(self.sources, ["huge.txt"], self.out, max_pack_bytes=100)
        self.assertFalse(self.out.exists())

    def test_blob_tampering_detected_on_read_and_verify(self):
        self.put("note.md", "A public educational note.")
        manifest = build_brainpack(self.sources, ["note.md"], self.out)
        pack = BrainPack(self.out)
        blob = self.out / manifest["documents"][0]["blob"]
        blob.write_bytes(b"forged")
        with self.assertRaises(BrainPackError):
            pack.read("note.md")
        with self.assertRaises(BrainPackError):
            pack.verify()

    def test_existing_destination_is_never_replaced(self):
        self.put("note.md", "public")
        self.out.mkdir()
        marker = self.out / "marker"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaises(BrainPackError):
            build_brainpack(self.sources, ["note.md"], self.out)
        self.assertEqual(marker.read_text(), "keep")

    def test_destination_appearing_during_build_is_refused(self):
        self.put("note.md", "public")
        compress = gzip.compress

        def competing_creation(*args, **kwargs):
            self.out.mkdir()
            (self.out / "owned-by-other").write_text("keep", encoding="utf-8")
            return compress(*args, **kwargs)

        with patch("mini_vera.brainpack.gzip.compress", side_effect=competing_creation):
            with self.assertRaises(BrainPackError):
                build_brainpack(self.sources, ["note.md"], self.out)
        self.assertEqual((self.out / "owned-by-other").read_text(), "keep")
        self.assertEqual(list(self.base.glob(".brainpack-build-*")), [])

    def test_unsupported_secure_dir_fd_platform_fails_closed(self):
        self.put("note.md", "public")
        with patch("mini_vera.brainpack.os.supports_dir_fd", set()):
            with self.assertRaisesRegex(BrainPackError, "unavailable on this platform"):
                build_brainpack(self.sources, ["note.md"], self.out)
        self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
