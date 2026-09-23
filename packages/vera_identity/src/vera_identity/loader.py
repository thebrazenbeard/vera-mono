from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"


def resource_path(relative_path: str) -> Path:
    if type(relative_path) is not str or not relative_path or relative_path.startswith("/"):
        raise ValueError("relative_path must be a non-empty relative string")
    candidate = (_RESOURCE_ROOT / relative_path).resolve()
    root = _RESOURCE_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("resource path escapes Vera identity resource root")
    return candidate


def load_text_resource(relative_path: str) -> str:
    return resource_path(relative_path).read_text(encoding="utf-8")


def load_json_resource(relative_path: str) -> Any:
    return json.loads(load_text_resource(relative_path))
