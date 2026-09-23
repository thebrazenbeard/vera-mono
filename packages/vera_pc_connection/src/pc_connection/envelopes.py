from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pc_connection import (
    PHASE_ONE_OPERATIONS,
    RECOGNIZED_PHASE_ONE_OPERATIONS,
    REMOTE_TRANSFER_OPERATIONS,
)
from pc_connection.canonical import sha256_domain_text_tuple
from pc_connection.validation import (
    ContractError,
    bounded_text,
    canonical_scalar,
    closed_fields,
    semver,
    sha256_hex,
    uint,
    utc_microseconds,
    uuid_v7,
)

JOB_SCHEMA = "VERA_PCCC_JOB_V1"
AUTHORIZATION_SCHEMA = "VERA_PCCC_AUTHORIZATION_V1"
JOB_DOMAIN = "VERA-PCCC-JOB-V1"
AUTHORIZATION_DOMAIN = "VERA-PCCC-AUTHORIZATION-V1"
ZERO_SHA256 = "0" * 64


def _validate_operation_scope(
    operation: str,
    write_root_id: str,
    artifact_manifest_digest: str,
) -> None:
    if operation not in RECOGNIZED_PHASE_ONE_OPERATIONS:
        raise ContractError("operation is not recognized by phase one")
    if operation in REMOTE_TRANSFER_OPERATIONS:
        raise ContractError("EXEC_OPERATION_DENIED")
    if operation not in PHASE_ONE_OPERATIONS:
        raise ContractError("operation is not enabled in phase one")
    if write_root_id != "NONE":
        raise ContractError(
            "enabled phase-one operations require write_root_id NONE"
        )
    if artifact_manifest_digest != ZERO_SHA256:
        raise ContractError(
            "enabled phase-one operations require no artifact manifest"
        )


@dataclass(frozen=True)
class JobEnvelope:
    schema_version: str
    envelope_id: str
    request_id: str
    idempotency_key: str
    project_id: str
    requester_principal_id: str
    requester_principal_type: str
    host_id: str
    operation_id: str
    operation_version: int
    parameters_digest: str
    artifact_manifest_digest: str
    read_roots_digest: str
    write_root_id: str
    authorization_id: str
    authorization_revision: int
    not_before: str
    expires_at: str
    timeout_seconds: int
    max_attempts: int
    lease_ttl_seconds: int
    retry_class: str
    protocol_min_version: str
    agent_min_version: str
    required_local_policy_digest: str
    required_capability_digest: str
    issuer_revocation_epoch: int
    host_revocation_epoch: int
    nonce: str
    trace_correlation_id: str

    FIELDS = (
        "schema_version",
        "envelope_id",
        "request_id",
        "idempotency_key",
        "project_id",
        "requester_principal_id",
        "requester_principal_type",
        "host_id",
        "operation_id",
        "operation_version",
        "parameters_digest",
        "artifact_manifest_digest",
        "read_roots_digest",
        "write_root_id",
        "authorization_id",
        "authorization_revision",
        "not_before",
        "expires_at",
        "timeout_seconds",
        "max_attempts",
        "lease_ttl_seconds",
        "retry_class",
        "protocol_min_version",
        "agent_min_version",
        "required_local_policy_digest",
        "required_capability_digest",
        "issuer_revocation_epoch",
        "host_revocation_epoch",
        "nonce",
        "trace_correlation_id",
    )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "JobEnvelope":
        closed_fields(value, cls.FIELDS, "job envelope")
        envelope = cls(**{field: value[field] for field in cls.FIELDS})
        envelope.validate()
        return envelope

    def validate(self) -> None:
        if self.schema_version != JOB_SCHEMA:
            raise ContractError("unsupported job schema")
        for field in (
            "envelope_id",
            "request_id",
            "host_id",
            "authorization_id",
            "nonce",
            "trace_correlation_id",
        ):
            uuid_v7(getattr(self, field), field)
        bounded_text(
            self.idempotency_key,
            "idempotency_key",
            maximum=256,
        )
        bounded_text(self.project_id, "project_id", maximum=256)
        bounded_text(
            self.requester_principal_id,
            "requester_principal_id",
            maximum=256,
        )
        if self.requester_principal_type not in {
            "USER",
            "SERVICE",
            "CONNECTOR",
        }:
            raise ContractError("unsupported requester_principal_type")
        uint(
            self.operation_version,
            "operation_version",
            minimum=1,
            maximum=4_294_967_295,
        )
        for field in (
            "parameters_digest",
            "artifact_manifest_digest",
            "read_roots_digest",
            "required_local_policy_digest",
            "required_capability_digest",
        ):
            sha256_hex(getattr(self, field), field)
        _validate_operation_scope(
            self.operation_id,
            self.write_root_id,
            self.artifact_manifest_digest,
        )
        uint(
            self.authorization_revision,
            "authorization_revision",
            minimum=1,
            maximum=18_446_744_073_709_551_615,
        )
        not_before = utc_microseconds(self.not_before, "not_before")
        expires = utc_microseconds(self.expires_at, "expires_at")
        if (
            not_before >= expires
            or (expires - not_before).total_seconds() > 3600
        ):
            raise ContractError("job freshness window is invalid")
        uint(
            self.timeout_seconds,
            "timeout_seconds",
            minimum=1,
            maximum=3600,
        )
        uint(self.max_attempts, "max_attempts", minimum=1, maximum=5)
        uint(
            self.lease_ttl_seconds,
            "lease_ttl_seconds",
            minimum=30,
            maximum=300,
        )
        if self.retry_class not in {
            "PURE_READ",
            "CONTENT_ADDRESSED_WRITE",
            "AT_MOST_ONCE",
        }:
            raise ContractError("unsupported retry_class")
        semver(self.protocol_min_version, "protocol_min_version")
        semver(self.agent_min_version, "agent_min_version")
        uint(
            self.issuer_revocation_epoch,
            "issuer_revocation_epoch",
            minimum=0,
            maximum=18_446_744_073_709_551_615,
        )
        uint(
            self.host_revocation_epoch,
            "host_revocation_epoch",
            minimum=0,
            maximum=18_446_744_073_709_551_615,
        )

    def digest_fields(self) -> tuple[str, ...]:
        return tuple(
            canonical_scalar(getattr(self, field))
            for field in self.FIELDS
        )

    def digest(self) -> str:
        self.validate()
        return sha256_domain_text_tuple(JOB_DOMAIN, self.digest_fields())


