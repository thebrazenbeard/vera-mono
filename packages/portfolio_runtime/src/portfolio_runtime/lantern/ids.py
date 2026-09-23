from __future__ import annotations

import hashlib
import secrets
import time
import uuid


def uuid7(*, timestamp_ms: int | None = None, random_bits: int | None = None) -> str:
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ts < 2**48:
        raise ValueError("UUIDv7 timestamp is out of range")
    rand = secrets.randbits(74) if random_bits is None else random_bits
    if not 0 <= rand < 2**74:
        raise ValueError("UUIDv7 random bits are out of range")
    rand_a = (rand >> 62) & 0xFFF
    rand_b = rand & ((1 << 62) - 1)
    value = (ts << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


def deterministic_uuid7(seed: str, *, timestamp_ms: int) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    random_bits = int.from_bytes(digest[:10], "big") & ((1 << 74) - 1)
    return uuid7(timestamp_ms=timestamp_ms, random_bits=random_bits)


def require_uuid7(value: str) -> str:
    parsed = uuid.UUID(value)
    if parsed.version != 7:
        raise ValueError(f"Expected UUIDv7, received version {parsed.version}")
    return str(parsed)
