"""Adversarial source-pack checks with no ChatGPT Project/provider access."""

from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from tools.verify_native_project_pack import InvalidSourcePack, inspect_pack, main


def fixture(root: Path) -> dict:
    members = []
    for name, content in (
        ("PROJECT_INSTRUCTIONS.md", b"private-by-default sample\n"),
        ("CHATGPT_REPO_INTERFACE.yaml", b"status: CANDIDATE_NATIVE_PROJECT_INTERFACE\n"),
    ):
        (root / name).write_bytes(content)
        members.append({
            "filename": name, "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        })
    manifest = {
        "schema": "VERA_MONO_CHATGPT_PROJECT_PACK_V1",
        "status": "CANDIDATE_NOT_INSTALLED",
        "repository": "thebrazenbeard/vera-mono",
        "source_branch": "sample-native-branch",
        "source_head_before_manifest": "1" * 40,
        "creation_base_main": "2" * 40,
        "project_name": "Vera Mono",
        "instructions_file": "PROJECT_INSTRUCTIONS.md",
        "members": members,
        "claim_ceiling": "UPLOAD_READY_PROJECT_PACK; NOT INSTALLED; NOT RUNTIME_CONSUMED; NOT BEHAVIORALLY_QUALIFIED",
        "protected_effects_not_authorized": ["INSTALL", "DEPLOY", "CANONICAL_MEMORY_WRITE"],
    }
    save(root, manifest)
    return manifest


def save(root: Path, manifest: dict) -> None:
    (root / "PROJECT_PACK_MANIFEST.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )


class NativeProjectPackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = fixture(self.root)

    def test_exact_members_pass_but_project_not_installed(self):
        result = inspect_pack(self.root, observed_git_head="a" * 40)
        self.assertEqual(result["source_integrity"], "PASS")
        self.assertEqual(result["member_count"], 2)
        self.assertEqual(result["native_project_owner_binding"], "UNRESOLVED")
        self.assertEqual(result["native_project_installation"], "UNVERIFIED")
        self.assertFalse(result["effect_authority"])
        self.assertFalse(result["memory_authority"])
        self.assertFalse(result["head_claim_independently_verified"])

    def test_bad_member_bytes_hold_without_authority(self):
        (self.root / "PROJECT_INSTRUCTIONS.md").write_bytes(b"changed")
        result = inspect_pack(self.root)
        self.assertEqual(result["source_integrity"], "FAIL")
        self.assertEqual(result["mismatched_members"], ["PROJECT_INSTRUCTIONS.md"])
        self.assertFalse(result["effect_authority"])

    def test_missing_member_holds(self):
        (self.root / "CHATGPT_REPO_INTERFACE.yaml").unlink()
        self.assertEqual(inspect_pack(self.root)["source_integrity"], "FAIL")

    def test_duplicate_key_json_is_rejected(self):
        (self.root / "PROJECT_PACK_MANIFEST.json").write_text(
            '{"schema":"X","schema":"Y"}', encoding="utf-8"
        )
        with self.assertRaises(InvalidSourcePack):
            inspect_pack(self.root)

    def test_filename_traversal_is_rejected(self):
        self.manifest["members"][1]["filename"] = "../secrets"
        save(self.root, self.manifest)
        with self.assertRaisesRegex(InvalidSourcePack, "unsafe member"):
            inspect_pack(self.root)

    def test_case_equivalent_duplicate_member_is_rejected(self):
        cloned = deepcopy(self.manifest["members"][0])
        cloned["filename"] = cloned["filename"].lower()
        self.manifest["members"].append(cloned)
        save(self.root, self.manifest)
        with self.assertRaisesRegex(InvalidSourcePack, "duplicate"):
            inspect_pack(self.root)

    def test_future_installed_claim_cannot_promote_authority(self):
        self.manifest["status"] = "INSTALLED"
        save(self.root, self.manifest)
        with self.assertRaisesRegex(InvalidSourcePack, "installation-state"):
            inspect_pack(self.root)

    def test_unexpected_authority_key_rejected(self):
        self.manifest["effect_authority_granted"] = True
        save(self.root, self.manifest)
        with self.assertRaisesRegex(InvalidSourcePack, "root keys"):
            inspect_pack(self.root)

    def test_repo_substitution_rejected(self):
        self.manifest["repository"] = "outsider/other"
        save(self.root, self.manifest)
        with self.assertRaisesRegex(InvalidSourcePack, "repository"):
            inspect_pack(self.root)

    def test_oversize_member_rejected(self):
        (self.root / "CHATGPT_REPO_INTERFACE.yaml").write_bytes(b"a" * (256 * 1024 + 1))
        result = inspect_pack(self.root)
        self.assertEqual(result["source_integrity"], "FAIL")

    def test_symlink_member_rejected_or_held(self):
        member = self.root / "CHATGPT_REPO_INTERFACE.yaml"
        member.unlink()
        try:
            member.symlink_to(self.root / "PROJECT_INSTRUCTIONS.md")
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        result = inspect_pack(self.root)
        self.assertEqual(result["source_integrity"], "FAIL")

    def test_invalid_git_head_claim_is_rejected(self):
        with self.assertRaisesRegex(InvalidSourcePack, "Git head"):
            inspect_pack(self.root, observed_git_head="main")

    def test_exact_manifest_git_blob_pin_is_checked_but_not_install_proof(self):
        original = inspect_pack(self.root)
        pinned = inspect_pack(
            self.root, expected_manifest_blob=original["manifest_git_blob_sha1"],
        )
        self.assertTrue(pinned["manifest_blob_matches_operator_pin"])
        self.assertFalse(pinned["operator_pin_independently_verified"])
        self.assertEqual(pinned["native_project_installation"], "UNVERIFIED")
        with self.assertRaisesRegex(InvalidSourcePack, "Git blob pin"):
            inspect_pack(self.root, expected_manifest_blob="0" * 40)

    def test_cli_never_returns_runtime_success(self):
        # Source integrity PASS still exits HOLD=2: no native Project binding.
        with redirect_stdout(StringIO()) as receipt_output:
            self.assertEqual(main(["--source-root", str(self.root)]), 2)
        self.assertEqual(json.loads(receipt_output.getvalue())["runtime_consumption"], "UNVERIFIED")


class CheckedInVeraMonoPackTests(unittest.TestCase):
    def test_checked_in_project_pack_is_integral_but_not_installed(self):
        root = Path(__file__).resolve().parents[1] / "architecture" / "chatgpt"
        if not root.is_dir():
            root = Path(__file__).resolve().parents[1] / "reference"
        if not root.is_dir():
            self.skipTest("no source pack available in isolated test copy")
        result = inspect_pack(root)
        self.assertEqual(result["source_integrity"], "PASS")
        self.assertEqual(result["native_project_owner_binding"], "UNRESOLVED")
        self.assertFalse(result["effect_authority"])


if __name__ == "__main__":
    unittest.main()