@dataclass(frozen=True)
class AuthorizationEnvelope:
    schema_version: str
    envelope_id: str
    job_id: str
    issuer_id: str
    subject_user_id: str
    host_id: str
    operation: str
    operation_version: int
    parameters_digest: str
    artifact_manifest_digest: str
    read_roots_digest: str
    write_root_id: str
    authorization_id: str
    authorization_revision: int
    issued_at: str
    not_before: str
    expires_at: str
    nonce: str
    max_attempts: int
    lease_ttl_seconds: int
    protocol_min_version: str
    agent_min_version: str
    issuer_revocation_epoch: int
    host_revocation_epoch: int

    FIELDS = (
        "schema_version",
        "envelope_id",
        "job_id",
        "issuer_id",
        "subject_user_id",
        "host_id",
        "operation",
        "operation_version",
        "parameters_digest",
        "artifact_manifest_digest",
        "read_roots_digest",
        "write_root_id",
        "authorization_id",
        "authorization_revision",
        "issued_at",
        "not_before",
        "expires_at",
        "nonce",
        "max_attempts",
        "lease_ttl_seconds",
        "protocol_min_version",
        "agent_min_version",
        "issuer_revocation_epoch",
        "host_revocation_epoch",
    )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "AuthorizationEnvelope":
        closed_fields(value, cls.FIELDS, "authorization envelope")
        envelope = cls(**{field: value[field] for field in cls.FIELDS})
        envelope.validate()
        return envelope

    def validate(self) -> None:
        if self.schema_version != AUTHORIZATION_SCHEMA:
            raise ContractError("unsupported authorization schema")
        for field in (
            "envelope_id",
            "job_id",
            "host_id",
            "authorization_id",
            "nonce",
        ):
            uuid_v7(getattr(self, field), field)
        bounded_text(self.issuer_id, "issuer_id", maximum=128)
        bounded_text(
            self.subject_user_id,
            "subject_user_id",
            maximum=128,
        )
        uint(
            self.operation_version,
            "operation_version",
            minimum=1,
            maximum=4_294_967_295,
        )
        for field in (
            "parameters_digest",
            "artifact_manifest_digest",
            "read_roots_digest",
        ):
            sha256_hex(getattr(self, field), field)
        _validate_operation_scope(
            self.operation,
            self.write_root_id,
            self.artifact_manifest_digest,
        )
        uint(
            self.authorization_revision,
            "authorization_revision",
            minimum=1,
            maximum=18_446_744_073_709_551_615,
        )
        issued = utc_microseconds(self.issued_at, "issued_at")
        not_before = utc_microseconds(self.not_before, "not_before")
        expires = utc_microseconds(self.expires_at, "expires_at")
        if not issued <= not_before < expires:
            raise ContractError(
                "timestamps must satisfy issued_at <= not_before < expires_at"
            )
        if (expires - not_before).total_seconds() > 3600:
            raise ContractError("authorization window exceeds one hour")
        uint(self.max_attempts, "max_attempts", minimum=1, maximum=5)
        uint(
            self.lease_ttl_seconds,
            "lease_ttl_seconds",
            minimum=30,
            maximum=300,
        )
        semver(self.protocol_min_version, "protocol_min_version")
        semver(self.agent_min_version, "agent_min_version")
        uint(
            self.issuer_revocation_epoch,
            "issuer_revocation_epoch",
            minimum=0,
            maximum=18_446_744_073_709_551_615,
        )
        uint(
            self.host_revocation_epoch,
            "host_revocation_epoch",
            minimum=0,
            maximum=18_446_744_073_709_551_615,
        )

    def digest_fields(self) -> tuple[str, ...]:
        return tuple(
            canonical_scalar(getattr(self, field))
            for field in self.FIELDS
        )

    def digest(self) -> str:
        self.validate()
        return sha256_domain_text_tuple(
            AUTHORIZATION_DOMAIN,
            self.digest_fields(),
        )


__all__ = [
    "AUTHORIZATION_DOMAIN",
    "AUTHORIZATION_SCHEMA",
    "AuthorizationEnvelope",
    "JOB_DOMAIN",
    "JOB_SCHEMA",
    "JobEnvelope",
    "ZERO_SHA256",
]
