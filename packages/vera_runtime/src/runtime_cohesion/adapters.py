from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .evidence import ProviderEvidenceEnvelope


PROBE_STATES = {
    "ELIGIBLE_FOR_OPERATION",
    "CURRENTLY_OBSERVED_REACHABLE",
    "RESULT",
    "UNAVAILABLE",
    "UNKNOWN",
}


@dataclass(frozen=True)
class AdapterRequest:
    domain_id: str
    provider: str
    source_ref: str
    route_ref: str
    selector_ref: str | None
    privacy_class: str
    evidence_capability_refs: tuple[str, ...]
    event_ref: str | None = None
    event_path: str | None = None
    event_selector: tuple[tuple[str, str], ...] = ()
    governing_proposition_or_effect_class: str | None = None
    governing_referent_scope: str | None = None

    def __post_init__(self) -> None:
        for name in ("domain_id", "provider", "source_ref", "route_ref", "privacy_class"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if not self.evidence_capability_refs:
            raise ValueError("evidence_capability_refs must be non-empty")
        if (self.event_ref is None) != (self.event_path is None):
            raise ValueError("event_ref and event_path must be supplied together")
        if self.event_ref is not None and (not isinstance(self.event_ref, str) or not self.event_ref):
            raise ValueError("event_ref must be a non-empty string when supplied")
        if self.event_path is not None and (not isinstance(self.event_path, str) or not self.event_path):
            raise ValueError("event_path must be a non-empty string when supplied")
        if self.event_selector and self.event_ref is None:
            raise ValueError("event_selector requires event_ref/event_path")
        seen: set[str] = set()
        for field_name, field_value in self.event_selector:
            if not isinstance(field_name, str) or not field_name or not isinstance(field_value, str) or not field_value:
                raise ValueError("event_selector entries must contain non-empty string field/value pairs")
            if field_name in seen:
                raise ValueError(f"duplicate event_selector field: {field_name}")
            seen.add(field_name)
        if (self.governing_proposition_or_effect_class is None) != (self.governing_referent_scope is None):
            raise ValueError("governing proposition and referent scope must be supplied together")
        if self.governing_proposition_or_effect_class is not None:
            if not isinstance(self.governing_proposition_or_effect_class, str) or not self.governing_proposition_or_effect_class:
                raise ValueError("governing proposition/effect class must be a non-empty string when supplied")
            if not isinstance(self.governing_referent_scope, str) or not self.governing_referent_scope:
                raise ValueError("governing referent scope must be a non-empty string when supplied")


@dataclass(frozen=True)
class AdapterProbeResult:
    provider: str
    route_ref: str
    state: str
    observed_at: str
    reason: str

    def __post_init__(self) -> None:
        if not self.provider or not self.route_ref or not self.observed_at:
            raise ValueError("probe provider/route_ref/observed_at must be non-empty")
        if self.state not in PROBE_STATES:
            raise ValueError(f"unsupported adapter probe state: {self.state}")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("probe reason must be non-empty")


class ProviderAdapter(Protocol):
    provider: str

    def probe(self, request: AdapterRequest) -> AdapterProbeResult: ...

    def read(self, request: AdapterRequest) -> ProviderEvidenceEnvelope | None: ...


class AdapterRegistry:
    """Runtime-owned adapter lookup; adapters do not carry policy authority."""

    def __init__(self, adapters: Mapping[str, ProviderAdapter]):
        self._adapters = dict(adapters)

    def get(self, provider: str) -> ProviderAdapter | None:
        return self._adapters.get(provider)

    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
