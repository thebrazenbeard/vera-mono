from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TargetKind(StrEnum):
    WORD = "WORD"
    PHRASE = "PHRASE"
    CONCEPT = "CONCEPT"
    CLAIM = "CLAIM"
    DECISION = "DECISION"
    EVENT = "EVENT"
    RULE = "RULE"
    IDENTIFIER = "IDENTIFIER"
    OTHER = "OTHER"


class RetrievalMethod(StrEnum):
    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    ALIAS = "ALIAS"
    BACK_REFERENCE = "BACK_REFERENCE"
    SEMANTIC = "SEMANTIC"
    VECTOR = "VECTOR"
    GRAPH = "GRAPH"
    MANUAL = "MANUAL"
    GIT_HISTORY = "GIT_HISTORY"


class EpistemicStatus(StrEnum):
    DIRECT_SOURCE = "DIRECT_SOURCE"
    DOCUMENTED_METADATA = "DOCUMENTED_METADATA"
    SUPPORTED_INFERENCE = "SUPPORTED_INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


class OccurrenceRelation(StrEnum):
    EARLIEST_ACCESSIBLE_EVIDENCE = "EARLIEST_ACCESSIBLE_EVIDENCE"
    ORIGIN_CLAIM = "ORIGIN_CLAIM"
    FIRST_LITERAL_OCCURRENCE = "FIRST_LITERAL_OCCURRENCE"
    CONCEPTUAL_ANCESTOR = "CONCEPTUAL_ANCESTOR"
    DERIVATION = "DERIVATION"
    REUSE = "REUSE"
    REINTERPRETATION = "REINTERPRETATION"
    FORMALIZATION = "FORMALIZATION"
    CORRECTION = "CORRECTION"
    SUPERSESSION = "SUPERSESSION"
    CONTRADICTION = "CONTRADICTION"
    CURRENT_MEANING = "CURRENT_MEANING"


class EdgeRelation(StrEnum):
    INSPIRED = "INSPIRED"
    DERIVED_INTO = "DERIVED_INTO"
    REUSED_AS = "REUSED_AS"
    REINTERPRETED_AS = "REINTERPRETED_AS"
    FORMALIZED_AS = "FORMALIZED_AS"
    CORRECTED_BY = "CORRECTED_BY"
    SUPERSEDED_BY = "SUPERSEDED_BY"
    CONTRADICTS = "CONTRADICTS"
    REFERENCES = "REFERENCES"
    CLAIMS_ORIGIN_IN = "CLAIMS_ORIGIN_IN"


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class OriginStatus(StrEnum):
    ESTABLISHED = "ESTABLISHED"
    EARLIEST_ACCESSIBLE_ONLY = "EARLIEST_ACCESSIBLE_ONLY"
    MULTIPLE_CLAIMS = "MULTIPLE_CLAIMS"
    UNRESOLVED = "UNRESOLVED"


class Completeness(StrEnum):
    COMPLETE_RELATIVE_TO_ACCESSIBLE_SOURCES = "COMPLETE_RELATIVE_TO_ACCESSIBLE_SOURCES"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"
    NO_EVIDENCE = "NO_EVIDENCE"


class TemporalPrecision(StrEnum):
    EXACT = "EXACT"
    SECOND = "SECOND"
    MINUTE = "MINUTE"
    HOUR = "HOUR"
    DAY = "DAY"
    MONTH = "MONTH"
    YEAR = "YEAR"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TimeBounds:
    start: datetime | None
    end: datetime | None
    precision: TemporalPrecision


@dataclass(frozen=True, slots=True)
class TargetSpec:
    target_id: str
    kind: TargetKind
    query_original: str
    literal_forms: tuple[str, ...] = ()
    normalized_forms: tuple[str, ...] = ()
    semantic_description: str | None = None
    aliases: tuple[str, ...] = ()
    source_surfaces: tuple[str, ...] = ()
    time_start: datetime | None = None
    time_end: datetime | None = None

    @classmethod
    def from_cli(cls, query: str, kind: TargetKind = TargetKind.PHRASE) -> "TargetSpec":
        import hashlib

        target_id = hashlib.sha256(f"{kind.value}:{query}".encode("utf-8")).hexdigest()[:16]
        return cls(
            target_id=target_id,
            kind=kind,
            query_original=query,
            literal_forms=(query,),
        )


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    record_id: str
    source_surface: str
    source_locator: str
    retrieval_method: RetrievalMethod
    epistemic_status: EpistemicStatus
    content: str
    event_time: TimeBounds
    source_record_id: str | None = None
    author: str | None = None
    ingested_at: datetime | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    record_id: str
    source_locator: str | None = None


@dataclass(frozen=True, slots=True)
class OccurrenceAssessment:
    record_id: str
    relations: tuple[OccurrenceRelation, ...]
    literal_match: str | None = None
    semantic_match: str | None = None
    assessment_basis: tuple[EvidenceRef, ...] = ()
    confidence: Confidence = Confidence.UNRESOLVED
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class LineageEdge:
    edge_id: str
    from_record_id: str
    to_record_id: str
    relation: EdgeRelation
    basis: tuple[EvidenceRef, ...] = ()
    epistemic_status: EpistemicStatus = EpistemicStatus.SUPPORTED_INFERENCE
    confidence: Confidence = Confidence.UNRESOLVED


@dataclass(frozen=True, slots=True)
class SourceAttempt:
    source: str
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Gap:
    gap_id: str
    description: str
    before_record_id: str | None = None
    after_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class UnresolvedReference:
    reference_id: str
    source_record_id: str
    target: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Conflict:
    conflict_id: str
    record_ids: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    code: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ProvenanceReceipt:
    schema_version: int
    trace_id: str
    target: TargetSpec
    started_at: datetime
    completed_at: datetime
    source_attempts: tuple[SourceAttempt, ...]
    completeness: Completeness
    earliest_accessible_evidence: tuple[str, ...]
    first_literal_occurrence: tuple[str, ...]
    conceptual_ancestors: tuple[str, ...]
    current_meaning: tuple[str, ...]
    origin_status: OriginStatus
    events: tuple[EvidenceEvent, ...]
    assessments: tuple[OccurrenceAssessment, ...]
    edges: tuple[LineageEdge, ...]
    conflicts: tuple[Conflict, ...]
    gaps: tuple[Gap, ...]
    unresolved_references: tuple[UnresolvedReference, ...]
    verification: tuple[CheckResult, ...]
    limitations: tuple[str, ...] = ()
