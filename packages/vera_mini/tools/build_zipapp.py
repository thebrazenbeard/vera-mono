"""Build a single-file stdlib Python zip application without model training."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile
import zipapp


def build(output: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    package = root / "mini_vera"
    if not (package / "__main__.py").is_file():
        raise FileNotFoundError("mini_vera/__main__.py is required")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mini-vera-zipapp-") as temporary:
        staging = Path(temporary)
        shutil.copytree(
            package,
            staging / "mini_vera",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        zipapp.create_archive(
            staging,
            target=output,
            main="mini_vera.__main__:main",
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a self-contained Mini-Vera .pyz")
    parser.add_argument("--output", type=Path, default=Path("dist/mini-vera.pyz"))
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()

