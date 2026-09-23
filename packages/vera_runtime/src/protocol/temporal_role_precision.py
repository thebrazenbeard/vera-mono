"""Role-specific temporal precision for the V.E.R.A. enforcement kernel.

The strict layer keeps event, state, record, and retrieval time independent.
Persistence time never substitutes for represented-state freshness, and elapsed
calculations must name the temporal role they compare.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from . import temporal_enforcement as legacy


class TemporalRole(str, Enum):
    EVENT_TIME = "event_time"
    STATE_TIME = "state_time"
    RECORD_TIME = "record_time"
    RETRIEVAL_TIME = "retrieval_time"


MEMORY_UNKNOWN_STATE_TIME_SENTINEL = "-infinity"


def _normalize_role(role: TemporalRole | str) -> TemporalRole:
    if isinstance(role, TemporalRole):
        return role
    try:
        return TemporalRole(role)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported temporal role: {role!r}") from exc


@dataclass(frozen=True)
class RoleTemporalPoint:
    """A temporal point with independent uncertainty for every time role."""

    source: legacy.ExternalEvidence
    scope_instance_id: str
    event_time: datetime | str | None = None
    event_time_precision: legacy.TemporalPrecision = legacy.TemporalPrecision.UNKNOWN
    event_time_lower_bound: datetime | str | None = None
    event_time_upper_bound: datetime | str | None = None
    state_time: datetime | str | None = None
    state_time_precision: legacy.TemporalPrecision = legacy.TemporalPrecision.UNKNOWN
    state_time_lower_bound: datetime | str | None = None
    state_time_upper_bound: datetime | str | None = None
    record_time: datetime | str | None = None
    record_time_precision: legacy.TemporalPrecision = legacy.TemporalPrecision.UNKNOWN
    record_time_lower_bound: datetime | str | None = None
    record_time_upper_bound: datetime | str | None = None
    retrieval_time: datetime | str | None = None
    retrieval_time_precision: legacy.TemporalPrecision = legacy.TemporalPrecision.UNKNOWN
    retrieval_time_lower_bound: datetime | str | None = None
    retrieval_time_upper_bound: datetime | str | None = None

    def _validate_role(
        self,
        *,
        role: str,
        value: datetime | str | None,
        precision: legacy.TemporalPrecision,
        lower_bound: datetime | str | None,
        upper_bound: datetime | str | None,
    ) -> None:
        if not isinstance(precision, legacy.TemporalPrecision):
            raise ValueError(f"{role}_precision must be a TemporalPrecision")

        normalized = (
            legacy._as_aware_datetime(value, role) if value is not None else None
        )
        lower = (
            legacy._as_aware_datetime(lower_bound, f"{role}_lower_bound")
            if lower_bound is not None
            else None
        )
        upper = (
            legacy._as_aware_datetime(upper_bound, f"{role}_upper_bound")
            if upper_bound is not None
            else None
        )

        if precision is legacy.TemporalPrecision.EXACT:
            if normalized is None or lower is not None or upper is not None:
                raise ValueError(f"EXACT {role} requires a value and forbids bounds")
        elif precision is legacy.TemporalPrecision.BOUNDED:
            if normalized is None or lower is None or upper is None:
                raise ValueError(
                    f"BOUNDED {role} requires a value and both inclusive bounds"
                )
            if lower > upper or not lower <= normalized <= upper:
                raise ValueError(f"BOUNDED {role} has inconsistent bounds")
        elif precision is legacy.TemporalPrecision.APPROXIMATE:
            if normalized is None or lower is not None or upper is not None:
                raise ValueError(
                    f"APPROXIMATE {role} requires a value and forbids hard bounds"
                )
        elif precision is legacy.TemporalPrecision.UNKNOWN:
            if normalized is not None or lower is not None or upper is not None:
                raise ValueError(f"UNKNOWN {role} forbids values and bounds")

    def validate_shape(self) -> None:
        self.source.validate_shape()
        if not self.source.confirmed:
            raise ValueError("role temporal point requires confirmed evidence claim")
        legacy._nonblank(self.scope_instance_id, "scope_instance_id")

        for role in TemporalRole:
            self._validate_role(
                role=role.value,
                value=self.role_value(role),
                precision=self.role_precision(role),
                lower_bound=self.role_lower_bound(role),
                upper_bound=self.role_upper_bound(role),
            )

    def role_value(self, role: TemporalRole | str) -> datetime | str | None:
        normalized = _normalize_role(role)
        return getattr(self, normalized.value)

    def role_precision(
        self, role: TemporalRole | str
    ) -> legacy.TemporalPrecision:
        normalized = _normalize_role(role)
        return getattr(self, f"{normalized.value}_precision")

    def role_lower_bound(
        self, role: TemporalRole | str
    ) -> datetime | str | None:
        normalized = _normalize_role(role)
        return getattr(self, f"{normalized.value}_lower_bound")

    def role_upper_bound(
        self, role: TemporalRole | str
    ) -> datetime | str | None:
        normalized = _normalize_role(role)
        return getattr(self, f"{normalized.value}_upper_bound")

    def role_best_time(self, role: TemporalRole | str) -> datetime | None:
        normalized = _normalize_role(role)
        if self.role_precision(normalized) is legacy.TemporalPrecision.UNKNOWN:
            return None
        value = self.role_value(normalized)
        assert value is not None
        return legacy._as_aware_datetime(value, normalized.value)

    def role_interval(
        self, role: TemporalRole | str
    ) -> tuple[datetime, datetime] | None:
        normalized = _normalize_role(role)
        self.validate_shape()
        precision = self.role_precision(normalized)
        if precision is legacy.TemporalPrecision.UNKNOWN:
            return None
        if precision is legacy.TemporalPrecision.BOUNDED:
            lower = self.role_lower_bound(normalized)
            upper = self.role_upper_bound(normalized)
            assert lower is not None and upper is not None
            return (
                legacy._as_aware_datetime(
                    lower, f"{normalized.value}_lower_bound"
                ),
                legacy._as_aware_datetime(
                    upper, f"{normalized.value}_upper_bound"
                ),
            )
        if precision is legacy.TemporalPrecision.EXACT:
            best = self.role_best_time(normalized)
            assert best is not None
            return best, best
        return None

    @property
    def best_time(self) -> datetime | None:
        """Best event time retained for compatibility with anchor checks."""

        return self.role_best_time(TemporalRole.EVENT_TIME)

    @property
    def freshness_time(self) -> datetime | None:
        """Substantive represented-state freshness.

        Known state time is authoritative. Event time is the fallback. Database
        persistence time and retrieval time never refresh represented state.
        """

        for role in (TemporalRole.STATE_TIME, TemporalRole.EVENT_TIME):
            best = self.role_best_time(role)
            if best is not None:
                return best
        return None

    @property
    def persistence_time(self) -> datetime | None:
        """Database persistence time, kept separate from substantive freshness."""

        return self.role_best_time(TemporalRole.RECORD_TIME)

    def interval(self) -> tuple[datetime, datetime] | None:
        """Event-time interval retained for compatibility."""

        return self.role_interval(TemporalRole.EVENT_TIME)


def adapt_memory_state_time(
    value: datetime | str | None,
    precision: legacy.TemporalPrecision | str,
    *,
    lower_bound: datetime | str | None = None,
    upper_bound: datetime | str | None = None,
    temporal_claim: bool | None,
) -> tuple[
    datetime | str | None,
    legacy.TemporalPrecision,
    datetime | str | None,
    datetime | str | None,
]:
    """Normalize Memory's UNKNOWN state-time storage sentinel.

    ``-infinity`` is a storage compatibility marker, not a timestamp. It is
    converted to ``None`` only when accompanied by UNKNOWN precision,
    ``temporal_claim=False``, and no bounds. Any mismatch fails with a named
    error rather than silently treating the sentinel as temporal evidence.
    """

    try:
        normalized_precision = (
            precision
            if isinstance(precision, legacy.TemporalPrecision)
            else legacy.TemporalPrecision(precision)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("MEMORY_STATE_TIME_PRECISION_INVALID") from exc

    is_sentinel = (
        isinstance(value, str)
        and value.strip().lower() == MEMORY_UNKNOWN_STATE_TIME_SENTINEL
    )

    if is_sentinel:
        if normalized_precision is not legacy.TemporalPrecision.UNKNOWN:
            raise ValueError("MEMORY_UNKNOWN_STATE_SENTINEL_PRECISION_MISMATCH")
        if temporal_claim is not False:
            raise ValueError("MEMORY_UNKNOWN_STATE_SENTINEL_TEMPORAL_CLAIM_INVALID")
        if lower_bound is not None or upper_bound is not None:
            raise ValueError("MEMORY_UNKNOWN_STATE_SENTINEL_BOUNDS_FORBIDDEN")
        return None, legacy.TemporalPrecision.UNKNOWN, None, None

    if normalized_precision is legacy.TemporalPrecision.UNKNOWN:
        if value is not None or lower_bound is not None or upper_bound is not None:
            raise ValueError("MEMORY_UNKNOWN_STATE_TIME_VALUE_PRESENT")
        if temporal_claim is True:
            raise ValueError("MEMORY_UNKNOWN_STATE_TIME_TEMPORAL_CLAIM_INVALID")
        return None, legacy.TemporalPrecision.UNKNOWN, None, None

    if temporal_claim is False:
        raise ValueError("MEMORY_KNOWN_STATE_TIME_TEMPORAL_CLAIM_FALSE")
    if value is None:
        raise ValueError("MEMORY_KNOWN_STATE_TIME_MISSING")

    return value, normalized_precision, lower_bound, upper_bound


def role_temporal_point_subject_hash(point: RoleTemporalPoint) -> str:
    """Bind evidence to all values, precisions, bounds, scope, and provenance."""

    point.validate_shape()
    payload: dict[str, Any] = {
        "scope_instance_id": point.scope_instance_id,
        "event_time": legacy._iso(point.event_time, "event_time"),
        "event_time_precision": point.event_time_precision,
        "event_time_lower_bound": legacy._iso(
            point.event_time_lower_bound, "event_time_lower_bound"
        ),
        "event_time_upper_bound": legacy._iso(
            point.event_time_upper_bound, "event_time_upper_bound"
        ),
        "state_time": legacy._iso(point.state_time, "state_time"),
        "state_time_precision": point.state_time_precision,
        "state_time_lower_bound": legacy._iso(
            point.state_time_lower_bound, "state_time_lower_bound"
        ),
        "state_time_upper_bound": legacy._iso(
            point.state_time_upper_bound, "state_time_upper_bound"
        ),
        "record_time": legacy._iso(point.record_time, "record_time"),
        "record_time_precision": point.record_time_precision,
        "record_time_lower_bound": legacy._iso(
            point.record_time_lower_bound, "record_time_lower_bound"
        ),
        "record_time_upper_bound": legacy._iso(
            point.record_time_upper_bound, "record_time_upper_bound"
        ),
        "retrieval_time": legacy._iso(point.retrieval_time, "retrieval_time"),
        "retrieval_time_precision": point.retrieval_time_precision,
        "retrieval_time_lower_bound": legacy._iso(
            point.retrieval_time_lower_bound, "retrieval_time_lower_bound"
        ),
        "retrieval_time_upper_bound": legacy._iso(
            point.retrieval_time_upper_bound, "retrieval_time_upper_bound"
        ),
        "source_system": point.source.system,
        "source_operation": point.source.operation,
        "source_reference_id": point.source.reference_id,
    }
    return legacy.canonical_subject_hash("role_temporal_point", payload)


def run_preflight(
    request: legacy.PreflightRequest,
    verifier: legacy.EvidenceVerifier | None,
) -> legacy.PreflightDecision:
    """Run the base gate plus strict role-precision prior-anchor validation."""

    original_anchor = request.prior_anchor
    base_request = replace(
        request,
        prior_anchor=None,
        prior_anchor_required=False,
    )
    base_decision = legacy.run_preflight(base_request, verifier)
    reasons = list(base_decision.reasons)
    limitations = list(base_decision.limitations)

    if request.prior_anchor_required and original_anchor is None:
        reasons.append("PRIOR_ANCHOR_MISSING")

    if original_anchor is not None:
        point = original_anchor.point
        if not isinstance(point, RoleTemporalPoint):
            reasons.append("PRIOR_ANCHOR_ROLE_PRECISION_MISSING")
        else:
            try:
                original_anchor.validate_shape()
                subject_hash = role_temporal_point_subject_hash(point)
            except ValueError:
                reasons.append("PRIOR_ANCHOR_INVALID")
            else:
                if not legacy._verified_evidence(
                    verifier,
                    point.source,
                    allowed_systems=legacy.TEMPORAL_READ_SYSTEMS,
                    operation="temporal_read",
                    subject_hash=subject_hash,
                    require_immutable=request.immutable_proof_required,
                ):
                    reasons.append("PRIOR_ANCHOR_EVIDENCE_UNVERIFIED")
                if (
                    request.scope is not None
                    and original_anchor.scope_instance_id
                    != request.scope.scope_instance_id
                ):
                    reasons.append("PRIOR_ANCHOR_SCOPE_MISMATCH")

                trusted_now = base_decision.trusted_now
                if trusted_now is not None:
                    event_time = point.best_time
                    if event_time is not None and event_time > trusted_now:
                        reasons.append("PRIOR_ANCHOR_FROM_FUTURE")
                    freshness_time = point.freshness_time
                    if freshness_time is None:
                        reasons.append("PRIOR_ANCHOR_FRESHNESS_UNAVAILABLE")
                    elif trusted_now < freshness_time:
                        reasons.append("PRIOR_ANCHOR_STATE_FROM_FUTURE")
                    elif (
                        request.maximum_anchor_age >= timedelta(0)
                        and trusted_now - freshness_time
                        > request.maximum_anchor_age
                    ):
                        reasons.append("PRIOR_ANCHOR_STALE")

    status = (
        legacy.AnchorStatus.ANCHORED
        if not reasons
        else legacy.AnchorStatus.UNANCHORED
    )
    return legacy.PreflightDecision(
        status=status,
        reasons=tuple(dict.fromkeys(reasons)),
        trusted_now=base_decision.trusted_now,
        scope=base_decision.scope,
        addressed_events=base_decision.addressed_events,
        prior_anchor=original_anchor,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def elapsed_between(
    start: RoleTemporalPoint,
    end: RoleTemporalPoint,
    role: TemporalRole | str = TemporalRole.EVENT_TIME,
) -> legacy.ElapsedResult:
    """Calculate elapsed time for one explicit temporal role."""

    try:
        normalized_role = _normalize_role(role)
        start.validate_shape()
        end.validate_shape()
    except (TypeError, ValueError) as exc:
        return legacy.ElapsedResult(
            legacy.ElapsedStatus.CONFLICTED,
            None,
            None,
            None,
            (str(exc),),
        )

    if start.scope_instance_id != end.scope_instance_id:
        return legacy.ElapsedResult(
            legacy.ElapsedStatus.CONFLICTED,
            None,
            None,
            None,
            ("Elapsed endpoints belong to different scope instances.",),
        )

    start_precision = start.role_precision(normalized_role)
    end_precision = end.role_precision(normalized_role)
    if (
        start_precision is legacy.TemporalPrecision.UNKNOWN
        or end_precision is legacy.TemporalPrecision.UNKNOWN
    ):
        return legacy.ElapsedResult(
            legacy.ElapsedStatus.UNAVAILABLE,
            None,
            None,
            None,
            (
                f"At least one endpoint has UNKNOWN "
                f"{normalized_role.value} precision.",
            ),
        )

    start_best = start.role_best_time(normalized_role)
    end_best = end.role_best_time(normalized_role)
    assert start_best is not None and end_best is not None
    representative_best = (end_best - start_best).total_seconds()

    if legacy.TemporalPrecision.APPROXIMATE in (
        start_precision,
        end_precision,
    ):
        if representative_best < 0:
            return legacy.ElapsedResult(
                legacy.ElapsedStatus.CONFLICTED,
                None,
                None,
                None,
                (
                    f"Best-supported end {normalized_role.value} "
                    f"precedes start {normalized_role.value}.",
                ),
            )
        return legacy.ElapsedResult(
            legacy.ElapsedStatus.APPROXIMATE,
            representative_best,
            None,
            None,
        )

    start_interval = start.role_interval(normalized_role)
    end_interval = end.role_interval(normalized_role)
    assert start_interval is not None and end_interval is not None
    raw_lower = (end_interval[0] - start_interval[1]).total_seconds()
    upper = (end_interval[1] - start_interval[0]).total_seconds()
    if upper < 0:
        return legacy.ElapsedResult(
            legacy.ElapsedStatus.CONFLICTED,
            None,
            None,
            None,
            (
                f"The supported end {normalized_role.value} interval is fully "
                f"earlier than the start interval.",
            ),
        )

    if (
        start_precision is legacy.TemporalPrecision.EXACT
        and end_precision is legacy.TemporalPrecision.EXACT
    ):
        return legacy.ElapsedResult(
            legacy.ElapsedStatus.EXACT,
            representative_best,
            representative_best,
            representative_best,
        )

    lower = max(0.0, raw_lower)
    supported_best = min(max(representative_best, lower), upper)
    return legacy.ElapsedResult(
        legacy.ElapsedStatus.BOUNDED,
        supported_best,
        lower,
        upper,
    )


run_postflight = legacy.run_postflight
