from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .canonical import canonical_json, sha256_bytes
from .model import Artifact


class StoreConflict(RuntimeError):
    pass


class FileSystemStore:
    def __init__(self, root: str | Path = ".ingest"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _atomic_create(self, path: Path, data: bytes) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise StoreConflict(f"immutable path collision: {path}")
            return False
        fd, temp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_name, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise StoreConflict(f"immutable path collision: {path}")
                return False
            return True
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def put_blob(self, data: bytes, *, media_type: str, kind: str) -> tuple[Artifact, bool]:
        digest = sha256_bytes(data)
        relative = Path("blobs") / "sha256" / digest[:2] / digest
        created = self._atomic_create(self.root / relative, data)
        return (
            Artifact(
                artifact_id=f"sha256:{digest}",
                sha256=digest,
                size_bytes=len(data),
                media_type=media_type,
                kind=kind,
                storage_locator=relative.as_posix(),
            ),
            created,
        )

    def _put_json(self, category: str, record_id: str, value: dict[str, Any]) -> bool:
        data = (canonical_json(value) + "\n").encode("utf-8")
        return self._atomic_create(self.root / category / f"{record_id}.json", data)

    def put_record(self, ingest_id: str, value: dict[str, Any]) -> bool:
        return self._put_json("records", ingest_id, value)

    def put_receipt(self, receipt_id: str, value: dict[str, Any]) -> bool:
        return self._put_json("receipts", receipt_id, value)

    def put_derivation(self, derivation_id: str, value: dict[str, Any]) -> bool:
        return self._put_json("derivations", derivation_id, value)

    def has_record(self, ingest_id: str) -> bool:
        return (self.root / "records" / f"{ingest_id}.json").is_file()

    def _get_json(self, category: str, record_id: str) -> dict[str, Any]:
        path = self.root / category / f"{record_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def get_record(self, ingest_id: str) -> dict[str, Any]:
        return self._get_json("records", ingest_id)

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self._get_json("receipts", receipt_id)

    def get_derivation(self, derivation_id: str) -> dict[str, Any]:
        return self._get_json("derivations", derivation_id)
