from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_JSON_DEPTH = 24
MAX_COLLECTION_ITEMS = 256
MAX_TOTAL_NODES = 4_096
MAX_STRING_BYTES = 8_192
MAX_KEY_BYTES = 256


def _check_text(value: str, field_name: str, *, key: bool = False) -> None:
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} contains invalid Unicode") from exc

    if len(encoded) > (MAX_KEY_BYTES if key else MAX_STRING_BYTES):
        raise ValueError(f"{field_name} exceeds size limit")

    if key and (
        not value
        or not value.isascii()
        or any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in value)
    ):
        raise ValueError(
            f"{field_name} object keys must be non-empty printable ASCII"
        )


def freeze_json(value: Any, field_name: str = "value") -> Any:
    """Validate and recursively freeze an Intranel canonical JSON value."""
    node_count = 0

    def recurse(current: Any, depth: int) -> Any:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_TOTAL_NODES:
            raise ValueError(f"{field_name} exceeds node limit")
        if depth > MAX_JSON_DEPTH:
            raise ValueError(f"{field_name} exceeds depth limit")

        if current is None or isinstance(current, bool):
            return current
        if isinstance(current, str):
            _check_text(current, field_name)
            return current
        if isinstance(current, int) and not isinstance(current, bool):
            if abs(current) > MAX_SAFE_INTEGER:
                raise ValueError(
                    f"{field_name} integer exceeds interoperable safe range"
                )
            return current
        if isinstance(current, float):
            if not current.is_integer() or abs(current) > MAX_SAFE_INTEGER:
                raise ValueError(
                    f"{field_name} non-integral floats are not allowed in "
                    "INTRANEL/1 canonical values"
                )
            return int(current)
        if isinstance(current, (list, tuple)):
            if len(current) > MAX_COLLECTION_ITEMS:
                raise ValueError(f"{field_name} exceeds collection limit")
            return tuple(recurse(item, depth + 1) for item in current)
        if isinstance(current, Mapping):
            if len(current) > MAX_COLLECTION_ITEMS:
                raise ValueError(f"{field_name} exceeds collection limit")
            frozen: dict[str, Any] = {}
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError(f"{field_name} object keys must be strings")
                _check_text(key, field_name, key=True)
                frozen[key] = recurse(item, depth + 1)
            return MappingProxyType(frozen)

        raise ValueError(f"{field_name} must be JSON-compatible")

    return recurse(value, 0)


def thaw_json(value: Any) -> Any:
    """Return a fresh mutable JSON-compatible copy of frozen semantic data."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value
