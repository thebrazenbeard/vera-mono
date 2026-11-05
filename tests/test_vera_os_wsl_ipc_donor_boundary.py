"""Offline, source-only donor provenance and authority-ceiling invariants."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
DONOR_PATH = ROOT / "provenance/donors/vera_os_wsl_ipc_candidate.json"
BOUNDARY_PATH = ROOT / "architecture/VERA_WSL_IPC_DONOR_BOUNDARY_V1.json"
SHA40 = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


def _read_json_unique(path: Path) -> dict:
    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if type(data) is not dict:
        raise ValueError("donor contract must be a JSON object")
    return data


class WSLIPCDonorBoundaryTests(unittest.TestCase):
    def test_exact_source_pins_and_independent_evidence_ceiling(self) -> None:
        donor = _read_json_unique(DONOR_PATH)
        self.assertEqual(donor["schema"], "VERA_MONO_DONOR_BINDING_V1")
        self.assertEqual(donor["donor_repository"], "thebrazenbeard/vera-os")
        self.assertEqual(donor["donor_head"],
                         "624da853340a1fdc3ce606ff38f2adb751dc7fc9")
        self.assertEqual(donor["donor_base_draft_head"],
                         "6e3925314781b9e288a11ff0e0799e53217e94c3")
        self.assertEqual(donor["donor_accepted_main_at_review"],
                         "31b66b6ff317eb981c4bd8fcc4ae6e5db1d21adf")
        expected_blobs = {
            "src/veraos/wsl_pilot.py": "f7361d208cf8b20a9b0be2ad679f362dc0d0c011",
            "src/veraos/wsl_ipc.py": "704259f3e346e59b3f6d221119fd00db8e8d4116",
            "tests/test_wsl_ipc.py": "a12c304f130d0f783c8332a888beb857e3067c78",
            "tests/test_wsl_ipc_replay_gap.py": "a1dd879cc79d88c253647168b7f5307c0d64f4aa",
            "docs/14-wsl2-next-gates.md": "417f6baf5bf61ec005969f0384f3da4e1acd4d2e",
            "docs/15-wsl2-windows-identity-and-worker-isolation.md":
                "71906ae425a6df9db7aea4e72de42cbba9c2fe59",
        }
        self.assertEqual(donor["source_blob_ids"], expected_blobs)
        for source_path, blob in donor["source_blob_ids"].items():
            self.assertFalse(source_path.startswith("/"))
            self.assertNotIn("..", Path(source_path).parts)
            self.assertRegex(blob, SHA40)
        self.assertEqual(donor["evidence"]["independent_host_reproduction"], False)
        self.assertEqual(donor["evidence"]["real_cross_uid_denial"], False)
        self.assertIn("NOT_ABSORBED", donor["claim_ceiling"])

    def test_admission_does_not_mint_runtime_or_effect_authority(self) -> None:
        donor = _read_json_unique(DONOR_PATH)
        boundary = _read_json_unique(BOUNDARY_PATH)
        self.assertEqual(donor["admission_state"], "EXPERIMENTING")
        self.assertEqual(donor["mode"], "SOURCE_REVIEW_ONLY_NO_CODE_COPY")
        self.assertIsNone(donor["absorbed_target"])
        self.assertIs(donor["runtime_dependency_on_donor"], False)
        self.assertEqual(donor["authority_effect"], "NONE")
        self.assertEqual(boundary["donor_binding"], DONOR_PATH.relative_to(ROOT).as_posix())
        self.assertEqual(boundary["donor_subject"],
                         f"{donor['donor_repository']}@{donor['donor_head']}")
        self.assertEqual(boundary["state"], "SOURCE_CANDIDATE_NOT_ADMITTED")
        self.assertEqual(boundary["canonical_runtime"], "vera_core.QualifiedVeraRuntime")
        self.assertEqual(boundary["canonical_task_ledger"], "vera_core.TaskExecutionLedger")
        self.assertEqual(boundary["current_transport_admission"], "NONE")
        self.assertIs(boundary["current_host_identity_qualification"], False)
        self.assertTrue(any("idempotent" in line for line in
                            boundary["future_admission_conditions"]))
        self.assertTrue(any("same-UID" in line for line in
                            donor["unqualified_boundaries"]))


if __name__ == "__main__":
    unittest.main()
