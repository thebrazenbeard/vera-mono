from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping


ALLOWED_SUPERSESSION_STATES = {
    "CURRENT_OBSERVATION",
    "SUPERSEDED",
    "UNKNOWN",
    "NOT_APPLICABLE",
}
ALLOWED_CONFLICT_STATES = {
    "NONE",
    "CONFLICT",
    "MISMATCH",
    "UNKNOWN",
    "NOT_APPLICABLE",
}


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _aware_timestamp(value: str) -> str:
    value = _required_text("observed_at", value)
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("observed_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value


@dataclass(frozen=True)
class ProviderEvidenceEnvelope:
    provider: str
    locator: str
    revision: str
    observed_at: str
    evidence_class: str
    referent: str
    scope: str
    privacy_class: str
    currentness_basis: str
    supersession_state: str
    conflict_state: str
    content_digest: str | None = None
    receipt_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "locator",
            "revision",
            "evidence_class",
            "referent",
            "scope",
            "privacy_class",
            "currentness_basis",
        ):
            object.__setattr__(self, name, _required_text(name, getattr(self, name)))
        object.__setattr__(self, "observed_at", _aware_timestamp(self.observed_at))

        if self.supersession_state not in ALLOWED_SUPERSESSION_STATES:
            raise ValueError(f"unsupported supersession_state: {self.supersession_state}")
        if self.conflict_state not in ALLOWED_CONFLICT_STATES:
            raise ValueError(f"unsupported conflict_state: {self.conflict_state}")
        if self.content_digest is not None:
            object.__setattr__(self, "content_digest", _required_text("content_digest", self.content_digest))
        if self.receipt_ref is not None:
            object.__setattr__(self, "receipt_ref", _required_text("receipt_ref", self.receipt_ref))
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        if self.metadata.get("semantic_authority") is True:
            raise ValueError("provider evidence cannot self-declare semantic authority")
        if self.metadata.get("current_authority") is True:
            raise ValueError("provider evidence cannot self-declare current authority")


def validate_envelope(envelope: ProviderEvidenceEnvelope) -> None:
    """Validate an already-created envelope without promoting its evidence."""
    if not isinstance(envelope, ProviderEvidenceEnvelope):
        raise ValueError("expected ProviderEvidenceEnvelope")
    # Frozen construction performs the substantive validation. This function is
    # intentionally explicit for callers that need a validation boundary.
    _aware_timestamp(envelope.observed_at)


def load_provider_fabric(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "VERA_PROVIDER_FABRIC_V1":
        raise ValueError("unsupported provider fabric schema")
    if data.get("normative_status") != "NON_NORMATIVE_OPERATIONAL_SUPPORT":
        raise ValueError("provider fabric must remain non-normative operational support")
    providers = data.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("provider fabric requires providers")
    projections = data.get("projections")
    if not isinstance(projections, list):
        raise ValueError("provider fabric projections must be a list")
    return data
