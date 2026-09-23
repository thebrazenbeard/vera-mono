from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pc_connection import PHASE_ONE_OPERATIONS
from pc_connection.canonical import sha256_domain_text_tuple
from pc_connection.validation import (
    ContractError,
    bounded_text,
    canonical_scalar,
    closed_fields,
    safe_basename,
    sha256_hex,
    uint,
    utc_microseconds,
    uuid_v7,
)

ARTIFACT_SCHEMA = "VERA_PCCC_ARTIFACT_MANIFEST_V1"
ARTIFACT_DOMAIN = "VERA-PCCC-ARTIFACT-MANIFEST-V1"
CHUNK_SIZE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactSource:
    store: str
    locator: str
    immutable_locator_version: str

    FIELDS = ("store", "locator", "immutable_locator_version")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactSource":
        closed_fields(value, cls.FIELDS, "artifact source")
        source = cls(**{field: value[field] for field in cls.FIELDS})
        if source.store != "LOCAL_ONLY":
            raise ContractError(
                "phase one artifact source must be LOCAL_ONLY"
            )
        bounded_text(source.locator, "source.locator", maximum=1024)
        if "://" in source.locator or ":" in source.locator:
            raise ContractError(
                "phase one source locator must not be a URL or ADS"
            )
        bounded_text(
            source.immutable_locator_version,
            "source.immutable_locator_version",
            maximum=256,
        )
        return source


@dataclass(frozen=True)
class DestinationPolicy:
    store: str
    backend_profile_id: str
    backend_profile_digest: str
    remote_transfer_enabled: bool
    relative_path: str

    FIELDS = (
        "store",
        "backend_profile_id",
        "backend_profile_digest",
        "remote_transfer_enabled",
        "relative_path",
    )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "DestinationPolicy":
        closed_fields(value, cls.FIELDS, "destination policy")
        policy = cls(**{field: value[field] for field in cls.FIELDS})
        if (
            policy.store != "LOCAL_ONLY"
            or policy.backend_profile_id != "LOCAL_ONLY"
        ):
            raise ContractError(
                "phase one destination backend must be LOCAL_ONLY"
            )
        sha256_hex(
            policy.backend_profile_digest,
            "backend_profile_digest",
        )
        if policy.remote_transfer_enabled is not False:
            raise ContractError("phase one remote transfer is disabled")
        bounded_text(
            policy.relative_path,
            "destination relative_path",
            maximum=1024,
        )
        parts = policy.relative_path.replace("/", "\\").split("\\")
        if (
            policy.relative_path.startswith(("/", "\\"))
            or ":" in policy.relative_path
            or ".." in parts
        ):
            raise ContractError("destination relative_path is unsafe")
        return policy


@dataclass(frozen=True)
class ArtifactAuthorization:
    authorization_id: str
    revision: int
    allowed_host_id: str
    allowed_job_id: str
    allowed_operations: tuple[str, ...]
    max_bytes: int
    issued_at: str
    expires_at: str

    FIELDS = (
        "authorization_id",
        "revision",
        "allowed_host_id",
        "allowed_job_id",
        "allowed_operations",
        "max_bytes",
        "issued_at",
        "expires_at",
    )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "ArtifactAuthorization":
        closed_fields(value, cls.FIELDS, "artifact authorization")
        operations = value["allowed_operations"]
        if (
            not isinstance(operations, list)
            or not operations
            or any(not isinstance(item, str) for item in operations)
            or len(set(operations)) != len(operations)
            or operations != sorted(operations)
        ):
            raise ContractError(
                "allowed_operations must be a sorted unique nonempty list"
            )
        if any(item not in PHASE_ONE_OPERATIONS for item in operations):
            raise ContractError("EXEC_OPERATION_DENIED")
        authorization = cls(
            authorization_id=value["authorization_id"],
            revision=value["revision"],
            allowed_host_id=value["allowed_host_id"],
            allowed_job_id=value["allowed_job_id"],
            allowed_operations=tuple(operations),
            max_bytes=value["max_bytes"],
            issued_at=value["issued_at"],
            expires_at=value["expires_at"],
        )
        for field in (
            "authorization_id",
            "allowed_host_id",
            "allowed_job_id",
        ):
            uuid_v7(getattr(authorization, field), field)
        uint(
            authorization.revision,
            "authorization revision",
            minimum=1,
            maximum=18_446_744_073_709_551_615,
        )
        uint(
            authorization.max_bytes,
            "authorization max_bytes",
            minimum=0,
            maximum=MAX_ARTIFACT_BYTES,
        )
        issued = utc_microseconds(
            authorization.issued_at,
            "authorization issued_at",
        )
        expires = utc_microseconds(
            authorization.expires_at,
            "authorization expires_at",
        )
        if (
            issued >= expires
            or (expires - issued).total_seconds() > 3600
        ):
            raise ContractError(
                "artifact authorization freshness is invalid"
            )
        return authorization


