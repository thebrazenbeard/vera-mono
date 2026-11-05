"""Source-only regression tests for the retired PCCC C: root policy."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "packages/vera_pc_connection/src"))

import pc_connection
from pc_connection import path_policy


class PCCCPathRootMigrationTests(unittest.TestCase):
    def test_only_authoritative_d_root_is_lexically_readable(self) -> None:
        self.assertEqual(pc_connection.READ_ONLY_ROOTS, (r"D:\VERA",))
        self.assertEqual(tuple(path_policy.READ_ROOTS), ("VERA_ROOT",))
        self.assertEqual(str(path_policy.READ_ROOTS["VERA_ROOT"]), r"D:\VERA")
        resolved = path_policy.resolve_remote_read("VERA_ROOT", "src\\safe.txt")
        self.assertEqual(str(resolved.absolute_path), r"D:\VERA\src\safe.txt")
        self.assertEqual(resolved.root_id, "VERA_ROOT")

    def test_obsolete_user_root_and_unsafe_paths_fail_closed(self) -> None:
        for root in ("USER_VERA_ROOT", "C_ROOT", "", "user/patri"):
            with self.subTest(root=root), self.assertRaises(path_policy.PathPolicyError):
                path_policy.resolve_remote_read(root, "safe.txt")
        for relative in ("C:/VERA/private.txt", "..\\secrets.txt", "\\\\server\\share",
                         "D:/VERA", "safe.txt:ads", "CON", "file. "):
            with self.subTest(relative=relative), self.assertRaises(path_policy.PathPolicyError):
                path_policy.resolve_remote_read("VERA_ROOT", relative)

    def test_no_write_root_or_exposure_of_reserved_runtime_subtree(self) -> None:
        self.assertIsNone(pc_connection.WRITABLE_ROOT)
        self.assertIsNone(path_policy.WRITE_ROOT)
        self.assertEqual(path_policy.WRITE_ROOT_ID, "PCCC_WRITE_ROOT_V1")
        for relative in ("safe.txt", "PCCC\\file.txt", ""):
            with self.subTest(relative=relative), self.assertRaises(path_policy.PathPolicyError):
                path_policy.resolve_runtime_write(relative)
        for relative in ("PCCC", "pccc\\private.db", "PCCC/readme.txt"):
            with self.subTest(relative=relative), self.assertRaises(path_policy.PathPolicyError):
                path_policy.resolve_remote_read("VERA_ROOT", relative)

    def test_migration_contract_preserves_source_not_host_authority(self) -> None:
        contract = json.loads((REPO / "architecture/VERA_PCCC_PATH_ROOT_MIGRATION_V1.json")
                              .read_text(encoding="utf-8"))
        donor = json.loads((REPO / "provenance/donors/vera_pc_connection.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(contract["authority_root"], r"D:\VERA")
        self.assertIs(contract["host_read_authorized"], False)
        self.assertEqual(contract["write_root"], None)
        self.assertIs(contract["write_root_admitted"], False)
        self.assertIs(contract["host_write_authorized"], False)
        self.assertIn("USER_VERA_ROOT", contract["retired_aliases"])
        self.assertIn("DERIVED_LOCAL_ROOT_POLICY", donor["mode"])
        self.assertEqual(len(donor["derived_local_paths"]), 2)
        self.assertIn("NO_HOST_VERIFICATION", donor["claim_ceiling"])


if __name__ == "__main__":
    unittest.main()
