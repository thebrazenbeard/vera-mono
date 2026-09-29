"""Historical evidence retrieval boundary.

Adapted from Deep Memory's two-plane contract. This module carries historical
evidence and privacy/currentness semantics only. It does not admit current
memory, select present state, or authorize action.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


RESULT_SEMANTICS = "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY"
CHRONOLOGY_SEMANTICS = (
    "EVENT_TIME_RECORD_TIME_EFFECTIVE_TIME_RETRIEVAL_TIME_SEPARATE"
)


class HistoricalEvidenceError(ValueError):
    pass


class HistoricalEvidenceAccessError(HistoricalEvidenceError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceRecord:
    memory_id: str
    privacy_scope: str
    event_time: str | None
    recorded_at: str | None
    effective_from: str | None
    source_ids: tuple[str, ...]
    provenance_ceiling: str
    currentness_rule: str
    historical_canonicity: str | None = None
    content: Mapping[str, object] | None = None
    chronology_semantics: str = CHRONOLOGY_SEMANTICS

    def __post_init__(self) -> None:
        for label, value in (
            ("memory_id", self.memory_id),
            ("privacy_scope", self.privacy_scope),
            ("provenance_ceiling", self.provenance_ceiling),
            ("currentness_rule", self.currentness_rule),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        if any(type(item) is not str or not item for item in self.source_ids):
            raise ValueError("source_ids must contain non-empty exact strings")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("source_ids must be unique")
        for label in ("event_time", "recorded_at", "effective_from"):
            value = getattr(self, label)
            if value is not None and (type(value) is not str or not value):
                raise ValueError(f"{label} must be null or a non-empty exact string")
        if self.content is not None:
            if not isinstance(self.content, Mapping):
                raise TypeError("content must be a mapping when supplied")
            object.__setattr__(self, "content", MappingProxyType(dict(self.content)))

    @property
    def recorded_at_status(self) -> str:
        return (
            "SOURCE_RECORDED"
            if self.recorded_at is not None
            else "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW"
        )

    @property
    def effective_from_status(self) -> str:
        return (
            "SOURCE_RECORDED"
            if self.effective_from is not None
            else "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW"
        )


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceResult:
    records: tuple[HistoricalEvidenceRecord, ...]
    authorized_privacy_scopes: tuple[str, ...]
    retrieved_at: str
    result_semantics: str = RESULT_SEMANTICS
    current_memory_effect: str = "NONE"
    authorization_effect: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(
            self,
            "authorized_privacy_scopes",
            tuple(self.authorized_privacy_scopes),
        )


def query_historical_evidence(
    records: tuple[HistoricalEvidenceRecord, ...],
    *,
    authorized_privacy_scopes: tuple[str, ...],
    retrieved_at: str | None = None,
) -> HistoricalEvidenceResult:
    """Return only caller-authorized historical evidence.

    Absence of exact privacy scopes fails closed. Retrieval is a projection over
    supplied evidence and has no current-memory or authorization side effect.
    """

    if type(authorized_privacy_scopes) is not tuple:
        authorized_privacy_scopes = tuple(authorized_privacy_scopes)
    if not authorized_privacy_scopes:
        raise HistoricalEvidenceAccessError(
            "historical evidence retrieval requires explicit privacy scope authorization"
        )
    if any(
        type(scope) is not str or not scope
        for scope in authorized_privacy_scopes
    ):
        raise HistoricalEvidenceAccessError(
            "authorized privacy scopes must be non-empty exact strings"
        )
    if len(authorized_privacy_scopes) != len(set(authorized_privacy_scopes)):
        raise HistoricalEvidenceAccessError(
            "authorized privacy scopes must be unique"
        )
    if type(retrieved_at) is not str or not retrieved_at:
        raise ValueError("retrieved_at must be a non-empty exact string")

    allowed = set(authorized_privacy_scopes)
    visible: list[HistoricalEvidenceRecord] = []
    for record in records:
        if type(record) is not HistoricalEvidenceRecord:
            raise TypeError(
                "records must contain exact HistoricalEvidenceRecord values"
            )
        if record.privacy_scope in allowed:
            visible.append(record)

    return HistoricalEvidenceResult(
        records=tuple(visible),
        authorized_privacy_scopes=authorized_privacy_scopes,
        retrieved_at=retrieved_at,
    )
