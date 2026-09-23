"""Fail-closed temporal enforcement for V.E.R.A.

The language model is treated as an intelligent but untrusted component.
Externally issued evidence must be bound to the exact subject it supports and
verified by a host-owned adapter. Generated labels such as ``system=HOST`` or
``confirmed=True`` are not self-authenticating.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5


class AnchorStatus(str, Enum):
    ANCHORED = "ANCHORED"
    UNANCHORED = "UNANCHORED"


class TemporalPrecision(str, Enum):
    EXACT = "EXACT"
    BOUNDED = "BOUNDED"
    APPROXIMATE = "APPROXIMATE"
    UNKNOWN = "UNKNOWN"


class ElapsedStatus(str, Enum):
    EXACT = "EXACT"
    BOUNDED = "BOUNDED"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICTED = "CONFLICTED"


class ScopeStability(str, Enum):
    STABLE = "STABLE"
    EPHEMERAL = "EPHEMERAL"


class EvidenceSystem(str, Enum):
    HOST = "HOST"
    SUPABASE = "SUPABASE"
    BASIC_MEMORY = "BASIC_MEMORY"
    GITHUB = "GITHUB"
    MODEL = "MODEL"
    OTHER = "OTHER"


class Workstream(str, Enum):
    TIME = "workstream/time"
    MEMORY = "workstream/memory"
    INITIATIVES = "workstream/initiatives"
    INTEGRATION = "workstream/integration"


TRUSTED_NOW_SYSTEMS = frozenset({EvidenceSystem.HOST, EvidenceSystem.SUPABASE})
IMMUTABLE_EVIDENCE_SYSTEMS = frozenset({EvidenceSystem.SUPABASE, EvidenceSystem.GITHUB})
TEMPORAL_READ_SYSTEMS = frozenset(
    {EvidenceSystem.SUPABASE, EvidenceSystem.BASIC_MEMORY, EvidenceSystem.GITHUB}
)


def _new_uuid() -> UUID:
    """Private UUID source so callers cannot select ephemeral identities."""

    return uuid4()


def _as_aware_datetime(value: datetime | str | None, field_name: str) -> datetime:
    if value is None:
        raise ValueError(f"{field_name} is required")
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime or ISO-8601 string")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value.astimezone(timezone.utc)


def _iso(value: datetime | str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _as_aware_datetime(value, field_name).isoformat().replace("+00:00", "Z")


def _nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{field_name} may not have surrounding whitespace")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field_name} may not contain control characters")
    return value


def _sha256(value: str, field_name: str) -> str:
    value = _nonblank(value, field_name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _iso(value, "datetime")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonical(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_subject_hash(kind: str, payload: Mapping[str, object]) -> str:
    """Bind external evidence to one exact operation subject."""

    body = {"kind": _nonblank(kind, "kind"), "payload": _canonical(payload)}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ExternalEvidence:
    """An evidence claim that still requires verification by an external adapter."""

    system: EvidenceSystem
    operation: str
    confirmed: bool
    reference_id: str | None
    observed_at: datetime | str | None
    subject_hash: str | None
    immutable: bool = False

    def validate_shape(self) -> None:
        _nonblank(self.operation, "operation")
        if self.system is EvidenceSystem.MODEL and self.confirmed:
            raise ValueError("model output cannot be confirmed external evidence")
        if self.confirmed:
            _nonblank(self.reference_id or "", "reference_id")
            _as_aware_datetime(self.observed_at, "observed_at")
            _sha256(self.subject_hash or "", "subject_hash")
        else:
            if self.reference_id is not None and not self.reference_id.strip():
                raise ValueError("reference_id may not be blank")
            if self.subject_hash is not None:
                _sha256(self.subject_hash, "subject_hash")
        if self.immutable and self.system not in IMMUTABLE_EVIDENCE_SYSTEMS:
            raise ValueError("immutable evidence must come from an immutable-capable system")


class EvidenceVerifier(Protocol):
    """Host-owned trust boundary for connector/tool evidence.

    The verifier must be constructed outside model generation from actual host or
    connector results. Passing a model-created verifier defeats the architecture.
    """

    def verify(
        self,
        evidence: ExternalEvidence,
        *,
        allowed_systems: frozenset[EvidenceSystem],
        operation: str,
        subject_hash: str,
        require_immutable: bool = False,
    ) -> bool:
        ...


@dataclass(frozen=True)
class ResolvedScope:
    project_id: str
    conversation_id: str
    branch_id: str
    session_id: str
    scope_instance_id: str
    checkpoint_id: str | None
    stability: ScopeStability
    provider_conversation_id: str | None
    provider_branch_id: str | None
    generated_at: datetime
    limitations: tuple[str, ...] = ()

    def validate(self) -> None:
        for name in ("project_id", "conversation_id", "branch_id", "session_id", "scope_instance_id"):
            _nonblank(getattr(self, name), name)
        _as_aware_datetime(self.generated_at, "generated_at")
        identities = [self.conversation_id, self.branch_id, self.session_id, self.scope_instance_id]
        if self.checkpoint_id is not None:
            _nonblank(self.checkpoint_id, "checkpoint_id")
            identities.append(self.checkpoint_id)
        if len(set(identities)) != len(identities):
            raise ValueError("conversation, branch, session, scope, and checkpoint identities must be distinct")
        if self.stability is ScopeStability.STABLE:
            _nonblank(self.provider_conversation_id or "", "provider_conversation_id")
            _nonblank(self.provider_branch_id or "", "provider_branch_id")
        else:
            if self.provider_conversation_id is not None or self.provider_branch_id is not None:
                raise ValueError("ephemeral scope may not claim provider identifiers")


def resolve_scope(
    *,
    project_id: str,
    observed_at: datetime | str,
    provider_conversation_id: str | None = None,
    provider_branch_id: str | None = None,
    checkpoint_id: str | None = None,
) -> ResolvedScope:
    """Resolve stable host scope or issue fresh ephemeral scope internally."""

    project_id = _nonblank(project_id, "project_id")
    generated_at = _as_aware_datetime(observed_at, "observed_at")
    session_id = f"session:{_new_uuid()}"

    if provider_conversation_id is not None and provider_branch_id is not None:
        provider_conversation_id = _nonblank(provider_conversation_id, "provider_conversation_id")
        provider_branch_id = _nonblank(provider_branch_id, "provider_branch_id")
        conversation_id = f"conversation:{provider_conversation_id}"
        branch_id = f"branch:{provider_branch_id}"
        stable_key = f"{project_id}|{provider_conversation_id}|{provider_branch_id}"
        scope_instance_id = f"scope:{uuid5(NAMESPACE_URL, stable_key)}"
        stability = ScopeStability.STABLE
        limitations: tuple[str, ...] = ()
    elif provider_conversation_id is None and provider_branch_id is None:
        conversation_id = f"conversation:ephemeral:{_new_uuid()}"
        branch_id = f"branch:ephemeral:{_new_uuid()}"
        scope_instance_id = f"scope:ephemeral:{_new_uuid()}"
        stability = ScopeStability.EPHEMERAL
        limitations = (
            "Host did not expose stable conversation or branch identifiers.",
            "This scope supports only the current execution and proves no durable recognition.",
        )
    else:
        raise ValueError("provider conversation and branch identifiers must be supplied together")

    scope = ResolvedScope(
        project_id=project_id,
        conversation_id=conversation_id,
        branch_id=branch_id,
        session_id=session_id,
        scope_instance_id=scope_instance_id,
        checkpoint_id=checkpoint_id,
        stability=stability,
        provider_conversation_id=provider_conversation_id,
        provider_branch_id=provider_branch_id,
        generated_at=generated_at,
        limitations=limitations,
    )
    scope.validate()
    return scope


def current_time_subject_hash(now: datetime | str) -> str:
    return canonical_subject_hash("current_time", {"now": _iso(now, "now")})


def scope_subject_hash(scope: ResolvedScope) -> str:
    scope.validate()
    return canonical_subject_hash(
        "resolved_scope",
        {
            "project_id": scope.project_id,
            "conversation_id": scope.conversation_id,
            "branch_id": scope.branch_id,
            "session_id": scope.session_id,
            "scope_instance_id": scope.scope_instance_id,
            "checkpoint_id": scope.checkpoint_id,
            "stability": scope.stability,
            "provider_conversation_id": scope.provider_conversation_id,
            "provider_branch_id": scope.provider_branch_id,
            "generated_at": scope.generated_at,
        },
    )


@dataclass(frozen=True)
class TemporalPoint:
    precision: TemporalPrecision
    source: ExternalEvidence
    scope_instance_id: str
    event_time: datetime | str | None = None
    state_time: datetime | str | None = None
    record_time: datetime | str | None = None
    retrieval_time: datetime | str | None = None
    lower_bound: datetime | str | None = None
    upper_bound: datetime | str | None = None

    def validate_shape(self) -> None:
        self.source.validate_shape()
        if not self.source.confirmed:
            raise ValueError("temporal point requires confirmed evidence claim")
        _nonblank(self.scope_instance_id, "scope_instance_id")

        event = _as_aware_datetime(self.event_time, "event_time") if self.event_time is not None else None
        lower = _as_aware_datetime(self.lower_bound, "lower_bound") if self.lower_bound is not None else None
        upper = _as_aware_datetime(self.upper_bound, "upper_bound") if self.upper_bound is not None else None
        for name, value in (
            ("state_time", self.state_time),
            ("record_time", self.record_time),
            ("retrieval_time", self.retrieval_time),
        ):
            if value is not None:
                _as_aware_datetime(value, name)

        if self.precision is TemporalPrecision.EXACT:
            if event is None or lower is not None or upper is not None:
                raise ValueError("EXACT requires event_time and forbids bounds")
        elif self.precision is TemporalPrecision.BOUNDED:
            if event is None or lower is None or upper is None:
                raise ValueError("BOUNDED requires event_time and both inclusive bounds")
            if lower > upper:
                raise ValueError("lower_bound may not exceed upper_bound")
            if not lower <= event <= upper:
                raise ValueError("event_time must fall inside inclusive bounds")
        elif self.precision is TemporalPrecision.APPROXIMATE:
            if event is None or lower is not None or upper is not None:
                raise ValueError("APPROXIMATE requires event_time and forbids hard bounds")
        elif self.precision is TemporalPrecision.UNKNOWN:
            if event is not None or lower is not None or upper is not None:
                raise ValueError("UNKNOWN forbids event_time and bounds")

    @property
    def best_time(self) -> datetime | None:
        return None if self.event_time is None else _as_aware_datetime(self.event_time, "event_time")

    @property
    def freshness_time(self) -> datetime | None:
        """When this anchor was last externally materialized as usable state.

        Record time is preferred over state/event time. A correction recorded now
        about an old event is not stale merely because the represented event is old.
        """

        for name, value in (
            ("record_time", self.record_time),
            ("state_time", self.state_time),
            ("event_time", self.event_time),
        ):
            if value is not None:
                return _as_aware_datetime(value, name)
        return None

    def interval(self) -> tuple[datetime, datetime] | None:
        self.validate_shape()
        if self.precision is TemporalPrecision.UNKNOWN:
            return None
        if self.precision is TemporalPrecision.BOUNDED:
            return (
                _as_aware_datetime(self.lower_bound, "lower_bound"),
                _as_aware_datetime(self.upper_bound, "upper_bound"),
            )
        if self.precision is TemporalPrecision.EXACT:
            best = self.best_time
            assert best is not None
            return best, best
        return None


def temporal_point_subject_hash(point: TemporalPoint) -> str:
    point.validate_shape()
    return canonical_subject_hash(
        "temporal_point",
        {
            "scope_instance_id": point.scope_instance_id,
            "precision": point.precision,
            "event_time": _iso(point.event_time, "event_time") if point.event_time is not None else None,
            "state_time": _iso(point.state_time, "state_time") if point.state_time is not None else None,
            "record_time": _iso(point.record_time, "record_time") if point.record_time is not None else None,
            "retrieval_time": _iso(point.retrieval_time, "retrieval_time") if point.retrieval_time is not None else None,
            "lower_bound": _iso(point.lower_bound, "lower_bound") if point.lower_bound is not None else None,
            "upper_bound": _iso(point.upper_bound, "upper_bound") if point.upper_bound is not None else None,
            "source_system": point.source.system,
            "source_operation": point.source.operation,
            "source_reference_id": point.source.reference_id,
        },
    )


@dataclass(frozen=True)
class TemporalAnchor:
    anchor_id: str
    anchor_key: str
    scope_instance_id: str
    status: AnchorStatus
    point: TemporalPoint
    workstream: Workstream = Workstream.TIME

    def validate_shape(self) -> None:
        _nonblank(self.anchor_id, "anchor_id")
        _nonblank(self.anchor_key, "anchor_key")
        _nonblank(self.scope_instance_id, "scope_instance_id")
        self.point.validate_shape()
        if self.scope_instance_id != self.point.scope_instance_id:
            raise ValueError("anchor and temporal point scope must match")
        if self.status is not AnchorStatus.ANCHORED:
            raise ValueError("prior anchors must be ANCHORED")


def anchor_subject_hash(anchor: TemporalAnchor) -> str:
    anchor.validate_shape()
    return canonical_subject_hash(
        "temporal_anchor",
        {
            "anchor_id": anchor.anchor_id,
            "anchor_key": anchor.anchor_key,
            "scope_instance_id": anchor.scope_instance_id,
            "status": anchor.status,
            "workstream": anchor.workstream,
            "point_subject_hash": temporal_point_subject_hash(anchor.point),
        },
    )


@dataclass(frozen=True)
class CoordinationEvent:
    event_id: str
    event_sequence: int
    thread_key: str
    source_workstream: Workstream
    target_workstream: Workstream | None
    event_type: str
    status: str
    record_time: datetime | str
    acknowledges_event_id: str | None = None

    def validate_shape(self) -> None:
        _nonblank(self.event_id, "event_id")
        if self.event_sequence <= 0:
            raise ValueError("event_sequence must be positive")
        _nonblank(self.thread_key, "thread_key")
        _nonblank(self.event_type, "event_type")
        _nonblank(self.status, "status")
        _as_aware_datetime(self.record_time, "record_time")
        if self.acknowledges_event_id is not None:
            _nonblank(self.acknowledges_event_id, "acknowledges_event_id")


def coordination_inbox_subject_hash(
    workstream: Workstream,
    events: tuple[CoordinationEvent, ...],
) -> str:
    canonical_events: list[dict[str, object]] = []
    for event in events:
        event.validate_shape()
        canonical_events.append(
            {
                "event_id": event.event_id,
                "event_sequence": event.event_sequence,
                "thread_key": event.thread_key,
                "source_workstream": event.source_workstream,
                "target_workstream": event.target_workstream,
                "event_type": event.event_type,
                "status": event.status,
                "record_time": _iso(event.record_time, "record_time"),
                "acknowledges_event_id": event.acknowledges_event_id,
            }
        )
    canonical_events.sort(key=lambda item: (int(item["event_sequence"]), str(item["event_id"])))
    return canonical_subject_hash(
        "coordination_inbox",
        {"workstream": workstream, "events": canonical_events},
    )


@dataclass(frozen=True)
class PreflightRequest:
    workstream: Workstream
    now: datetime | str | None
    now_evidence: ExternalEvidence | None
    scope: ResolvedScope | None
    scope_evidence: ExternalEvidence | None
    coordination_inbox_checked: bool
    coordination_read_evidence: ExternalEvidence | None
    coordination_events: tuple[CoordinationEvent, ...] = ()
    retrieval_required: bool = False
    retrieval_evidence: ExternalEvidence | None = None
    retrieval_subject_hash: str | None = None
    prior_anchor_required: bool = False
    prior_anchor: TemporalAnchor | None = None
    maximum_anchor_age: timedelta = timedelta(days=30)
    immutable_proof_required: bool = False
    model_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreflightDecision:
    status: AnchorStatus
    reasons: tuple[str, ...]
    trusted_now: datetime | None
    scope: ResolvedScope | None
    addressed_events: tuple[CoordinationEvent, ...]
    prior_anchor: TemporalAnchor | None
    limitations: tuple[str, ...]

    @property
    def may_reason_temporally(self) -> bool:
        return self.status is AnchorStatus.ANCHORED


@dataclass(frozen=True)
class RequiredHandoff:
    target_workstream: Workstream
    subject_hash: str

    def validate(self) -> None:
        _sha256(self.subject_hash, "subject_hash")


@dataclass(frozen=True)
class HandoffEvidence:
    target_workstream: Workstream
    write_evidence: ExternalEvidence


@dataclass(frozen=True)
class PostflightRequest:
    preflight: PreflightDecision
    material_transition: bool
    transition_subject_hash: str | None = None
    temporal_write_evidence: ExternalEvidence | None = None
    required_handoffs: tuple[RequiredHandoff, ...] = ()
    handoff_evidence: tuple[HandoffEvidence, ...] = ()
    model_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnTemporalResult:
    status: AnchorStatus
    reasons: tuple[str, ...]
    temporal_reference_id: str | None
    handoff_reference_ids: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ElapsedResult:
    status: ElapsedStatus
    best_seconds: float | None
    lower_seconds: float | None
    upper_seconds: float | None
    reasons: tuple[str, ...] = ()


def _verified_evidence(
    verifier: EvidenceVerifier | None,
    evidence: ExternalEvidence | None,
    *,
    allowed_systems: frozenset[EvidenceSystem],
    operation: str,
    subject_hash: str,
    require_immutable: bool = False,
) -> bool:
    if verifier is None or evidence is None:
        return False
    try:
        evidence.validate_shape()
        _sha256(subject_hash, "subject_hash")
    except ValueError:
        return False
    if not evidence.confirmed:
        return False
    try:
        return bool(
            verifier.verify(
                evidence,
                allowed_systems=allowed_systems,
                operation=operation,
                subject_hash=subject_hash,
                require_immutable=require_immutable,
            )
        )
    except Exception:
        return False


def run_preflight(
    request: PreflightRequest,
    verifier: EvidenceVerifier | None,
) -> PreflightDecision:
    """Evaluate the mandatory temporal gate before temporal reasoning."""

    reasons: list[str] = []
    limitations: list[str] = []
    trusted_now: datetime | None = None

    if verifier is None:
        reasons.append("EVIDENCE_VERIFIER_MISSING")

    try:
        trusted_now = _as_aware_datetime(request.now, "now")
    except ValueError:
        reasons.append("TRUSTED_NOW_INVALID")
    else:
        if not _verified_evidence(
            verifier,
            request.now_evidence,
            allowed_systems=TRUSTED_NOW_SYSTEMS,
            operation="current_time",
            subject_hash=current_time_subject_hash(trusted_now),
        ):
            reasons.append("TRUSTED_NOW_UNVERIFIED")

    if request.scope is None:
        reasons.append("SCOPE_UNRESOLVED")
    else:
        try:
            request.scope.validate()
        except ValueError:
            reasons.append("SCOPE_INVALID")
        else:
            limitations.extend(request.scope.limitations)
            if request.scope.stability is ScopeStability.STABLE:
                if not _verified_evidence(
                    verifier,
                    request.scope_evidence,
                    allowed_systems=frozenset({EvidenceSystem.HOST}),
                    operation="resolve_scope",
                    subject_hash=scope_subject_hash(request.scope),
                ):
                    reasons.append("STABLE_SCOPE_UNVERIFIED")

    if not request.coordination_inbox_checked:
        reasons.append("COORDINATION_INBOX_NOT_CHECKED")
    else:
        try:
            inbox_hash = coordination_inbox_subject_hash(request.workstream, request.coordination_events)
        except ValueError:
            reasons.append("COORDINATION_EVENT_INVALID")
            inbox_hash = canonical_subject_hash(
                "coordination_inbox",
                {"workstream": request.workstream, "events": []},
            )
        if not _verified_evidence(
            verifier,
            request.coordination_read_evidence,
            allowed_systems=frozenset({EvidenceSystem.SUPABASE}),
            operation="coordination_read_inbox",
            subject_hash=inbox_hash,
        ):
            reasons.append("COORDINATION_INBOX_UNVERIFIED")

    addressed: list[CoordinationEvent] = []
    seen_sequences: set[int] = set()
    for event in request.coordination_events:
        try:
            event.validate_shape()
        except ValueError:
            reasons.append("COORDINATION_EVENT_INVALID")
            continue
        if event.event_sequence in seen_sequences:
            reasons.append("COORDINATION_SEQUENCE_CONFLICT")
        seen_sequences.add(event.event_sequence)
        if event.target_workstream in (None, request.workstream):
            addressed.append(event)

    if request.retrieval_required:
        try:
            retrieval_hash = _sha256(request.retrieval_subject_hash or "", "retrieval_subject_hash")
        except ValueError:
            reasons.append("TEMPORAL_RETRIEVAL_SUBJECT_MISSING")
        else:
            if not _verified_evidence(
                verifier,
                request.retrieval_evidence,
                allowed_systems=TEMPORAL_READ_SYSTEMS,
                operation="temporal_retrieval",
                subject_hash=retrieval_hash,
                require_immutable=request.immutable_proof_required,
            ):
                reasons.append("TEMPORAL_RETRIEVAL_UNVERIFIED")

    if request.prior_anchor_required and request.prior_anchor is None:
        reasons.append("PRIOR_ANCHOR_MISSING")

    if request.maximum_anchor_age < timedelta(0):
        reasons.append("MAXIMUM_ANCHOR_AGE_INVALID")

    if request.prior_anchor is not None:
        try:
            request.prior_anchor.validate_shape()
        except ValueError:
            reasons.append("PRIOR_ANCHOR_INVALID")
        else:
            expected_anchor_hash = temporal_point_subject_hash(request.prior_anchor.point)
            if not _verified_evidence(
                verifier,
                request.prior_anchor.point.source,
                allowed_systems=TEMPORAL_READ_SYSTEMS,
                operation="temporal_read",
                subject_hash=expected_anchor_hash,
                require_immutable=request.immutable_proof_required,
            ):
                reasons.append("PRIOR_ANCHOR_EVIDENCE_UNVERIFIED")
            if request.scope is not None and request.prior_anchor.scope_instance_id != request.scope.scope_instance_id:
                reasons.append("PRIOR_ANCHOR_SCOPE_MISMATCH")
            if trusted_now is not None:
                event_time = request.prior_anchor.point.best_time
                if event_time is not None and event_time > trusted_now:
                    reasons.append("PRIOR_ANCHOR_FROM_FUTURE")
                freshness_time = request.prior_anchor.point.freshness_time
                if freshness_time is None:
                    reasons.append("PRIOR_ANCHOR_FRESHNESS_UNAVAILABLE")
                elif trusted_now < freshness_time:
                    reasons.append("PRIOR_ANCHOR_RECORDED_IN_FUTURE")
                elif trusted_now - freshness_time > request.maximum_anchor_age:
                    reasons.append("PRIOR_ANCHOR_STALE")

    if request.model_claims:
        limitations.append("Model claims were ignored as temporal evidence.")

    status = AnchorStatus.ANCHORED if not reasons else AnchorStatus.UNANCHORED
    return PreflightDecision(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        trusted_now=trusted_now,
        scope=request.scope,
        addressed_events=tuple(sorted(addressed, key=lambda event: event.event_sequence)),
        prior_anchor=request.prior_anchor,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def run_postflight(
    request: PostflightRequest,
    verifier: EvidenceVerifier | None,
) -> TurnTemporalResult:
    """Evaluate persistence and handoff evidence after reasoning."""

    reasons: list[str] = []
    limitations = list(request.preflight.limitations)
    temporal_reference: str | None = None
    handoff_references: list[str] = []

    if verifier is None:
        reasons.append("EVIDENCE_VERIFIER_MISSING")
    if request.preflight.status is not AnchorStatus.ANCHORED:
        reasons.append("PREFLIGHT_UNANCHORED")

    if request.material_transition:
        try:
            transition_hash = _sha256(request.transition_subject_hash or "", "transition_subject_hash")
        except ValueError:
            reasons.append("MATERIAL_TRANSITION_SUBJECT_MISSING")
        else:
            if not _verified_evidence(
                verifier,
                request.temporal_write_evidence,
                allowed_systems=frozenset({EvidenceSystem.SUPABASE}),
                operation="append_temporal_event",
                subject_hash=transition_hash,
                require_immutable=True,
            ):
                reasons.append("MATERIAL_TRANSITION_NOT_PERSISTED")
            else:
                assert request.temporal_write_evidence is not None
                temporal_reference = request.temporal_write_evidence.reference_id

    evidence_by_target: dict[Workstream, ExternalEvidence] = {}
    duplicate_targets: set[Workstream] = set()
    for handoff in request.handoff_evidence:
        if handoff.target_workstream in evidence_by_target:
            duplicate_targets.add(handoff.target_workstream)
            continue
        evidence_by_target[handoff.target_workstream] = handoff.write_evidence
    for target in duplicate_targets:
        reasons.append(f"DUPLICATE_HANDOFF_EVIDENCE:{target.value}")

    required_by_target: dict[Workstream, RequiredHandoff] = {}
    for required in request.required_handoffs:
        try:
            required.validate()
        except ValueError:
            reasons.append(f"HANDOFF_SUBJECT_INVALID:{required.target_workstream.value}")
            continue
        if required.target_workstream in required_by_target:
            reasons.append(f"DUPLICATE_REQUIRED_HANDOFF:{required.target_workstream.value}")
            continue
        required_by_target[required.target_workstream] = required

    used_references: set[str] = set()
    for target, required in required_by_target.items():
        evidence = evidence_by_target.get(target)
        if not _verified_evidence(
            verifier,
            evidence,
            allowed_systems=frozenset({EvidenceSystem.SUPABASE}),
            operation="coordination_post",
            subject_hash=required.subject_hash,
            require_immutable=True,
        ):
            reasons.append(f"REQUIRED_HANDOFF_UNCONFIRMED:{target.value}")
            continue
        assert evidence is not None and evidence.reference_id is not None
        if evidence.reference_id in used_references:
            reasons.append("HANDOFF_REFERENCE_REUSED")
            continue
        used_references.add(evidence.reference_id)
        handoff_references.append(evidence.reference_id)

    if request.model_claims:
        limitations.append("Model claims of saving or delivery were ignored.")

    status = AnchorStatus.ANCHORED if not reasons else AnchorStatus.UNANCHORED
    return TurnTemporalResult(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        temporal_reference_id=temporal_reference,
        handoff_reference_ids=tuple(handoff_references),
        limitations=tuple(dict.fromkeys(limitations)),
    )


def elapsed_between(start: TemporalPoint, end: TemporalPoint) -> ElapsedResult:
    """Calculate elapsed time without inventing precision."""

    try:
        start.validate_shape()
        end.validate_shape()
    except ValueError as exc:
        return ElapsedResult(ElapsedStatus.CONFLICTED, None, None, None, (str(exc),))

    if start.scope_instance_id != end.scope_instance_id:
        return ElapsedResult(
            ElapsedStatus.CONFLICTED,
            None,
            None,
            None,
            ("Elapsed endpoints belong to different scope instances.",),
        )
    if start.precision is TemporalPrecision.UNKNOWN or end.precision is TemporalPrecision.UNKNOWN:
        return ElapsedResult(
            ElapsedStatus.UNAVAILABLE,
            None,
            None,
            None,
            ("At least one endpoint has UNKNOWN temporal precision.",),
        )

    start_best = start.best_time
    end_best = end.best_time
    assert start_best is not None and end_best is not None
    best = (end_best - start_best).total_seconds()
    if best < 0:
        return ElapsedResult(
            ElapsedStatus.CONFLICTED,
            None,
            None,
            None,
            ("Best-supported end time precedes start time.",),
        )

    if TemporalPrecision.APPROXIMATE in (start.precision, end.precision):
        return ElapsedResult(ElapsedStatus.APPROXIMATE, best, None, None)

    start_interval = start.interval()
    end_interval = end.interval()
    assert start_interval is not None and end_interval is not None
    raw_lower = (end_interval[0] - start_interval[1]).total_seconds()
    upper = (end_interval[1] - start_interval[0]).total_seconds()
    if upper < 0:
        return ElapsedResult(
            ElapsedStatus.CONFLICTED,
            None,
            None,
            None,
            ("The supported end interval is fully earlier than the start interval.",),
        )
    if start.precision is TemporalPrecision.EXACT and end.precision is TemporalPrecision.EXACT:
        return ElapsedResult(ElapsedStatus.EXACT, best, best, best)
    return ElapsedResult(ElapsedStatus.BOUNDED, best, max(0.0, raw_lower), upper)


def canonical_turn_hash(payload: Mapping[str, object]) -> str:
    """Hash an externally supplied turn subject for idempotency and binding."""

    return canonical_subject_hash("turn", payload)
