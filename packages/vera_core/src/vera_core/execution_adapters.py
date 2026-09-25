from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope
from pc_connection.validation import sha256_hex


@runtime_checkable
class PCExecutionTransportAttestation(Protocol):
    """Live host observation of the PC transport's admitted execution surface."""

    host_id: str
    capability_digest: str
    local_policy_digest: str
    read_roots_digest: str


def validate_pc_execution_transport_attestation(
    value: Any,
) -> PCExecutionTransportAttestation:
    required = (
        "host_id",
        "capability_digest",
        "local_policy_digest",
        "read_roots_digest",
    )
    missing = tuple(name for name in required if not hasattr(value, name))
    if missing:
        raise TypeError(
            "PC execution transport attestation is missing fields: "
            + ", ".join(missing)
        )
    if type(value.host_id) is not str or not value.host_id:
        raise ValueError(
            "PC execution transport attestation host_id must be non-empty"
        )
    for field in (
        "capability_digest",
        "local_policy_digest",
        "read_roots_digest",
    ):
        sha256_hex(getattr(value, field), field)
    return value


def validate_pc_execution_transport_for_job(
    transport: "PCExecutionTransport",
    job: JobEnvelope,
) -> PCExecutionTransportAttestation:
    """Fail closed unless live transport surface matches exact job requirements."""
    if transport.host_id != job.host_id:
        raise ValueError(
            "PC execution transport host identity does not match job host"
        )
    attestation = validate_pc_execution_transport_attestation(
        transport.attest()
    )
    if attestation.host_id != job.host_id:
        raise ValueError(
            "PC execution transport attestation host identity "
            "does not match job host"
        )
    if attestation.host_id != transport.host_id:
        raise ValueError(
            "PC execution transport attestation host identity "
            "does not match transport identity"
        )
    if attestation.capability_digest != job.required_capability_digest:
        raise ValueError(
            "PC execution transport capability digest "
            "does not match job requirement"
        )
    if attestation.local_policy_digest != job.required_local_policy_digest:
        raise ValueError(
            "PC execution transport local policy digest "
            "does not match job requirement"
        )
    if attestation.read_roots_digest != job.read_roots_digest:
        raise ValueError(
            "PC execution transport read roots digest "
            "does not match job requirement"
        )
    return attestation


@runtime_checkable
class PCExecutionTransport(Protocol):
    """Host-injected PC transport identity, attestation, and execution surface."""

    host_id: str

    def attest(self) -> PCExecutionTransportAttestation:
        ...

    def execute(
        self,
        job: JobEnvelope,
        authorization: AuthorizationEnvelope,
    ) -> Any:
        ...


@runtime_checkable
class ProviderExecutionTransport(Protocol):
    """Host-injected provider transport bound to one provider identity."""

    provider_id: str

    def execute(
        self,
        operation: str,
        request_payload: Any,
    ) -> Any:
        ...


@dataclass(frozen=True, slots=True)
class SourceMutationTransportResult:
    repository: str
    ref: str
    operation: str
    path: str
    destination_path: str | None
    previous_ref_head: str
    new_ref_head: str
    result_id: str


@runtime_checkable
class SourceMutationTransport(Protocol):
    """Host-injected repository/file mutation surface.

    The transport must enforce the request's expected_ref_head and expected
    blob identities atomically/provider-side. It is not allowed to broaden
    task writable scope or delegation ownership.
    """

    provider_id: str
    repository: str
    ref: str

    def mutate(
        self,
        request_payload: Mapping[str, Any],
    ) -> SourceMutationTransportResult:
        ...