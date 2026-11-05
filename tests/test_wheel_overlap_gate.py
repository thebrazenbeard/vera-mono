"""Contract tests for fail-closed wheel site-packages ownership preflight."""

import base64
import csv
from pathlib import Path
import hashlib
from io import StringIO
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile
from contextlib import redirect_stderr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_wheel_overlap
from check_wheel_overlap import InvalidWheel, _installed_path, compare


class WheelOverlapGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def wheel(self, filename: str, *paths: str, wrong_hash=False,
              malformed_size=False) -> Path:
        wheel = self.root / filename
        owner = filename.removesuffix(".whl") + "-1.dist-info"
        wheel_meta = owner + "/WHEEL"
        pkg_meta = owner + "/METADATA"
        record = owner + "/RECORD"
        wheel_body = ("Wheel-Version: 1.0\nGenerator: test\n"
                      "Root-Is-Purelib: true\nTag: py3-none-any\n")
        contents = [(path, path.encode("utf-8")) for path in paths]
        contents += [(wheel_meta, wheel_body.encode("utf-8")),
                     (pkg_meta, b"Metadata-Version: 2.1\nName: fixture\nVersion: 1.0\n")]
        record_text = StringIO()
        writer = csv.writer(record_text, lineterminator="\n")
        for i, (name, data) in enumerate(contents):
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            if wrong_hash and i == 0:
                digest = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode()
            writer.writerow([name, "sha256=" + digest,
                             "9" * 5000 if malformed_size and i == 0 else len(data)])
        writer.writerow([record, "", ""])
        with ZipFile(wheel, "w") as archive:
            for name, data in contents:
                archive.writestr(name, data)
            archive.writestr(record, record_text.getvalue())
        return wheel

    def test_disjoint_packages_pass(self):
        a = self.wheel("a.whl", "alpha/__init__.py")
        b = self.wheel("b.whl", "beta/__init__.py")
        result = compare(a, b)
        self.assertEqual(result["status"], "DISJOINT")
        self.assertEqual(result["overlap_count"], 0)

    def test_same_installed_path_fails_even_when_archive_data_identical(self):
        a = self.wheel("a.whl", "ingest/storage.py")
        b = self.wheel("b.whl", "ingest/storage.py")
        result = compare(a, b)
        self.assertEqual(result["status"], "COLLISION")
        self.assertEqual(result["overlapping_site_paths"], ["ingest/storage.py"])

    def test_data_purelib_matches_normal_package_root(self):
        a = self.wheel("a.whl", "wheel_a.data/purelib/ingest/storage.py")
        b = self.wheel("b.whl", "ingest/storage.py")
        self.assertEqual(compare(a, b)["overlap_count"], 1)

    def test_invalid_path_is_denied(self):
        for path in ("../ingest/storage.py", "/ingest/storage.py", "ingest\\storage.py",
                     "ingest//storage.py", "ingest/./storage.py", "C:/ingest/storage.py",
                     "ingest/storage.py:alternate", "CON/file.txt", "ingest/foo."):
            with self.subTest(path=path):
                self.assertRaises(InvalidWheel, _installed_path, path)

    def test_distribution_metadata_paths_also_cannot_be_dual_owned(self):
        a = self.wheel("a.whl", "shared-1.dist-info/other.txt")
        b = self.wheel("b.whl", "shared-1.dist-info/other.txt")
        self.assertEqual(compare(a, b)["overlap_count"], 1)

    def test_duplicate_archive_entry_is_denied(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            a = self.wheel("a.whl", "ingest/storage.py", "ingest/storage.py")
        b = self.wheel("b.whl", "beta/__init__.py")
        with self.assertRaises(InvalidWheel):
            compare(a, b)

    def test_windows_casefold_and_unicode_nfc_nfd_collisions(self):
        a = self.wheel("a.whl", "Ingest/Caf\u00e9.py")
        b = self.wheel("b.whl", "ingest/Cafe\u0301.py")
        result = compare(a, b)
        self.assertEqual(result["status"], "COLLISION")
        self.assertEqual(result["overlapping_site_paths"], ["ingest/caf\u00e9.py"])
        self.assertEqual(result["path_key_policy"], "NFC_CASEFOLD_PORTABLE")

    def test_same_wheel_portable_alias_is_invalid(self):
        a = self.wheel("a.whl", "Ingest/Caf\u00e9.py", "ingest/Cafe\u0301.py")
        b = self.wheel("b.whl", "beta/__init__.py")
        with self.assertRaises(InvalidWheel):
            compare(a, b)

    def test_unsafe_directory_entry_is_invalid(self):
        for unsafe in ("../", "C:/", "ingest/../", "ingest\\", "NUL/"):
            with self.subTest(unsafe=unsafe):
                a = self.wheel("a.whl", unsafe, "alpha/__init__.py")
                b = self.wheel("b.whl", "beta/__init__.py")
                with self.assertRaises(InvalidWheel):
                    compare(a, b)

    def test_missing_or_inconsistent_wheel_metadata_is_invalid(self):
        a = self.root / "bad.whl"
        b = self.wheel("b.whl", "beta/__init__.py")
        with ZipFile(a, "w") as archive:
            archive.writestr("alpha/__init__.py", "alpha")
        with self.assertRaises(InvalidWheel):
            compare(a, b)

    def test_missing_dist_info_metadata_is_invalid_not_disjoint(self):
        a = self.root / "missing-metadata.whl"
        b = self.wheel("b.whl", "beta/__init__.py")
        with ZipFile(a, "w") as archive:
            archive.writestr("missing-1.dist-info/WHEEL",
                             "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n")
            archive.writestr("missing-1.dist-info/RECORD", "missing-1.dist-info/RECORD,,\n")
        with self.assertRaises(InvalidWheel):
            compare(a, b)

    def test_record_wrong_sha256_is_invalid_not_disjoint(self):
        a = self.wheel("a.whl", "alpha/__init__.py", wrong_hash=True)
        b = self.wheel("b.whl", "beta/__init__.py")
        with self.assertRaises(InvalidWheel):
            compare(a, b)

    def test_unbounded_record_size_is_structured_invalid_not_traceback(self):
        a = self.wheel("a.whl", "alpha/__init__.py", malformed_size=True)
        b = self.wheel("b.whl", "beta/__init__.py")
        with self.assertRaises(InvalidWheel):
            compare(a, b)
        stderr = StringIO()
        with redirect_stderr(stderr):
            exit_code = check_wheel_overlap.main([str(a), str(b)])
        self.assertEqual(exit_code, 2)
        self.assertIn('"status": "INVALID"', stderr.getvalue())

    def test_unsupported_zip_compression_reports_invalid_exit_two(self):
        a = self.wheel("a.whl", "alpha/__init__.py")
        b = self.wheel("b.whl", "beta/__init__.py")
        raw = bytearray(a.read_bytes())
        local = raw.find(b"PK\x03\x04")
        central = raw.find(b"PK\x01\x02")
        self.assertGreaterEqual(min(local, central), 0)
        raw[local + 8:local + 10] = (99).to_bytes(2, "little")
        raw[central + 10:central + 12] = (99).to_bytes(2, "little")
        a.write_bytes(raw)
        stderr = StringIO()
        with redirect_stderr(stderr):
            exit_code = check_wheel_overlap.main([str(a), str(b)])
        self.assertEqual(exit_code, 2)
        self.assertIn('"status": "INVALID"', stderr.getvalue())
        a = self.wheel("bad.whl", "alpha/__init__.py")
        with ZipFile(a, "a") as archive:
            archive.writestr("unrecorded.txt", "not in RECORD")
        with self.assertRaises(InvalidWheel):
            compare(a, b)

    def test_byte_snapshot_binds_digest_to_original_inventory_under_mutation(self):
        a = self.wheel("a.whl", "ingest/storage.py")
        b = self.wheel("b.whl", "ingest/storage.py")
        digest_before = hashlib.sha256(a.read_bytes()).hexdigest()
        replacement = self.wheel("replacement.whl", "alpha/__init__.py").read_bytes()
        original_read = check_wheel_overlap._read_wheel_bytes

        def mutate_after_read(path):
            raw = original_read(path)
            if path == a:
                a.write_bytes(replacement)
            return raw

        with patch.object(check_wheel_overlap, "_read_wheel_bytes",
                          side_effect=mutate_after_read):
            result = compare(a, b)
        self.assertEqual(result["status"], "COLLISION")
        self.assertEqual(result["wheels"][0]["sha256"], digest_before)
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(),
                         hashlib.sha256(replacement).hexdigest())


if __name__ == "__main__":
    unittest.main()
