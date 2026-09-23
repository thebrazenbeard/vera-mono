"""Atomic one-successor lifecycle consumption registry."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import tempfile
from typing import Any

from .canonical import canonical_bytes, canonical_dumps, canonical_sha256, strict_loads
from .portable_lock import PortableFileLock


class LifecycleRegistryError(ValueError):
    pass


class StaleLifecycleHead(LifecycleRegistryError):
    pass


def _key(key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) < 16:
        raise LifecycleRegistryError(
            "lifecycle registry key must contain at least 16 bytes"
        )
    return key


def _mac(key: bytes, value: Any) -> str:
    return hmac.new(key, canonical_bytes(value), hashlib.sha256).hexdigest()


class LifecycleRegistry:
    """Authenticated JSON registry with cross-platform inter-process CAS locking."""

    def __init__(self, path: str | Path, key: bytes):
        self.path = Path(path)
        self.lock = self.path.with_suffix(self.path.suffix + ".lock.sqlite3")
        self.key = _key(key)

    def _seal(self, body: dict) -> dict:
        head = canonical_sha256(body)
        authenticated = body | {"head_digest": head}
        return authenticated | {"head_mac": _mac(self.key, authenticated)}

    def _genesis(self) -> dict:
        return self._seal(
            {
                "schema": "VERA_R8A0_LIFECYCLE_REGISTRY_V1",
                "generation": 0,
                "predecessor_head": "0" * 64,
                "events": {},
            }
        )

    def _read(self) -> dict:
        data = self._genesis() if not self.path.exists() else strict_loads(
            self.path.read_bytes()
        )
        if (
            set(data)
            != {
                "schema",
                "generation",
                "predecessor_head",
                "events",
                "head_digest",
                "head_mac",
            }
            or data["schema"] != "VERA_R8A0_LIFECYCLE_REGISTRY_V1"
        ):
            raise LifecycleRegistryError("invalid lifecycle registry")
        authenticated = {k: v for k, v in data.items() if k != "head_mac"}
        body = {
            k: v
            for k, v in data.items()
            if k not in {"head_digest", "head_mac"}
        }
        if (
            not hmac.compare_digest(
                str(data["head_mac"]), _mac(self.key, authenticated)
            )
            or data["head_digest"] != canonical_sha256(body)
        ):
            raise LifecycleRegistryError(
                "lifecycle registry authentication mismatch"
            )
        return data

    def current_head(self) -> str:
        return self._read()["head_digest"]

    def consume(
        self,
        *,
        termination_signature: str,
        checkpoint_signature: str,
        predecessor_runtime_id: str,
        successor_runtime_id: str,
        resumption_claim_digest: str,
        expected_head: str,
    ) -> str:
        with PortableFileLock(self.lock):
            data = self._read()
            if data["head_digest"] != expected_head:
                raise StaleLifecycleHead("stale lifecycle registry head")
            if termination_signature in data["events"]:
                raise LifecycleRegistryError(
                    "termination event already consumed"
                )
            event = {
                "termination_signature": termination_signature,
                "checkpoint_signature": checkpoint_signature,
                "predecessor_runtime_id": predecessor_runtime_id,
                "successor_runtime_id": successor_runtime_id,
                "resumption_claim_digest": resumption_claim_digest,
                "state": "CONSUMED",
            }
            events = dict(data["events"])
            events[termination_signature] = event
            new = self._seal(
                {
                    "schema": data["schema"],
                    "generation": data["generation"] + 1,
                    "predecessor_head": data["head_digest"],
                    "events": events,
                }
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(
                prefix=self.path.name + ".",
                suffix=".tmp",
                dir=self.path.parent,
            )
            os.close(fd)
            temp = Path(name)
            try:
                temp.write_text(canonical_dumps(new), encoding="utf-8")
                os.replace(temp, self.path)
            finally:
                if temp.exists():
                    temp.unlink()
            if self._read()["head_digest"] != new["head_digest"]:
                raise LifecycleRegistryError(
                    "lifecycle registry write readback mismatch"
                )
            return new["head_digest"]

    def event(self, termination_signature: str) -> dict | None:
        return self._read()["events"].get(termination_signature)
