"""The pip --target entrypoint must not rely on a checkout or PYTHONPATH."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "launch_target_monorepo.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *arguments],
        cwd=ROOT.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_or_wrong_target_fails_closed(tmp_path: Path) -> None:
    missing = _run()
    assert missing.returncode != 0
    assert "usage:" in missing.stderr

    wrong = _run("--target-root", str(tmp_path), "--help")
    assert wrong.returncode != 0
    assert "does not contain" in wrong.stderr


def test_target_only_python_package_is_invoked_with_arguments(tmp_path: Path) -> None:
    target = tmp_path / "isolated-wheel-target"
    package = target / "vera_core"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "def main(argv=None):\n"
        "    print('TARGET_ONLY', repr(argv))\n"
        "    return 0\n",
        encoding="utf-8",
    )
    result = _run("--target-root", str(target), "status", "--project-id", "demo")
    assert result.returncode == 0, result.stderr
    assert "TARGET_ONLY ['status', '--project-id', 'demo']" in result.stdout

    # A wheel-installed script must locate its own target without carrying a
    # repository checkout or an ambient PYTHONPATH.
    scripts_dir = target / "bin"
    scripts_dir.mkdir()
    staged_launcher = scripts_dir / LAUNCHER.name
    shutil.copy2(LAUNCHER, staged_launcher)
    result = subprocess.run(
        [sys.executable, str(staged_launcher), "shell", "one-shot"],
        cwd=ROOT.parent,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "TARGET_ONLY ['shell', 'one-shot']" in result.stdout
