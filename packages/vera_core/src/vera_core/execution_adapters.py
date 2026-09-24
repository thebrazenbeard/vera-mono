from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope


@runtime_checkable
class PCExecutionTransport(Protocol):
    """Host-injected PC transport identity and execution surface."""

    host_id: str

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
