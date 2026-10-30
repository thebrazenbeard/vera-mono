"""Immutable, host-constructed identity and provider admission snapshot.

Only the privileged host service may hold or invoke this object. Python
Even tuple-backed immutable values are *not* an OS security boundary against
code executing inside the authority process; kernel peer authentication and
process isolation are required before calling :meth:`principal_for_peer`.
"""

from __future__ import annotations

from collections import namedtuple
from types import MappingProxyType
from typing import Mapping


class HostBindingError(PermissionError):
    """A peer, provider or operation is not admitted by the host snapshot."""


def _identity(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field} must be an exact nonempty trimmed str")
    return value


def _identifiers(values: object, field: str) -> frozenset[str]:
    # Reject custom set/collection subclasses that may carry executable or
    # mutable collaborators. Copy builtin sets into immutable value snapshots.
    if type(values) not in (set, frozenset):
        raise TypeError(f"{field} must be a builtin set or frozenset")
    for item in values:
        _identity(item, field)
    return frozenset(values)


def _built_in_mapping(values: object, field: str) -> Mapping[str, object]:
    if type(values) not in (dict, MappingProxyType):
        raise TypeError(f"{field} must be a builtin dict or mappingproxy")
    return values


_PrincipalTuple = namedtuple(
    "_PrincipalTuple",
    ("peer_key", "model_id", "adapter_id", "runtime_id", "subject_id", "allowed_provider_ids"),
)


class PrincipalBinding(_PrincipalTuple):
    """A genuinely immutable, tuple-backed principal value."""

    __slots__ = ()

    def __new__(cls, peer_key: str, model_id: str, adapter_id: str,
                runtime_id: str, subject_id: str, allowed_provider_ids: frozenset[str]):
        for field, value in (("peer_key", peer_key), ("model_id", model_id),
                             ("adapter_id", adapter_id), ("runtime_id", runtime_id),
                             ("subject_id", subject_id)):
            _identity(value, field)
        return super().__new__(
            cls, peer_key, model_id, adapter_id, runtime_id, subject_id,
            _identifiers(allowed_provider_ids, "allowed_provider_ids"),
        )


_ProviderTuple = namedtuple(
    "_ProviderTuple", ("provider_id", "provider_instance_id", "allowed_operations")
)


class ProviderBinding(_ProviderTuple):
    __slots__ = ()

    def __new__(cls, provider_id: str, provider_instance_id: str,
                allowed_operations: frozenset[str]):
        return super().__new__(
            cls, _identity(provider_id, "provider_id"),
            _identity(provider_instance_id, "provider_instance_id"),
            _identifiers(allowed_operations, "allowed_operations"),
        )


_HostSnapshotTuple = namedtuple(
    "_HostSnapshotTuple", ("host_id", "issuer_id", "epoch", "principals", "providers")
)


class HostBindingSnapshot(_HostSnapshotTuple):
    """Exact host-owned snapshot with no rebinding-capable nested values."""

    __slots__ = ()

    def __new__(cls, host_id: str, issuer_id: str, epoch: int,
                principals: Mapping[str, PrincipalBinding],
                providers: Mapping[str, ProviderBinding]):
        _identity(host_id, "host_id")
        _identity(issuer_id, "issuer_id")
        if type(epoch) is not int or epoch <= 0:
            raise ValueError("epoch must be a positive exact int")
        principals = _built_in_mapping(principals, "principals")
        providers = _built_in_mapping(providers, "providers")
        principal_copy: dict[str, PrincipalBinding] = {}
        seen_model_instances: set[tuple[str, str, str, str]] = set()
        for peer_key, principal in principals.items():
            _identity(peer_key, "peer_key")
            if type(principal) is not PrincipalBinding:
                raise TypeError("principal binding must have exact PrincipalBinding type")
            if peer_key != principal.peer_key:
                raise ValueError("principal map key differs from authenticated peer key")
            identity = (principal.model_id, principal.adapter_id,
                        principal.runtime_id, principal.subject_id)
            if identity in seen_model_instances:
                raise ValueError("duplicate model-instance identity across OS peers")
            seen_model_instances.add(identity)
            # Never retain caller-owned aliases; explicitly reconstruct exact
            # tuple-backed values rather than accepting arbitrary collaborators.
            principal_copy[peer_key] = PrincipalBinding(
                principal.peer_key, principal.model_id, principal.adapter_id,
                principal.runtime_id, principal.subject_id,
                principal.allowed_provider_ids,
            )
        provider_copy: dict[str, ProviderBinding] = {}
        seen_provider_instances: set[str] = set()
        for provider_id, provider in providers.items():
            _identity(provider_id, "provider_id")
            if type(provider) is not ProviderBinding:
                raise TypeError("provider binding must have exact ProviderBinding type")
            if provider_id != provider.provider_id:
                raise ValueError("provider map key differs from provider identity")
            if provider.provider_instance_id in seen_provider_instances:
                raise ValueError("provider instance assigned to multiple provider IDs")
            seen_provider_instances.add(provider.provider_instance_id)
            provider_copy[provider_id] = ProviderBinding(
                provider.provider_id, provider.provider_instance_id,
                provider.allowed_operations,
            )
        return super().__new__(
            cls, host_id, issuer_id, epoch,
            MappingProxyType(principal_copy), MappingProxyType(provider_copy),
        )

    def principal_for_peer(self, peer_key: str) -> PrincipalBinding:
        if type(peer_key) is not str or peer_key not in self.principals:
            raise HostBindingError("unrecognized authenticated OS peer")
        return self.principals[peer_key]

    def provider_for(
        self, principal: PrincipalBinding, provider_id: str, operation: str,
    ) -> ProviderBinding:
        if type(principal) is not PrincipalBinding:
            raise HostBindingError("invalid principal")
        if self.principals.get(principal.peer_key) is not principal:
            raise HostBindingError("principal was not resolved by this host snapshot")
        if type(provider_id) is not str or type(operation) is not str:
            raise HostBindingError("invalid provider operation")
        if provider_id not in principal.allowed_provider_ids:
            raise HostBindingError("principal not admitted to provider")
        provider = self.providers.get(provider_id)
        if provider is None or operation not in provider.allowed_operations:
            raise HostBindingError("provider or operation not admitted")
        return provider
