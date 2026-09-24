from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

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
