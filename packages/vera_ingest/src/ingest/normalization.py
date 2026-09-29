from __future__ import annotations

import json
import unicodedata

from .canonical import canonical_json


NORMALIZER_VERSION = "ingest-normalizer-v1"


class NormalizationError(ValueError):
    pass


def _clean_media_type(media_type: str | None) -> str | None:
    if media_type is None:
        return None
    return media_type.split(";", 1)[0].strip().lower() or None


def sniff_media_type(data: bytes) -> str:
    stripped = data.lstrip()
    if stripped.startswith((b"{", b"[")):
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        else:
            return "application/json"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    if "\x00" in text:
        return "application/octet-stream"
    return "text/plain"


def normalize_bytes(data: bytes, media_type: str) -> bytes | None:
    media_type = _clean_media_type(media_type) or "application/octet-stream"
    if media_type in {"application/json", "text/json"}:
        try:
            value = json.loads(data.decode("utf-8"))
            return canonical_json(value).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise NormalizationError(f"invalid JSON: {exc}") from exc
    if media_type in {"application/x-ndjson", "application/jsonl"}:
        lines: list[str] = []
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NormalizationError("JSONL is not valid UTF-8") from exc
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                lines.append(canonical_json(value))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise NormalizationError(f"invalid JSONL line {index}: {exc}") from exc
        return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
    if media_type.startswith("text/"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NormalizationError("text payload is not valid UTF-8") from exc
        text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
        return text.encode("utf-8")
    return None
