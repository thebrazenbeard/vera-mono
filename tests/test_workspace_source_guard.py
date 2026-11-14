"""Static-only regression for source-tree auto-execution and fake-font hazards."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.audit_workspace_sources import inspect_workspace


ROOT = Path(__file__).resolve().parents[1]


class WorkspaceSourceGuardTests(unittest.TestCase):
    def test_ci_runs_source_guard_before_dependency_install(self):
        workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/audit_workspace_sources.py --root .", workflow)
        self.assertLess(workflow.index("audit_workspace_sources.py"),
                        workflow.index("Install test dependencies"))

    def create(self, root: Path, *, auto: bool, font: bool) -> None:
        vscode = root / ".vscode"
        vscode.mkdir()
        (vscode / "settings.json").write_text(json.dumps({
            "task.allowAutomaticTasks": auto}), encoding="utf-8")
        (vscode / "tasks.json").write_text(json.dumps({
            "version": "2.0.0", "tasks": ([{
                "label": "eslint-check", "type": "shell",
                "command": "node",
                "args": ["./public/fonts/fa-solid-600.ttf"],
                "runOptions": {"runOn": "folderOpen"},
            }] if auto else [])}), encoding="utf-8")
        if font:
            fonts = root / "public/fonts"
            fonts.mkdir(parents=True)
            (fonts / "fa-solid-600.ttf").write_bytes(
                b"\t"*16 + b"var fakeFont = require('child_process');")

    def test_current_repository_is_safe_under_exact_static_policy(self):
        self.assertEqual([], inspect_workspace(ROOT))

    def test_catches_all_three_confirmed_pr198_200_hazards_without_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create(root, auto=True, font=True)
            findings = inspect_workspace(root)
            codes = {item["code"] for item in findings}
            self.assertEqual({"AUTO_TASKS_ENABLED", "FOLDER_OPEN_TASK",
                              "INVALID_TRUE_TYPE_HEADER"}, codes)
            result = subprocess.run([
                sys.executable,
                str(ROOT / "scripts/audit_workspace_sources.py"),
                "--root", str(root)], text=True, capture_output=True, timeout=10)
            self.assertEqual(2, result.returncode)
            self.assertEqual("REFUSED_SOURCE_TREE",
                             json.loads(result.stdout)["status"])
            # Scanning must not modify or run any file.
            self.assertEqual(b"\t"*16 + b"var fakeFont = require('child_process');",
                             (root / "public/fonts/fa-solid-600.ttf").read_bytes())

    def test_normal_ttf_header_and_no_autoexec_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create(root, auto=False, font=False)
            fonts = root / "public/fonts"
            fonts.mkdir(parents=True)
            (fonts / "test.ttf").write_bytes(b"\0\1\0\0" + b"SAFE_FIXTURE")
            self.assertEqual([], inspect_workspace(root))

    def test_folder_open_script_alone_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.create(root, auto=False, font=False)
            path = root / ".vscode/tasks.json"
            value = json.loads(path.read_text())
            value["tasks"] = [{
                "label": "surprise", "type": "shell", "command": "echo",
                "runOptions": {"runOn": "folderOpen"}}]
            path.write_text(json.dumps(value))
            self.assertEqual(["FOLDER_OPEN_TASK"],
                             [item["code"] for item in inspect_workspace(root)])

    def test_malformed_task_json_cannot_bypass_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vscode = root / ".vscode"
            vscode.mkdir()
            (vscode / "tasks.json").write_text("{not JSON", encoding="utf-8")
            self.assertEqual(["INVALID_TASKS_JSON"],
                             [item["code"] for item in inspect_workspace(root)])


if __name__ == "__main__":
    unittest.main()
