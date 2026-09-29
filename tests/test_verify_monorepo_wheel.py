from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


def _verifier_module():
    path = Path("scripts/verify_monorepo_wheel.py")
    spec = importlib.util.spec_from_file_location("verify_monorepo_wheel", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wheel_verifier_accepts_crlf_metadata(tmp_path: Path) -> None:
    verifier = _verifier_module()
    wheel = tmp_path / "vera_mono-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        for name in verifier.REQUIRED_FILES:
            archive.writestr(name, b"x")
        archive.writestr(
            "vera_mono-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.4\r\n"
            "Name: vera-mono\r\n"
            "Version: 0.1.0\r\n\r\n",
        )
        archive.writestr(
            "vera_mono-0.1.0.dist-info/entry_points.txt",
            "[console_scripts]\r\n"
            "vera-mono = vera_core.cli:main\r\n",
        )

    result = subprocess.run(
        [sys.executable, "scripts/verify_monorepo_wheel.py", str(wheel)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
