from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import hmac
from typing import Protocol, runtime_checkable

from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope
from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex


PC_AUTHORITY_PROOF_SCHEMA = "VERA_MONO_PC_AUTHORITY_PROOF_V1"
PROVIDER_AUTHORITY_SCHEMA = "VERA_MONO_PROVIDER_AUTHORITY_V1"


class OutboundAuthorityError(PermissionError):
    pass


def _subject(prefix: str, body: dict) -> str:
    return f"{prefix}:" + sha256_hex(canonical_json_bytes(body))


def validate_pc_authorization_binding(
    job: JobEnvelope,
    authorization: AuthorizationEnvelope,
) -> None:
    """Bind the PC authorization contract to all shared job constraints.

    AuthorizationEnvelope.job_id remains an opaque authority-side identifier
    because the absorbed PCCC contract does not define it as equal to either
    JobEnvelope.envelope_id or request_id. The verifier proof below binds the
    exact authorization envelope and exact job digest together.
    """
    if type(job) is not JobEnvelope:
        raise OutboundAuthorityError("PC authority requires exact JobEnvelope")
    if type(authorization) is not AuthorizationEnvelope:
        raise OutboundAuthorityError(
            "PC authority requires exact AuthorizationEnvelope"
        )
    job.validate()
    authorization.validate()

    exact = {
        "authorization_id": (job.authorization_id, authorization.authorization_id),
        "authorization_revision": (
            job.authorization_revision, authorization.authorization_revision
        ),
        "host_id": (job.host_id, authorization.host_id),
        "operation": (job.operation_id, authorization.operation),
        "operation_version": (job.operation_version, authorization.operation_version),
        "parameters_digest": (job.parameters_digest, authorization.parameters_digest),
        "artifact_manifest_digest": (
            job.artifact_manifest_digest, authorization.artifact_manifest_digest
        ),
        "read_roots_digest": (job.read_roots_digest, authorization.read_roots_digest),
        "write_root_id": (job.write_root_id, authorization.write_root_id),
        "protocol_min_version": (
            job.protocol_min_version, authorization.protocol_min_version
        ),
        "agent_min_version": (job.agent_min_version, authorization.agent_min_version),
        "issuer_revocation_epoch": (
            job.issuer_revocation_epoch, authorization.issuer_revocation_epoch
        ),
        "host_revocation_epoch": (
            job.host_revocation_epoch, authorization.host_revocation_epoch
        ),
    }
    for field, (job_value, authority_value) in exact.items():
        if job_value != authority_value:
            raise OutboundAuthorityError(
                f"PC authorization does not bind job field: {field}"
            )

    if job.max_attempts > authorization.max_attempts:
        raise OutboundAuthorityError("PC job max_attempts exceeds authorization")
    if job.lease_ttl_seconds > authorization.lease_ttl_seconds:
        raise OutboundAuthorityError(
            "PC job lease_ttl_seconds exceeds authorization"
        )
    if job.not_before < authorization.not_before:
        raise OutboundAuthorityError("PC job starts before authorization window")
    if job.expires_at > authorization.expires_at:
        raise OutboundAuthorityError("PC job expires after authorization window")


def pc_authority_subject(
    *,
    job_digest: str,
    authorization_digest: str,
    lifecycle_permit_digest: str,
) -> str:
    return _subject(
        "vera-mono-pc-authority-v1",
        {
            "job_digest": job_digest,
            "authorization_digest": authorization_digest,
            "lifecycle_permit_digest": lifecycle_permit_digest,
        },
    )


@dataclass(frozen=True, slots=True)
class PCJobAuthorityProof:
    schema: str
    issuer_id: str
    subject: str
    verification_token: str


@runtime_checkable
class PCJobAuthorityVerifier(Protocol):
    def verify(
        self, proof: PCJobAuthorityProof, *, expected_subject: str
    ) -> bool:
        ...


