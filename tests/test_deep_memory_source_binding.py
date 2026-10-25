"""Immutable external DeepMemoryStorage source and vendored-contract binding.

This checks repository provenance without opening any historical ledger rows.
It is not evidence of a live checkout, runtime installation, or memory admission.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "packages/vera_memory/src/vera_memory/resources"
INTEGRATION = RESOURCE / "architecture/integration"
PIN = "63edbc51fb87c889ab58051d02e18ba2aeca0d24"
ARCHITECTURE_BLOB = "8fc03596e8095ebdf6a787430738512b7b5f85c5"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob_sha(contents: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(contents)).encode("ascii") + b"\0" + contents
    ).hexdigest()


class DeepMemorySourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.registry = _read_json(
            INTEGRATION / "VERA_EXTERNAL_EVIDENCE_PROVIDER_REGISTRY_V1.json"
        )
        self.contract = _read_json(
            INTEGRATION / "VERA_DEEP_MEMORY_ARCHIVE_INTEGRATION_V1.json"
        )
        self.provider = next(
            entry for entry in self.registry["providers"]
            if entry["provider_id"] == "deep_memory"
        )

    def test_registry_and_contract_pin_same_reviewed_immutable_commit(self):
        source = self.provider["source"]
        external = self.contract["external_archive"]
        self.assertEqual(source["repository"], "thebrazenbeard/deepmemorystorage")
        self.assertEqual(external["repository"], source["repository"])
        self.assertEqual(source["source_merged_commit"], PIN)
        self.assertEqual(external["source_merged_commit"], PIN)
        self.assertEqual(source["reviewed_provider_head"], PIN)
        self.assertEqual(external["reviewed_provider_head"], PIN)

    def test_vendored_files_are_byte_identical_to_declared_git_blobs(self):
        source = self.provider["source"]
        paths = set()
        source_paths = set()
        for binding in source["bindings"]:
            self.assertNotIn(binding["vendored_path"], paths)
            paths.add(binding["vendored_path"])
            source_paths.add(binding["path"])
            relative = Path(binding["vendored_path"])
            self.assertFalse(relative.is_absolute())
            self.assertEqual(relative.parts[:3], ("architecture", "integration", "vendor"))
            self.assertNotIn("..", relative.parts)
            vendor = RESOURCE / binding["vendored_path"]
            self.assertTrue(vendor.is_file())
            self.assertFalse(vendor.is_symlink())
            self.assertEqual(_git_blob_sha(vendor.read_bytes()), binding["blob"])
        self.assertEqual(
            source_paths,
            {
                "architecture/DEEP_MEMORY_ARCHITECTURE_BINDING_V1.json",
                "architecture/DEEP_MEMORY_INTEGRATION_CONTRACT_V1.md",
                "schema/DEEP_MEMORY_EVIDENCE_RESULT_V1.schema.json",
            },
        )
        self.assertEqual(len(paths), 3)
        self.assertEqual(
            self.contract["external_archive"]["required_contract_blob"],
            ARCHITECTURE_BLOB,
        )
        self.assertEqual(
            next(b["blob"] for b in source["bindings"] if
                 b["path"] == "architecture/DEEP_MEMORY_ARCHITECTURE_BINDING_V1.json"),
            ARCHITECTURE_BLOB,
        )

    def test_architecture_does_not_promote_history_or_privacy(self):
        vendor = _read_json(
            INTEGRATION / "vendor/DEEP_MEMORY_ARCHITECTURE_BINDING_V1.json"
        )
        self.assertFalse(vendor["current_authority"])
        self.assertFalse(vendor["automatic_runtime_consumption"])
        self.assertFalse(vendor["automatic_current_memory_admission"])
        self.assertFalse(vendor["automatic_consent_or_conation_promotion"])
        self.assertEqual(vendor["privacy_default"], "FAIL_CLOSED_EXACT_AUTHORIZED_SCOPE")
        self.assertEqual(vendor["retrieval_contract"]["mode"], "EVIDENCE_SEARCH")
        self.assertEqual(
            vendor["validation"]["workflow_external_action_ref_scan"],
            "ALL_EXTERNAL_USES_REFS_MUST_MATCH_PIN_REGISTRY",
        )
        self.assertEqual(self.provider["operations"], ["EVIDENCE_SEARCH"])
        self.assertFalse(self.provider["canonical_memory_transfer"])
        self.assertFalse(self.provider["execution_authorized"])
        self.assertFalse(self.provider["runtime_install_authorized"])


if __name__ == "__main__":
    unittest.main()
