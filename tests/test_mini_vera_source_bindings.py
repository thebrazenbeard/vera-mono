"""Effectless model-byte and ledger-source Mini-Vera integration tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for package in ("vera_memory", "portfolio_runtime"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger  # noqa: E402
from tools.mini_vera import artifact_binding, compose, ledger_bridge  # noqa: E402


KEY = b"synthetic-integrity-test-key-32x"[:32]


def model_fixture(folder: Path, *, adapter_format: str = "GGUF"):
    model_root = folder / "artifacts"
    model_root.mkdir()
    base = b"GGUF" + b"\0" * 64
    adapter = (b"GGUF" + b"\0" * 40) if adapter_format == "GGUF" else (
        (16).to_bytes(8, "little") + b'{"__metadata__":{}}' + b"\0" * 40)
    adapter_name = "adapter.gguf" if adapter_format == "GGUF" else "adapter.safetensors"
    (model_root / "base.gguf").write_bytes(base)
    (model_root / adapter_name).write_bytes(adapter)
    artifacts = [
        {"role": "base", "format": "GGUF", "path": "base.gguf", "bytes": len(base), "sha256": compose.sha256(base)},
        {"role": "adapter", "format": adapter_format, "path": adapter_name, "bytes": len(adapter), "sha256": compose.sha256(adapter)},
    ]
    manifest = {"schema": "MINI_VERA_LOCAL_MODEL_MANIFEST_V1", "model_alias": "mini-vera:synthetic",
                "artifacts": artifacts}
    path = folder / "manifest.json"
    raw = compose.canonical(manifest)
    path.write_bytes(raw)
    return model_root, path, compose.sha256(raw), manifest


def ledger_fixture(folder: Path):
    ledger = MemoryLedger(folder / "memory.sqlite", project_id="vera-mono", identity_id="vera")
    request = AdmissionRequest(
        record_id="work-1", text="Synthetic public project milestone; not present-day truth.",
        memory_class=MemoryClass.WORKING_PROJECT, source_actor="test-fixture",
        authority_ref="synthetic-approved", privacy_ref="PUBLIC",
        provenance_refs=("synthetic-source",), operation_id="synthetic-1",
        project_id="vera-mono", governed_identity_id="vera",
    )
    receipt = ledger.admit(request, expected_head=ledger.current_head)
    return ledger, receipt["store_head"]


def synthetic_composer_args(state: dict, revision: int):
    ident, ident_raw = compose.read_object(compose.IDENTITY_PATH, 16_384)
    behavior, behavior_raw = compose.read_object(compose.BEHAVIOR_PATH, 16_384)
    return {
        "identity": ident, "identity_raw": ident_raw,
        "behavior": behavior, "behavior_raw": behavior_raw,
        "expected_identity_sha256": compose.sha256(ident_raw),
        "expected_behavior_sha256": compose.sha256(behavior_raw),
        "state": state, "key": KEY, "expected_revision": revision,
        "turn": {"schema": "MINI_VERA_SYNTHETIC_TURN_V1", "turn_id": "synthetic-1",
                 "scope": "SYNTHETIC_ONLY", "user_text": "Which project statements are verified?"},
    }


def synthetic_approval(record, head):
    # A real host must independently verify these refs against policy/current
    # authorization; strings in the fixture are deliberately not real grants.
    return (record.privacy_ref == "PUBLIC" and record.authority_ref == "synthetic-approved"
            and len(head) == 64)


class MiniVeraBindingTests(unittest.TestCase):
    def test_pinned_model_bytes_and_ledger_state_feed_existing_composer(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            model_root, manifest, digest, _ = model_fixture(folder)
            ledger, head = ledger_fixture(folder)
            state, receipt = ledger_bridge.project_existing_ledger(
                ledger, record_ids=["work-1"], expected_head=head, expected_revision=9,
                integrity_key=KEY, host_public_project_approval=synthetic_approval,
            )
            self.assertEqual("SOURCE_PROJECTION_ONLY_NOT_PRIVACY_OR_HOST_ATTESTATION", receipt["evidence"])
            self.assertEqual(0, receipt["writes"])
            self.assertEqual("ledger:" + head, state["source_id"])
            projected, _ = compose.verify_state(state, key=KEY, expected_revision=9)
            self.assertEqual("UNVERIFIED_CONTEXT_DATA", projected[0]["trust"])
            composed = artifact_binding.compose_with_local_manifest(
                model_root=model_root, model_manifest=manifest, expected_manifest_sha256=digest,
                **synthetic_composer_args(state, 9),
            )
            self.assertEqual("mini-vera:synthetic", composed["inference"]["model"])
            self.assertEqual("LOCAL_BYTES_MATCH_DECLARED_MANIFEST_ONLY", composed["evidence"]["local_model_bytes"])
            self.assertEqual("NOT_ATTESTED", composed["evidence"]["resident_model_identity"])
            self.assertEqual(0, composed["evidence"]["model_calls"])
            self.assertEqual("NONE", composed["evidence"]["authority_effect"])
            self.assertNotIn(str(model_root), json.dumps(composed))

    def test_stale_head_and_superseded_record_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger, old_head = ledger_fixture(Path(temp))
            ledger.admit(AdmissionRequest(
                record_id="work-2", text="corrected", memory_class=MemoryClass.WORKING_PROJECT,
                source_actor="test-fixture", authority_ref="synthetic-approved",
                privacy_ref="PUBLIC", provenance_refs=("synthetic-source",),
                operation_id="synthetic-2", project_id="vera-mono", governed_identity_id="vera",
                supersedes="work-1"), expected_head=old_head)
            new_head = ledger.current_head
            with self.assertRaisesRegex(compose.CompositionRejected, "head drift"):
                ledger_bridge.project_existing_ledger(
                    ledger, record_ids=["work-1"], expected_head=old_head,
                    expected_revision=1, integrity_key=KEY, host_public_project_approval=synthetic_approval)
            with self.assertRaisesRegex(compose.CompositionRejected, "superseded"):
                ledger_bridge.project_existing_ledger(
                    ledger, record_ids=["work-1"], expected_head=new_head,
                    expected_revision=2, integrity_key=KEY, host_public_project_approval=synthetic_approval)

    def test_private_ref_not_silently_reclassified_public(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = MemoryLedger(Path(temp) / "memory.sqlite", project_id="vera-mono", identity_id="vera")
            ledger.admit(AdmissionRequest(
                record_id="private-1", text="Should not be exported.",
                memory_class=MemoryClass.WORKING_PROJECT, source_actor="test-fixture",
                authority_ref="synthetic-approved", privacy_ref="PRIVATE",
                provenance_refs=("synthetic-source",), operation_id="private-op",
                project_id="vera-mono", governed_identity_id="vera"), expected_head=ledger.current_head)
            with self.assertRaisesRegex(compose.CompositionRejected, "stored privacy class"):
                ledger_bridge.project_existing_ledger(
                    ledger, record_ids=["private-1"], expected_head=ledger.current_head,
                    expected_revision=1, integrity_key=KEY, host_public_project_approval=synthetic_approval)
            with self.assertRaisesRegex(compose.CompositionRejected, "stored privacy class"):
                ledger_bridge.project_existing_ledger(
                    ledger, record_ids=["private-1"], expected_head=ledger.current_head,
                    expected_revision=9999, integrity_key=KEY,
                    host_public_project_approval=lambda record, head: True)
            with self.assertRaisesRegex(compose.CompositionRejected, "callback required"):
                ledger_bridge.project_existing_ledger(
                    ledger, record_ids=["private-1"], expected_head=ledger.current_head,
                    expected_revision=1, integrity_key=KEY, host_public_project_approval=None)

    def test_manifest_drift_corrupted_weights_symlink_and_duplicate_role_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            root, manifest, expected, value = model_fixture(folder)
            result = artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256=expected)
            self.assertEqual(2, len(result["artifacts"]))
            self.assertEqual("NOT_ATTESTED", result["resident_model_identity"])
            with self.assertRaisesRegex(compose.CompositionRejected, "manifest source drift"):
                artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256="0" * 64)
            (root / "base.gguf").write_bytes(b"GGUF" + b"x" * 64)
            with self.assertRaisesRegex(compose.CompositionRejected, "bytes do not match"):
                artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256=expected)
            (root / "base.gguf").unlink()
            (root / "base.gguf").symlink_to(root / value["artifacts"][1]["path"])
            with self.assertRaisesRegex(compose.CompositionRejected, "symlink"):
                artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256=expected)
            (root / "base.gguf").unlink()
            (root / "base.gguf").write_bytes(b"GGUF" + b"\0" * 64)
            value["artifacts"][1]["role"] = "base"
            new_raw = compose.canonical(value)
            manifest.write_bytes(new_raw)
            with self.assertRaisesRegex(compose.CompositionRejected, "duplicate"):
                artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256=compose.sha256(new_raw))

    def test_optional_safetensors_and_format_extension_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            root, manifest, digest, value = model_fixture(folder, adapter_format="SAFETENSORS")
            self.assertEqual("SAFETENSORS", artifact_binding.verify_local_manifest(
                root, manifest, expected_manifest_sha256=digest)["artifacts"][1]["format"])
            value["artifacts"][1]["format"] = "GGUF"
            raw = compose.canonical(value)
            manifest.write_bytes(raw)
            with self.assertRaisesRegex(compose.CompositionRejected, "extension"):
                artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256=compose.sha256(raw))

    def test_combined_three_gb_limit_before_any_artifact_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root, manifest, _, value = model_fixture(Path(temp))
            value["artifacts"][0]["bytes"] = 2_990_000_000
            value["artifacts"][1]["bytes"] = 20_000_000
            raw = compose.canonical(value)
            manifest.write_bytes(raw)
            with self.assertRaisesRegex(compose.CompositionRejected, "total model byte budget"):
                artifact_binding.verify_local_manifest(root, manifest, expected_manifest_sha256=compose.sha256(raw))

    def test_effectless_public_scope_changes_cannot_bypass_composer(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            root, manifest, digest, _ = model_fixture(folder)
            ledger, head = ledger_fixture(folder)
            state, _ = ledger_bridge.project_existing_ledger(
                ledger, record_ids=["work-1"], expected_head=head, expected_revision=4,
                integrity_key=KEY, host_public_project_approval=synthetic_approval)
            request = synthetic_composer_args(state, 4)
            request["turn"]["scope"] = "PRIVATE_CHAT_EXPORT"
            with self.assertRaisesRegex(compose.CompositionRejected, "synthetic"):
                artifact_binding.compose_with_local_manifest(
                    model_root=root, model_manifest=manifest, expected_manifest_sha256=digest, **request)
            with self.assertRaisesRegex(compose.CompositionRejected, "originate"):
                artifact_binding.compose_with_local_manifest(
                    model_root=root, model_manifest=manifest, expected_manifest_sha256=digest,
                    model="unverified", **synthetic_composer_args(state, 4))


if __name__ == "__main__":
    unittest.main()
