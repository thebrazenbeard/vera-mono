from __future__ import annotations

import hashlib
from collections.abc import Iterable

ENCODING_ID = "LENGTH_PREFIXED_UTF8_TEXT_TUPLE_V1"


def encode_text_tuple(fields: Iterable[str]) -> bytes:
    """Encode an ordered text tuple as T1 length-prefixed UTF-8."""

    materialized = tuple(fields)
    for index, field in enumerate(materialized):
        if not isinstance(field, str):
            raise TypeError(f"field {index} must be str")

    chunks = [f"T1|{len(materialized)}|".encode("ascii")]
    for field in materialized:
        encoded = field.encode("utf-8", errors="strict")
        chunks.extend(
            (str(len(encoded)).encode("ascii"), b":", encoded)
        )
    return b"".join(chunks)


def sha256_text_tuple(fields: Iterable[str]) -> str:
    """Return SHA-256 of an undomained canonical tuple."""

    return hashlib.sha256(encode_text_tuple(fields)).hexdigest()


def sha256_domain_text_tuple(
    domain: str,
    fields: Iterable[str],
) -> str:
    """Return SHA-256(domain UTF-8 || LF || canonical tuple bytes)."""

    if (
        not isinstance(domain, str)
        or not domain
        or "\n" in domain
        or "\r" in domain
    ):
        raise ValueError("domain must be a nonempty single-line string")
    material = domain.encode("utf-8", errors="strict") + b"\n"
    material += encode_text_tuple(fields)
    return hashlib.sha256(material).hexdigest()


__all__ = [
    "ENCODING_ID",
    "encode_text_tuple",
    "sha256_text_tuple",
    "sha256_domain_text_tuple",
]