@dataclass(frozen=True)
class RetentionPolicy:
    retention_class: str
    retain_until: str

    FIELDS = ("class", "retain_until")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RetentionPolicy":
        closed_fields(value, cls.FIELDS, "retention policy")
        policy = cls(
            retention_class=value["class"],
            retain_until=value["retain_until"],
        )
        if policy.retention_class not in {
            "EPHEMERAL",
            "PROJECT",
            "RELEASE",
            "LEGAL_HOLD",
        }:
            raise ContractError("unsupported retention class")
        utc_microseconds(policy.retain_until, "retain_until")
        return policy


@dataclass(frozen=True)
class ArtifactManifest:
    schema_version: str
    manifest_id: str
    manifest_digest_algorithm: str
    manifest_sha256: str
    artifact_id: str
    content_id: str
    logical_name: str
    declared_filename: str
    byte_length: int
    sha256: str
    content_class: str
    privacy_class: str
    execution_class: str
    archive_class: str
    media_type_declared: str
    source: ArtifactSource
    destination_policy: DestinationPolicy
    authorization: ArtifactAuthorization
    retention: RetentionPolicy
    created_at: str

    FIELDS = (
        "schema_version",
        "manifest_id",
        "manifest_digest_algorithm",
        "manifest_sha256",
        "artifact_id",
        "content_id",
        "logical_name",
        "declared_filename",
        "byte_length",
        "sha256",
        "content_class",
        "privacy_class",
        "execution_class",
        "archive_class",
        "media_type_declared",
        "source",
        "destination_policy",
        "authorization",
        "retention",
        "created_at",
    )
    CONTENT_CLASSES = {
        "SOURCE",
        "CONFIG",
        "LOG",
        "RECEIPT",
        "TEST_EVIDENCE",
        "DATASET",
        "MODEL_WEIGHT",
        "CHECKPOINT",
        "ARCHIVE",
        "USER_DOCUMENT",
        "OTHER",
        "UNKNOWN",
    }
    PRIVACY_CLASSES = {
        "PUBLIC",
        "PROJECT",
        "PRIVATE",
        "SENSITIVE",
    }
    ARCHIVE_CLASSES = {
        "NOT_ARCHIVE",
        "ZIP",
        "TAR",
        "TAR_GZ",
        "UNKNOWN",
    }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactManifest":
        closed_fields(value, cls.FIELDS, "artifact manifest")
        manifest = cls(
            schema_version=value["schema_version"],
            manifest_id=value["manifest_id"],
            manifest_digest_algorithm=value["manifest_digest_algorithm"],
            manifest_sha256=value["manifest_sha256"],
            artifact_id=value["artifact_id"],
            content_id=value["content_id"],
            logical_name=value["logical_name"],
            declared_filename=value["declared_filename"],
            byte_length=value["byte_length"],
            sha256=value["sha256"],
            content_class=value["content_class"],
            privacy_class=value["privacy_class"],
            execution_class=value["execution_class"],
            archive_class=value["archive_class"],
            media_type_declared=value["media_type_declared"],
            source=ArtifactSource.from_mapping(value["source"]),
            destination_policy=DestinationPolicy.from_mapping(
                value["destination_policy"]
            ),
            authorization=ArtifactAuthorization.from_mapping(
                value["authorization"]
            ),
            retention=RetentionPolicy.from_mapping(value["retention"]),
            created_at=value["created_at"],
        )
        manifest.validate()
        return manifest

    def validate(self) -> None:
        if self.schema_version != ARTIFACT_SCHEMA:
            raise ContractError("unsupported artifact manifest schema")
        if self.manifest_digest_algorithm != "SHA-256":
            raise ContractError("unsupported manifest digest algorithm")
        uuid_v7(self.manifest_id, "manifest_id")
        uuid_v7(self.artifact_id, "artifact_id")
        sha256_hex(self.manifest_sha256, "manifest_sha256")
        bounded_text(self.logical_name, "logical_name", maximum=256)
        safe_basename(self.declared_filename, "declared_filename")
        uint(
            self.byte_length,
            "byte_length",
            minimum=0,
            maximum=MAX_ARTIFACT_BYTES,
        )
        digest = sha256_hex(self.sha256, "sha256")
        if self.content_id != f"urn:sha256:{digest}:{self.byte_length}":
            raise ContractError(
                "content_id does not bind SHA-256 and byte length"
            )
        if self.content_class not in self.CONTENT_CLASSES:
            raise ContractError("unsupported content_class")
        if self.privacy_class not in self.PRIVACY_CLASSES:
            raise ContractError("unsupported privacy_class")
        if self.execution_class != "NON_EXECUTABLE":
            raise ContractError("phase one executable artifacts are denied")
        if self.archive_class not in self.ARCHIVE_CLASSES:
            raise ContractError("unsupported archive_class")
        bounded_text(
            self.media_type_declared,
            "media_type_declared",
            maximum=127,
        )
        if "/" not in self.media_type_declared:
            raise ContractError(
                "media_type_declared must be a MIME type"
            )
        if self.authorization.max_bytes < self.byte_length:
            raise ContractError(
                "authorization max_bytes is below byte_length"
            )
        created = utc_microseconds(self.created_at, "created_at")
        retain_until = utc_microseconds(
            self.retention.retain_until,
            "retain_until",
        )
        if retain_until < created:
            raise ContractError("retain_until precedes created_at")
        if self.manifest_sha256 != self.computed_manifest_sha256():
            raise ContractError(
                "manifest_sha256 does not match canonical fields"
            )

    def digest_fields(self) -> tuple[str, ...]:
        return (
            self.schema_version,
            self.manifest_id,
            self.manifest_digest_algorithm,
            self.artifact_id,
            self.content_id,
            self.logical_name,
            self.declared_filename,
            str(self.byte_length),
            self.sha256,
            self.content_class,
            self.privacy_class,
            self.execution_class,
            self.archive_class,
            self.media_type_declared,
            self.source.store,
            self.source.locator,
            self.source.immutable_locator_version,
            self.destination_policy.store,
            self.destination_policy.backend_profile_id,
            self.destination_policy.backend_profile_digest,
            canonical_scalar(
                self.destination_policy.remote_transfer_enabled
            ),
            self.destination_policy.relative_path,
            self.authorization.authorization_id,
            str(self.authorization.revision),
            self.authorization.allowed_host_id,
            self.authorization.allowed_job_id,
            ",".join(self.authorization.allowed_operations),
            str(self.authorization.max_bytes),
            self.authorization.issued_at,
            self.authorization.expires_at,
            self.retention.retention_class,
            self.retention.retain_until,
            self.created_at,
        )

    def computed_manifest_sha256(self) -> str:
        return sha256_domain_text_tuple(
            ARTIFACT_DOMAIN,
            self.digest_fields(),
        )


__all__ = [
    "ARTIFACT_DOMAIN",
    "ARTIFACT_SCHEMA",
    "ArtifactAuthorization",
    "ArtifactManifest",
    "ArtifactSource",
    "CHUNK_SIZE_BYTES",
    "DestinationPolicy",
    "MAX_ARTIFACT_BYTES",
    "RetentionPolicy",
]
