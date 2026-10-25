"""Read-only local host preflight. No model, samples, network, or training."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from importlib import import_module, metadata
from pathlib import Path

from .adapter_prep import _reject_git_checkout, _require_private_filesystem


_PACKAGES = ("torch", "transformers", "peft")
_MIN_FREE_BYTES = 3 * 1024**3


def _private_output_parent(path: Path) -> bool:
    """Inspect directory metadata/mounts only; never enumerate private files."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        return False
    _reject_git_checkout(path, "training output parent")
    _require_private_filesystem(path, "training output parent")
    attrs = path.stat()
    return (
        stat.S_ISDIR(attrs.st_mode)
        and stat.S_IMODE(attrs.st_mode) & 0o077 == 0
        and attrs.st_uid == os.getuid()
    )


def _package_versions() -> tuple[dict[str, str], bool]:
    versions = {}
    present = True
    for name in _PACKAGES:
        try:
            raw = metadata.version(name)
            if not isinstance(raw, str) or re.fullmatch(r"[A-Za-z0-9.!+_-]{1,64}", raw) is None:
                raise ValueError("unrecognized package version")
            versions[name] = raw
        except metadata.PackageNotFoundError:
            versions[name] = "NOT_INSTALLED"
            present = False
        except Exception:
            # Broken package metadata must never leak private environment
            # paths, filenames or arbitrary exception text to receipts.
            versions[name] = "UNVERIFIED"
            present = False
    return versions, present


def inspect_host_readiness(output_parent: Path) -> dict:
    """Report preliminary host capability, never model or data qualification."""
    checks = {
        "platform": "HOLD",
        "python": "HOLD",
        "filesystem": "NOT_CHECKED",
        "dependencies": "NOT_CHECKED",
        "cuda": "NOT_CHECKED",
        "bf16_native": "NOT_CHECKED",
        "vram_free": "NOT_CHECKED",
    }
    report: dict = {
        "schema_version": 1,
        "status": "HOST_HOLD",
        "checks": checks,
        "package_versions": {name: "NOT_CHECKED" for name in _PACKAGES},
        "free_vram_gib": None,
        "training_authorized": False,
        "model_and_data_qualified": False,
    }
    # Native Windows ACLs are not qualified by this workflow. Never probe
    # its filesystem or import torch even if a synthetic path looks POSIX-like.
    if not sys.platform.startswith("linux") or os.name != "posix":
        return report
    checks["platform"] = "PASS"
    if sys.version_info < (3, 12):
        return report
    checks["python"] = "PASS"
    try:
        if not _private_output_parent(Path(output_parent)):
            checks["filesystem"] = "HOLD"
            return report
    except Exception:
        # Filesystem plugins and metadata probes may raise unexpected errors;
        # never propagate local path details into a diagnostic receipt.
        checks["filesystem"] = "HOLD"
        return report
    checks["filesystem"] = "PASS"

    versions, packages_present = _package_versions()
    report["package_versions"] = versions
    if not packages_present:
        checks["dependencies"] = "HOLD"
        return report
    checks["dependencies"] = "PASS"
    try:
        torch = import_module("torch")
        if torch.cuda.is_available() is not True:
            checks["cuda"] = "HOLD"
            return report
        checks["cuda"] = "PASS"
        # PyTorch's default can permit BF16 emulation. We require native BF16;
        # on older APIs without this keyword we fail closed.
        if torch.cuda.is_bf16_supported(including_emulation=False) is not True:
            checks["bf16_native"] = "HOLD"
            return report
        checks["bf16_native"] = "PASS"
        free, total = torch.cuda.mem_get_info()
        if (type(free) is not int or type(total) is not int or free < 0
                or total < free or free < _MIN_FREE_BYTES):
            checks["vram_free"] = "HOLD"
            return report
        checks["vram_free"] = "PASS"
        report["free_vram_gib"] = round(free / 1024**3, 2)
    except Exception:
        # Import errors, incompatible CUDA APIs and runtime failures are all
        # holds; never serialize raw exception text (may contain local paths).
        if checks["cuda"] == "NOT_CHECKED":
            checks["cuda"] = "HOLD"
        elif checks["bf16_native"] == "NOT_CHECKED":
            checks["bf16_native"] = "HOLD"
        else:
            checks["vram_free"] = "HOLD"
        return report
    report["status"] = "HOST_PREFLIGHT_PASS_NOT_TRAINING_AUTHORIZATION"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Vera host capability preflight; no training")
    parser.add_argument("--output-parent", type=Path, required=True,
                        help="Existing private Linux parent for a future adapter output")
    args = parser.parse_args(argv)
    report = inspect_host_readiness(args.output_parent)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "HOST_PREFLIGHT_PASS_NOT_TRAINING_AUTHORIZATION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
