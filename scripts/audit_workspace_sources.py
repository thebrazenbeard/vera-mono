"""Read-only repository preflight for disguised executables and automatic VS Code tasks.

This is a source-tree check, not malware analysis or host infection attestation.
It never imports repository code, launches tasks, or reads credential material.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


FONT_HEADERS = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf")


def inspect_workspace(root: Path) -> list[dict[str, str]]:
    """Return deterministic source hazards; never execute inspected content."""
    if not root.is_dir():
        raise ValueError("workspace root missing or not a directory")
    findings: list[dict[str, str]] = []

    def flag(code: str, path: Path) -> None:
        findings.append({"code": code,
                         "path": path.relative_to(root).as_posix()})

    for filename, invalid_code in (
        (".vscode/settings.json", "INVALID_SETTINGS_JSON"),
        (".vscode/tasks.json", "INVALID_TASKS_JSON"),
    ):
        path = root / filename
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
            flag(invalid_code, path)
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError, OSError):
            flag(invalid_code, path)
            continue
        if type(doc) is not dict:
            flag(invalid_code, path)
            continue
        if filename.endswith("settings.json"):
            if doc.get("task.allowAutomaticTasks") is True:
                flag("AUTO_TASKS_ENABLED", path)
        else:
            tasks = doc.get("tasks", [])
            if type(tasks) is not list:
                flag(invalid_code, path)
                continue
            for task in tasks:
                if type(task) is not dict:
                    flag(invalid_code, path)
                    break
                options = task.get("runOptions", {})
                if type(options) is not dict:
                    flag(invalid_code, path)
                    break
                if options.get("runOn") == "folderOpen":
                    flag("FOLDER_OPEN_TASK", path)

    fonts = root / "public/fonts"
    if fonts.is_dir() and not fonts.is_symlink():
        for path in sorted(fonts.glob("*.ttf")):
            if path.is_symlink() or not path.is_file():
                flag("INVALID_TRUE_TYPE_HEADER", path)
                continue
            try:
                with path.open("rb") as reader:
                    header = reader.read(4)
            except OSError:
                flag("INVALID_TRUE_TYPE_HEADER", path)
                continue
            if header not in FONT_HEADERS:
                flag("INVALID_TRUE_TYPE_HEADER", path)
    elif fonts.is_symlink():
        flag("UNTRUSTED_FONT_DIRECTORY", fonts)
    return sorted(findings, key=lambda finding: (
        finding["code"], finding["path"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        findings = inspect_workspace(args.root.resolve(strict=True))
    except (ValueError, OSError) as exc:
        print(json.dumps({"schema": "VERA_MONO_WORKSPACE_SOURCE_AUDIT_V1",
                          "status": "REFUSED_SOURCE_TREE",
                          "reason": str(exc), "findings": []}, sort_keys=True))
        return 2
    status = ("REFUSED_SOURCE_TREE" if findings
              else "STATIC_SOURCE_CHECK_PASSED_NOT_HOST_SECURITY_ATTESTATION")
    print(json.dumps({"schema": "VERA_MONO_WORKSPACE_SOURCE_AUDIT_V1",
                      "status": status,
                      "files_executed": 0,
                      "findings": findings}, sort_keys=True))
    return 2 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