class HmacPCJobAuthority:
    """Reference exact-subject PC authority using an externally held secret."""

    def __init__(self, issuer_id: str, secret: bytes):
        if type(issuer_id) is not str or not issuer_id:
            raise ValueError("issuer_id must be a non-empty exact string")
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("secret must contain at least 32 bytes")
        self.issuer_id = issuer_id
        self._secret = secret
        self._used: set[str] = set()

    def issue(
        self,
        *,
        job: JobEnvelope,
        authorization: AuthorizationEnvelope,
        lifecycle_permit_digest: str,
    ) -> PCJobAuthorityProof:
        validate_pc_authorization_binding(job, authorization)
        subject = pc_authority_subject(
            job_digest=job.digest(),
            authorization_digest=authorization.digest(),
            lifecycle_permit_digest=lifecycle_permit_digest,
        )
        unsigned = PCJobAuthorityProof(
            schema=PC_AUTHORITY_PROOF_SCHEMA,
            issuer_id=self.issuer_id,
            subject=subject,
            verification_token="",
        )
        token = hmac.new(
            self._secret,
            canonical_json_bytes(
                {
                    "schema": unsigned.schema,
                    "issuer_id": unsigned.issuer_id,
                    "subject": unsigned.subject,
                }
            ),
            sha256,
        ).hexdigest()
        return replace(unsigned, verification_token=token)

    def verify(
        self, proof: PCJobAuthorityProof, *, expected_subject: str
    ) -> bool:
        try:
            if type(proof) is not PCJobAuthorityProof:
                return False
            if proof.schema != PC_AUTHORITY_PROOF_SCHEMA:
                return False
            if proof.issuer_id != self.issuer_id:
                return False
            if proof.subject != expected_subject:
                return False
            expected = hmac.new(
                self._secret,
                canonical_json_bytes(
                    {
                        "schema": proof.schema,
                        "issuer_id": proof.issuer_id,
                        "subject": proof.subject,
                    }
                ),
                sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, proof.verification_token):
                return False
            replay = f"{proof.issuer_id}:{proof.verification_token}"
            if replay in self._used:
                return False
            self._used.add(replay)
            return True
        except (TypeError, ValueError):
            return False


def provider_authority_subject(
    *,
    effect_id: str,
    provider_id: str,
    operation: str,
    request_digest: str,
    lifecycle_permit_digest: str,
) -> str:
    return _subject(
        "vera-mono-provider-authority-v1",
        {
            "effect_id": effect_id,
            "provider_id": provider_id,
            "operation": operation,
            "request_digest": request_digest,
            "lifecycle_permit_digest": lifecycle_permit_digest,
        },
    )


@dataclass(frozen=True, slots=True)
class ProviderAuthorityEnvelope:
    schema: str
    issuer_id: str
    provider_id: str
    operation: str
    subject: str
    verification_token: str


@runtime_checkable
class ProviderAuthorityVerifier(Protocol):
    def verify(
        self,
        envelope: ProviderAuthorityEnvelope,
        *,
        expected_provider_id: str,
        expected_operation: str,
        expected_subject: str,
    ) -> bool:
        ...


class HmacProviderAuthority:
    """Reference provider authority with an externally held injected secret."""

    def __init__(self, issuer_id: str, provider_id: str, secret: bytes):
        if type(issuer_id) is not str or not issuer_id:
            raise ValueError("issuer_id must be a non-empty exact string")
        if type(provider_id) is not str or not provider_id:
            raise ValueError("provider_id must be a non-empty exact string")
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("secret must contain at least 32 bytes")
        self.issuer_id = issuer_id
        self.provider_id = provider_id
        self._secret = secret
        self._used: set[str] = set()

    def issue(
        self,
        *,
        effect_id: str,
        operation: str,
        request_digest: str,
        lifecycle_permit_digest: str,
    ) -> ProviderAuthorityEnvelope:
        subject = provider_authority_subject(
            effect_id=effect_id,
            provider_id=self.provider_id,
            operation=operation,
            request_digest=request_digest,
            lifecycle_permit_digest=lifecycle_permit_digest,
        )
        unsigned = ProviderAuthorityEnvelope(
            schema=PROVIDER_AUTHORITY_SCHEMA,
            issuer_id=self.issuer_id,
            provider_id=self.provider_id,
            operation=operation,
            subject=subject,
            verification_token="",
        )
        token = hmac.new(
            self._secret,
            canonical_json_bytes(
                {
                    "schema": unsigned.schema,
                    "issuer_id": unsigned.issuer_id,
                    "provider_id": unsigned.provider_id,
                    "operation": unsigned.operation,
                    "subject": unsigned.subject,
                }
            ),
            sha256,
        ).hexdigest()
        return replace(unsigned, verification_token=token)

    def verify(
        self,
        envelope: ProviderAuthorityEnvelope,
        *,
        expected_provider_id: str,
        expected_operation: str,
        expected_subject: str,
    ) -> bool:
        try:
            if type(envelope) is not ProviderAuthorityEnvelope:
                return False
            if envelope.schema != PROVIDER_AUTHORITY_SCHEMA:
                return False
            if envelope.issuer_id != self.issuer_id:
                return False
            if envelope.provider_id != self.provider_id:
                return False
            if envelope.provider_id != expected_provider_id:
                return False
            if envelope.operation != expected_operation:
                return False
            if envelope.subject != expected_subject:
                return False
            expected = hmac.new(
                self._secret,
                canonical_json_bytes(
                    {
                        "schema": envelope.schema,
                        "issuer_id": envelope.issuer_id,
                        "provider_id": envelope.provider_id,
                        "operation": envelope.operation,
                        "subject": envelope.subject,
                    }
                ),
                sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, envelope.verification_token):
                return False
            replay = f"{envelope.issuer_id}:{envelope.verification_token}"
            if replay in self._used:
                return False
            self._used.add(replay)
            return True
        except (TypeError, ValueError):
            return False
