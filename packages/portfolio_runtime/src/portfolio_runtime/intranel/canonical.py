from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import hashlib
import json
from typing import Any

from .jsonvalue import freeze_json, thaw_json
from .types import Address


def _wire(value: Any) -> Any:
    to_mapping = getattr(value, "to_mapping", None)
    if callable(to_mapping):
        return _wire(to_mapping())
    if isinstance(value, Address):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize the strict cross-runtime INTRANEL/1 canonical JSON subset."""
    # INTRANEL/1 deliberately uses a restricted RFC-8785-compatible subset:
    # printable-ASCII object keys; safe integral numeric values; UTF-8 string
    # values; integral float inputs normalized to integer form; and no
    # non-integral floats.
    frozen = freeze_json(_wire(value), "canonical value")
    normalized = thaw_json(frozen)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
