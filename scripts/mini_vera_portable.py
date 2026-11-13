"""Build/verify a small, source-pinned Mini-Vera Windows runtime folder.

Offline files only. It never loads a neural model, exports private memories,
starts Ollama, grants tools, or asserts any cryptographic identity transfer.
The SHA manifest detects accidental drift; it is NOT a signed trust root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys

RESOURCE_PATHS = (
    "packages/vera_identity/src/vera_identity/resources/architecture/identity/VERA_PROJECT_IDENTITY_V1.json",
    "packages/vera_identity/src/vera_identity/resources/architecture/identity/VERA_BEHAVIOR_PROFILE_V1.json",
)
LEGAL_PATHS = ("LICENSE", "NOTICE")
# Explicit, immutable-source dependency closure for the opt-in synthetic
# PUBLIC-memory restart canary. No user databases, keys or weights included.
CANARY_MEMORY_SOURCE_PATHS = (
    "packages/vera_memory/src/vera_memory/__init__.py",
    "packages/vera_memory/src/vera_memory/ledger.py",
    "packages/vera_memory/src/vera_memory/historical_evidence.py",
    "packages/vera_memory/src/vera_memory/historical_export_projection.py",
    "packages/vera_memory/src/vera_memory/learned_influence.py",
    "packages/portfolio_runtime/src/portfolio_runtime/__init__.py",
    "packages/portfolio_runtime/src/portfolio_runtime/lantern/__init__.py",
    "packages/portfolio_runtime/src/portfolio_runtime/lantern/canonical.py",
)
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
HEX40 = re.compile(r"[a-f0-9]{40}\Z")

LAUNCHER = (
    "@echo off\r\n"
    "setlocal\r\n"
    "cd /d \"%~dp0\"\r\n"
    "set \"PYTHONDONTWRITEBYTECODE=1\"\r\n"
    "where py.exe >nul 2>&1\r\n"
    "if not errorlevel 1 goto use_py\r\n"
    "where python.exe >nul 2>&1\r\n"
    "if not errorlevel 1 goto use_python\r\n"
    "echo Python 3 not found on PATH 1>&2\r\n"
    "exit /b 2\r\n"
    ":use_py\r\n"
    "py -3 \"scripts\\mini_vera_portable.py\" verify --output \"%CD%\" >nul\r\n"
    "if errorlevel 1 exit /b 2\r\n"
    "py -3 -m tools.mini_vera.ollama_preflight %*\r\n"
    "exit /b %ERRORLEVEL%\r\n"
    ":use_python\r\n"
    "python \"scripts\\mini_vera_portable.py\" verify --output \"%CD%\" >nul\r\n"
    "if errorlevel 1 exit /b 2\r\n"
    "python -m tools.mini_vera.ollama_preflight %*\r\n"
    "exit /b %ERRORLEVEL%\r\n"
)


class BundleRefused(ValueError):
    """Fail closed without modifying an existing install."""


def _regular(path: Path) -> None:
    """Reject symlinks and Windows reparse points in an entire source chain."""
    for part in (path, *path.parents):
        try:
            item = os.lstat(part)
        except OSError as exc:
            raise BundleRefused("missing filesystem path") from exc
        if stat.S_ISLNK(item.st_mode) or (
            getattr(item, "st_file_attributes", 0) & 0x400
        ):
            raise BundleRefused("symlink or Windows reparse point refused")
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise BundleRefused("missing, non-file or oversized source")


def _sha256(path: Path) -> str:
    _regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sources(root: Path) -> tuple[str, ...]:
    folder = root / "tools/mini_vera"
    if not folder.is_dir() or folder.is_symlink():
        raise BundleRefused("Mini-Vera Python package missing")
    names = sorted(p.relative_to(root).as_posix() for p in folder.glob("*.py"))
    if "tools/mini_vera/ollama_preflight.py" not in names:
        raise BundleRefused("bounded local preflight missing")
    paths = (
        *names,
        "tools/__init__.py",
        "scripts/mini_vera_portable.py",
        *RESOURCE_PATHS,
        *LEGAL_PATHS,
        *(CANARY_MEMORY_SOURCE_PATHS
          if "tools/mini_vera/restart_public_canary.py" in names else ()),
    )
    if len(paths) != len(set(paths)):
        raise BundleRefused("duplicate bundle source")
    for name in paths:
        _regular(root / name)
    return tuple(sorted(paths))


def _load_manifest(path: Path) -> dict:
    _regular(path)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise BundleRefused("oversized manifest")
    def no_duplicates(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise BundleRefused("duplicate manifest key")
            data[key] = value
        return data
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=no_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BundleRefused("invalid manifest") from exc


def verify(output: Path) -> bool:
    """Verify exact files in the local folder, without any model/network calls."""
    root = output.resolve(strict=True)
    manifest = _load_manifest(root / "INSTALL.json")
    if (manifest.get("schema") != "MINI_VERA_PORTABLE_SOURCE_V1"
            or manifest.get("model_alias") != "qwen3.5:0.8b"
            or manifest.get("neural_weights_included") is not False
            or not isinstance(manifest.get("files_sha256"), dict)
            or not HEX40.fullmatch(str(manifest.get("source_revision_claim")))):
        raise BundleRefused("invalid bundle contract")
    expected = manifest["files_sha256"]
    if (not expected or any(type(name) is not str or
            not re.fullmatch(r"[A-Za-z0-9_./-]+", name) or
            any(part in ("", ".", "..") for part in name.split("/")) or
            type(digest) is not str or
            not re.fullmatch(r"[a-f0-9]{64}", digest)
            for name, digest in expected.items())):
        raise BundleRefused("invalid bundle file inventory")
    entries = list(root.rglob("*"))
    for entry in entries:
        mode = os.lstat(entry)
        if (stat.S_ISLNK(mode.st_mode) or
                getattr(mode, "st_file_attributes", 0) & 0x400 or
                not (stat.S_ISDIR(mode.st_mode) or stat.S_ISREG(mode.st_mode))):
            raise BundleRefused("unreviewed filesystem object or redirection")
    actual = {p.relative_to(root).as_posix()
              for p in entries if p.is_file()}
    actual_dirs = {p.relative_to(root).as_posix()
                   for p in entries if p.is_dir()}
    allowed_dirs = set()
    for name in expected:
        part = Path(name).parent
        while part != Path("."):
            allowed_dirs.add(part.as_posix())
            part = part.parent
    if actual != set(expected) | {"INSTALL.json"} or actual_dirs != allowed_dirs:
        raise BundleRefused("missing or unexpected bundle file/directory")
    if not {"mini-vera.cmd", "scripts/mini_vera_portable.py",
            "tools/mini_vera/ollama_preflight.py"}.issubset(expected):
        raise BundleRefused("required launcher or verifier missing")
    for name, digest in expected.items():
        if _sha256(root / name) != digest:
            raise BundleRefused("bundle byte integrity mismatch")
    return True


def build(source: Path, output: Path, source_revision: str) -> Path:
    if not isinstance(source_revision, str) or not HEX40.fullmatch(source_revision):
        raise BundleRefused("full lowercase 40-character source revision required")
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise BundleRefused("destination must be new and absolute")
    parent = output.parent
    if not parent.is_dir():
        raise BundleRefused("destination parent missing")
    # Refuse redirections in the chosen installation parent.
    for part in (parent, *parent.parents):
        item = os.lstat(part)
        if stat.S_ISLNK(item.st_mode) or (
            getattr(item, "st_file_attributes", 0) & 0x400
        ):
            raise BundleRefused("destination path redirection refused")
    paths = _sources(source)
    stage = parent / f".{output.name}.{secrets.token_hex(8)}.incomplete"
    stage.mkdir(mode=0o700)
    try:
        for name in paths:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        (stage / "mini-vera.cmd").write_bytes(LAUNCHER.encode("ascii"))
        file_names = (*paths, "mini-vera.cmd")
        manifest = {
            "schema": "MINI_VERA_PORTABLE_SOURCE_V1",
            "source_revision_claim": source_revision,
            "source_revision_evidence": "OPERATOR_DECLARED_NOT_SIGNATURE",
            "model_alias": "qwen3.5:0.8b",
            "neural_weights_included": False,
            "neural_weight_location": "EXISTING_LOCAL_OLLAMA_STORE_NOT_COPIED",
            "memory": "PROCESS_LOCAL_EPHEMERAL_DEFAULT_NO_PRIVATE_IMPORT",
            "host_activation": "NOT_ACTIVATED_NOT_RESOURCE_QUALIFIED",
            "files_sha256": {name: _sha256(stage / name)
                             for name in sorted(file_names)},
        }
        (stage / "INSTALL.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        verify(stage)
        # A renamed folder is not an exclusive host trust/custody guarantee.
        if output.exists():
            raise BundleRefused("destination appeared during staging")
        stage.rename(output)
        verify(output)
        return output
    except Exception:
        # Keep this unique incomplete folder for forensic inspection;
        # never delete or replace any pre-existing user directory.
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "verify"))
    parser.add_argument("--source", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha")
    args = parser.parse_args(argv)
    try:
        if args.operation == "verify":
            verify(args.output)
            print("MINI_VERA_PORTABLE_BYTES_VERIFIED_NOT_MODEL_QUALIFIED")
        else:
            output = build(args.source, args.output, args.source_sha)
            print(f"MINI_VERA_PORTABLE_INSTALLED_SOURCE_ONLY {output}")
        return 0
    except (BundleRefused, OSError) as exc:
        print(f"Mini-Vera portable refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
