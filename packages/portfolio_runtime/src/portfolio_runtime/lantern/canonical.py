from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by Lantern's JCS subset."""


_MAX_SAFE_INTEGER = 2**53 - 1


def _validate_string(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise CanonicalizationError("Unicode surrogate code points are not allowed")
    return value


def normalize_timestamp(value: str | datetime) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CanonicalizationError(f"Invalid ISO-8601 timestamp: {value!r}") from exc
    else:
        parsed = value
    if parsed.tzinfo is None:
        raise CanonicalizationError("Timestamps must include an explicit UTC offset")
    normalized = parsed.astimezone(UTC)
    if normalized.microsecond:
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_relative_posix_path(value: str) -> str:
    value = _validate_string(value)
    if not value or "\\" in value:
        raise CanonicalizationError("Paths must be non-empty POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise CanonicalizationError("Absolute paths are not allowed")
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise CanonicalizationError("Path traversal and non-normalized segments are not allowed")
    normalized = str(path)
    if normalized != value:
        raise CanonicalizationError("Path must already be normalized")
    return normalized


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def normalize_value(value: Any, *, key_hint: str | None = None) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise CanonicalizationError("Integers must fit the interoperable IEEE-754 safe range")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError("Non-finite JSON numbers are not allowed")
        raise CanonicalizationError("Floating-point values are excluded from Lantern v1 canonical records")
    if isinstance(value, str):
        checked = _validate_string(value)
        if key_hint and (key_hint == "path" or key_hint.endswith("_path")):
            return normalize_relative_posix_path(checked)
        if key_hint and key_hint.endswith("_at"):
            return normalize_timestamp(checked)
        return checked
    if isinstance(value, (list, tuple)):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise CanonicalizationError("JSON object keys must be strings")
            key = _validate_string(raw_key)
            if key in normalized:
                raise CanonicalizationError(f"Duplicate key after validation: {key}")
            normalized[key] = normalize_value(raw_value, key_hint=key)
        return {key: normalized[key] for key in sorted(normalized, key=_utf16_sort_key)}
    raise CanonicalizationError(f"Unsupported canonical JSON type: {type(value).__name__}")


def strict_json_loads(value: str | bytes) -> Any:
    text = value.decode("utf-8") if isinstance(value, bytes) else value

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise CanonicalizationError(f"Duplicate JSON key: {key}")
            result[key] = item
        return result

    def parse_constant(token: str) -> Any:
        raise CanonicalizationError(f"Non-finite JSON number: {token}")

    try:
        return json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=parse_constant,
        )
    except UnicodeDecodeError as exc:
        raise CanonicalizationError("JSON input is not valid UTF-8") from exc


def canonical_json_bytes(value: Any) -> bytes:
    normalized = normalize_value(value)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    return text.encode("utf-8")


def canonical_json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()
