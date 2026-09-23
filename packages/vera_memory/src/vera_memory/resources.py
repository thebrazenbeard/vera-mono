from __future__ import annotations

from pathlib import Path


_RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"


def resource_path(relative_path: str) -> Path:
    if type(relative_path) is not str or not relative_path or relative_path.startswith("/"):
        raise ValueError("relative_path must be a non-empty relative string")
    path = (_RESOURCE_ROOT / relative_path).resolve()
    root = _RESOURCE_ROOT.resolve()
    if path != root and root not in path.parents:
        raise ValueError("resource path escapes Vera memory resource root")
    return path
