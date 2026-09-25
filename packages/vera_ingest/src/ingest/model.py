from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping


class IngestStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    PARTIAL = "PARTIAL"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class EvidenceClass(StrEnum):
    DIRECT_SOURCE = "DIRECT_SOURCE"
    CLAIMED_METADATA = "CLAIMED_METADATA"
    OBSERVED_METADATA = "OBSERVED_METADATA"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceRef:
    scheme: str
    locator: str
    adapter: str
    adapter_version: str
    observed_at: str
    source_identity: Mapping[str, Any] = field(default_factory=dict)
    claimed_metadata: Mapping[str, Any] = field(default_factory=dict)
    observed_metadata: Mapping[str, Any] = field(default_factory=dict)

    def identity_material(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "locator": self.locator,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "source_identity": dict(self.source_identity),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_material(),
            "observed_at": self.observed_at,
            "claimed_metadata": dict(self.claimed_metadata),
            "observed_metadata": dict(self.observed_metadata),
        }


@dataclass(frozen=True, slots=True)
class Acquisition:
    data: bytes
    source: SourceRef
    claimed_media_type: str | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    sha256: str
    size_bytes: int
    media_type: str
    kind: str
    storage_locator: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "kind": self.kind,
            "storage_locator": self.storage_locator,
        }


@dataclass(frozen=True, slots=True)
class StageReceipt:
    receipt_id: str
    ingest_id: str | None
    stage: str
    stage_version: str
    issued_at: str
    outcome: str
    input_artifact_ids: tuple[str, ...] = ()
    output_artifact_ids: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)
    receipt_digest: str = ""

    def body(self) -> dict[str, Any]:
        return {
            "schema": "INGEST_STAGE_RECEIPT_V1",
            "receipt_id": self.receipt_id,
            "ingest_id": self.ingest_id,
            "stage": self.stage,
            "stage_version": self.stage_version,
            "issued_at": self.issued_at,
            "outcome": self.outcome,
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_artifact_ids": list(self.output_artifact_ids),
            "details": dict(self.details),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class Derivation:
    derivation_id: str
    relation: str
    parent_artifact_id: str
    child_artifact_id: str
    receipt_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "INGEST_DERIVATION_V1",
            "derivation_id": self.derivation_id,
            "relation": self.relation,
            "parent_artifact_id": self.parent_artifact_id,
            "child_artifact_id": self.child_artifact_id,
            "receipt_id": self.receipt_id,
        }


@dataclass(frozen=True, slots=True)
class IngestRecord:
    ingest_id: str
    source: SourceRef
    raw_artifact: Artifact
    normalized_artifact: Artifact | None
    status: IngestStatus
    evidence_class: EvidenceClass
    normalizer_version: str
    policy_id: str
    receipt_ids: tuple[str, ...] = ()
    derivation_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "INGEST_RECORD_V1",
            "ingest_id": self.ingest_id,
            "source": self.source.to_dict(),
            "raw_artifact": self.raw_artifact.to_dict(),
            "normalized_artifact": (
                None if self.normalized_artifact is None else self.normalized_artifact.to_dict()
            ),
            "status": self.status.value,
            "evidence_class": self.evidence_class.value,
            "normalizer_version": self.normalizer_version,
            "policy_id": self.policy_id,
            "receipt_ids": list(self.receipt_ids),
            "derivation_ids": list(self.derivation_ids),
            "warnings": list(self.warnings),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class IngestResult:
    ingest_id: str | None
    status: IngestStatus
    source: SourceRef | None = None
    raw_artifact: Artifact | None = None
    normalized_artifact: Artifact | None = None
    receipt_ids: tuple[str, ...] = ()
    derivation_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "INGEST_RESULT_V1",
            "ingest_id": self.ingest_id,
            "status": self.status.value,
            "source": None if self.source is None else self.source.to_dict(),
            "raw_artifact": None if self.raw_artifact is None else self.raw_artifact.to_dict(),
            "normalized_artifact": (
                None if self.normalized_artifact is None else self.normalized_artifact.to_dict()
            ),
            "receipt_ids": list(self.receipt_ids),
            "derivation_ids": list(self.derivation_ids),
            "warnings": list(self.warnings),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class TextSource:
    text: str
    locator: str = "inline:text"


@dataclass(frozen=True, slots=True)
class BytesSource:
    data: bytes
    locator: str = "inline:bytes"
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class FileSource:
    path: str


@dataclass(frozen=True, slots=True)
class UrlSource:
    url: str


@dataclass(frozen=True, slots=True)
class GitHubFileSource:
    owner: str
    repository: str
    ref: str
    path: str


@dataclass(frozen=True, slots=True)
class MessageSource:
    message_id: str
    payload: Mapping[str, Any]
    source: str = "message"
    event_time: str | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
