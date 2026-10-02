from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LatentMemoryError(ValueError):
    pass


class Resolution(StrEnum):
    L0_EXACT = "L0_EXACT"
    L1_HIGH_FIDELITY = "L1_HIGH_FIDELITY"
    L2_SEMANTIC_LATENT = "L2_SEMANTIC_LATENT"
    L3_ABSTRACT = "L3_ABSTRACT"


class LossClass(StrEnum):
    LOSSLESS = "LOSSLESS"
    LOSSY = "LOSSY"


def _require_text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise LatentMemoryError(f"{label} must be a non-empty exact string")
    return value


def _require_digest(value: object, label: str) -> str:
    text = _require_text(value, label)
    if _SHA256.fullmatch(text) is None:
        raise LatentMemoryError(f"{label} must be a lowercase sha256 digest")
    return text


def _require_refs(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise LatentMemoryError(f"{label} must be a non-empty exact tuple")
    if any(type(item) is not str or not item for item in value):
        raise LatentMemoryError(f"{label} must contain non-empty exact strings")
    if len(value) != len(set(value)):
        raise LatentMemoryError(f"{label} must contain unique references")
    return value


@dataclass(frozen=True, slots=True)
class LatentBlock:
    block_id: str
    source_refs: tuple[str, ...]
    source_digest: str
    resolution: Resolution
    codec_id: str
    codec_version: str
    representation: bytes
    representation_digest: str
    loss_class: LossClass
    exact_recoverable: bool
    provenance: tuple[str, ...]
    created_at: str

    @staticmethod
    def _identity_material(
        *,
        source_refs: tuple[str, ...],
        source_digest: str,
        resolution: Resolution,
        codec_id: str,
        codec_version: str,
        representation_digest: str,
        loss_class: LossClass,
        exact_recoverable: bool,
        provenance: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "source_refs": list(source_refs),
            "source_digest": source_digest,
            "resolution": resolution.value,
            "codec_id": codec_id,
            "codec_version": codec_version,
            "representation_digest": representation_digest,
            "loss_class": loss_class.value,
            "exact_recoverable": exact_recoverable,
            "provenance": list(provenance),
        }

    @classmethod
    def create(
        cls,
        *,
        source_refs: tuple[str, ...],
        source_digest: str,
        resolution: Resolution,
        codec_id: str,
        codec_version: str,
        representation: bytes,
        loss_class: LossClass,
        exact_recoverable: bool,
        provenance: tuple[str, ...],
        created_at: str,
    ) -> "LatentBlock":
        _require_refs(source_refs, "source_refs")
        digest = _require_digest(source_digest, "source_digest")
        if type(resolution) is not Resolution:
            raise LatentMemoryError("resolution must be an exact Resolution")
        codec = _require_text(codec_id, "codec_id")
        version = _require_text(codec_version, "codec_version")
        if type(representation) is not bytes or not representation:
            raise LatentMemoryError("representation must be non-empty exact bytes")
        if type(loss_class) is not LossClass:
            raise LatentMemoryError("loss_class must be an exact LossClass")
        if type(exact_recoverable) is not bool:
            raise LatentMemoryError("exact_recoverable must be an exact bool")
        provenance_refs = _require_refs(provenance, "provenance")
        observed_at = _require_text(created_at, "created_at")
        representation_digest = sha256_hex(representation)
        material = cls._identity_material(
            source_refs=source_refs,
            source_digest=digest,
            resolution=resolution,
            codec_id=codec,
            codec_version=version,
            representation_digest=representation_digest,
            loss_class=loss_class,
            exact_recoverable=exact_recoverable,
            provenance=provenance_refs,
        )
        return cls(
            block_id=sha256_hex(canonical_json_bytes(material)),
            source_refs=source_refs,
            source_digest=digest,
            resolution=resolution,
            codec_id=codec,
            codec_version=version,
            representation=representation,
            representation_digest=representation_digest,
            loss_class=loss_class,
            exact_recoverable=exact_recoverable,
            provenance=provenance_refs,
            created_at=observed_at,
        )

    def validate(self) -> None:
        _require_digest(self.block_id, "block_id")
        rebuilt = type(self).create(
            source_refs=self.source_refs,
            source_digest=self.source_digest,
            resolution=self.resolution,
            codec_id=self.codec_id,
            codec_version=self.codec_version,
            representation=self.representation,
            loss_class=self.loss_class,
            exact_recoverable=self.exact_recoverable,
            provenance=self.provenance,
            created_at=self.created_at,
        )
        if rebuilt.block_id != self.block_id:
            raise LatentMemoryError("block_id does not bind the exact latent block")
        if rebuilt.representation_digest != self.representation_digest:
            raise LatentMemoryError(
                "representation_digest does not bind representation bytes"
            )

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "block_id": self.block_id,
            "source_refs": list(self.source_refs),
            "source_digest": self.source_digest,
            "resolution": self.resolution.value,
            "codec_id": self.codec_id,
            "codec_version": self.codec_version,
            "representation_hex": self.representation.hex(),
            "representation_digest": self.representation_digest,
            "loss_class": self.loss_class.value,
            "exact_recoverable": self.exact_recoverable,
            "provenance": list(self.provenance),
            "created_at": self.created_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LatentBlock":
        try:
            block = cls(
                block_id=payload["block_id"],
                source_refs=tuple(payload["source_refs"]),
                source_digest=payload["source_digest"],
                resolution=Resolution(payload["resolution"]),
                codec_id=payload["codec_id"],
                codec_version=payload["codec_version"],
                representation=bytes.fromhex(payload["representation_hex"]),
                representation_digest=payload["representation_digest"],
                loss_class=LossClass(payload["loss_class"]),
                exact_recoverable=payload["exact_recoverable"],
                provenance=tuple(payload["provenance"]),
                created_at=payload["created_at"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise LatentMemoryError("stored latent block payload is malformed") from error
        block.validate()
        return block


class LatentMemoryStore:
    """Durable compact-representation store.

    The store records representations and bindings only. It does not perform
    governed semantic-memory admission and does not create epistemic authority.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS latent_blocks (
                    block_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode(payload_json: str) -> LatentBlock:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as error:
            raise LatentMemoryError("stored latent block JSON is malformed") from error
        if type(payload) is not dict:
            raise LatentMemoryError("stored latent block payload must be an object")
        return LatentBlock.from_payload(payload)

    def put(self, block: LatentBlock) -> LatentBlock:
        if type(block) is not LatentBlock:
            raise LatentMemoryError("block must be an exact LatentBlock")
        block.validate()
        encoded = canonical_json(block.payload())
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM latent_blocks WHERE block_id=?",
                (block.block_id,),
            ).fetchone()
            if row is not None:
                stored = self._decode(row["payload_json"])
                if (
                    stored.block_id != block.block_id
                    or stored.representation_digest != block.representation_digest
                    or stored.source_digest != block.source_digest
                ):
                    raise LatentMemoryError(
                        "latent block identity collides with different content"
                    )
                return stored
            db.execute(
                "INSERT INTO latent_blocks(block_id,payload_json) VALUES(?,?)",
                (block.block_id, encoded),
            )
            db.commit()
        return block

    def get(self, block_id: str) -> LatentBlock:
        identity = _require_digest(block_id, "block_id")
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM latent_blocks WHERE block_id=?",
                (identity,),
            ).fetchone()
        if row is None:
            raise KeyError(identity)
        return self._decode(row["payload_json"])

    def all(self) -> tuple[LatentBlock, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload_json FROM latent_blocks ORDER BY block_id"
            ).fetchall()
        return tuple(self._decode(row["payload_json"]) for row in rows)

    def context(self) -> dict[str, object]:
        blocks = self.all()
        by_resolution: dict[str, int] = {}
        for block in blocks:
            by_resolution[block.resolution.value] = (
                by_resolution.get(block.resolution.value, 0) + 1
            )
        return {
            "schema": "VERA_MONO_LATENT_MEMORY_CONTEXT_V1",
            "block_count": len(blocks),
            "exact_recoverable_count": sum(
                1 for block in blocks if block.exact_recoverable
            ),
            "by_resolution": dict(sorted(by_resolution.items())),
            "claim_ceiling": (
                "REPRESENTATION_STORAGE_ONLY_NOT_MEMORY_ADMISSION_TRUTH_AUTHORITY_"
                "OR_PROVIDER_INTERNAL_COMPRESSION"
            ),
        }
