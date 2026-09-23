"""Strict canonical JSON helpers for the bounded R8A0 slice."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


class CanonicalizationError(ValueError):
    """Raised when input cannot be represented as strict canonical JSON."""


def _pairs_no_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CanonicalizationError(f"non-finite JSON number: {value}")


def strict_loads(payload: str | bytes) -> Any:
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError("JSON must be UTF-8") from exc
    try:
        return json.loads(
            payload,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except CanonicalizationError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise CanonicalizationError(str(exc)) from exc


def canonical_dumps(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(str(exc)) from exc


def canonical_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
