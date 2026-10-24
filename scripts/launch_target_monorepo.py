"""Launch a separately staged ``pip --target`` Vera Mono installation.

Pip's generated console scripts do not add ``--target`` directories to the
interpreter's import path. This launcher makes that boundary explicit without
changing a user's global PYTHONPATH or relying on the source checkout.
"""

from __future__ import annotations

from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        raise SystemExit(
            "usage: python launch_target_monorepo.py TARGET_ROOT "
            "VERA_MONO_COMMAND [ARG ...]"
        )

    target_root = Path(arguments[0]).expanduser().resolve()
    if not (target_root / "vera_core" / "cli.py").is_file():
        raise SystemExit(
            "target directory does not contain an installed vera_core/cli.py: "
            f"{target_root}"
        )

    sys.path.insert(0, str(target_root))
    from vera_core.cli import main as vera_main

    return vera_main(arguments[1:])


if __name__ == "__main__":
    raise SystemExit(main())
