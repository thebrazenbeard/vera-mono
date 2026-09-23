from __future__ import annotations

from datetime import datetime, timezone
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import RFC_4122, UUID


class ContractError(ValueError):
    """Raised when a closed PCCC contract fails validation."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$"
)
_RFC3339_MICRO_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_SAFE_BASENAME = re.compile(r'^[^<>:"/\\|?*\x00-\x1f]+$')
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def closed_fields(
    value: Mapping[str, Any],
    required: Sequence[str],
    contract: str,
    optional: Sequence[str] = (),
) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{contract} must be an object")
    actual = set(value)
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - actual)
    unknown = sorted(actual - allowed)
    if missing:
        raise ContractError(f"{contract} missing fields: {missing}")
    if unknown:
        raise ContractError(f"{contract} unknown fields: {unknown}")


def uuid_v7(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field} must be a UUIDv7 string")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ContractError(f"{field} must be UUIDv7") from exc
    if (
        str(parsed) != value
        or parsed.version != 7
        or parsed.variant != RFC_4122
    ):
        raise ContractError(
            f"{field} must be canonical lowercase UUIDv7"
        )
    return value


def bounded_text(
    value: Any,
    field: str,
    *,
    maximum: int = 1024,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise ContractError(f"{field} must be bounded UTF-8 text")
    return value


def sha256_hex(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContractError(f"{field} must be lowercase SHA-256 hex")
    return value


def uint(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ContractError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def utc_microseconds(value: Any, field: str) -> datetime:
    if (
        not isinstance(value, str)
        or not _RFC3339_MICRO_UTC.fullmatch(value)
    ):
        raise ContractError(
            f"{field} must use UTC RFC3339 with exactly six "
            "fractional digits"
        )
    return datetime.strptime(
        value,
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ).replace(tzinfo=timezone.utc)


def semver(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ContractError(f"{field} must be semantic version text")
    return value


def safe_basename(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or len(value.encode("utf-8")) > 255
        or not _SAFE_BASENAME.fullmatch(value)
        or value[-1] in {" ", "."}
    ):
        raise ContractError(f"{field} must be a safe Windows basename")
    if value.split(".", 1)[0].upper() in _RESERVED_WINDOWS_NAMES:
        raise ContractError(
            f"{field} uses a reserved Windows device name"
        )
    return value


def canonical_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


__all__ = [
    "ContractError",
    "bounded_text",
    "canonical_scalar",
    "closed_fields",
    "safe_basename",
    "semver",
    "sha256_hex",
    "uint",
    "utc_microseconds",
    "uuid_v7",
]
