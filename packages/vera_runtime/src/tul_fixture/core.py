from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .types import (
    ApproximationEvidence,
    ElapsedResult,
    ElapsedStatus,
    TemporalEndpoint,
    TimeSemantics,
    TimestampSource,
)


@dataclass(frozen=True)
class CalculatorPolicy:
    exact_uncertainty_threshold_seconds: float = 0.001
    compatible_clock_domains: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def clocks_compatible(self, start_domain: str | None, end_domain: str | None) -> bool:
        if start_domain is None or end_domain is None:
            return False
        if start_domain == end_domain:
            return True
        return (start_domain, end_domain) in self.compatible_clock_domains


def validate_semantic_source(endpoint: TemporalEndpoint) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []

    if endpoint.timestamp is None:
        if endpoint.semantics is not TimeSemantics.UNKNOWN:
            reasons.append("null timestamp requires UNKNOWN semantics")
        if endpoint.source is not TimestampSource.UNAVAILABLE:
            reasons.append("null timestamp requires UNAVAILABLE source")
        return (not reasons, tuple(reasons))

    if endpoint.semantics is TimeSemantics.UNKNOWN:
        reasons.append("non-null timestamp cannot use UNKNOWN semantics")

    if endpoint.source is TimestampSource.UNAVAILABLE:
        reasons.append("non-null timestamp cannot use UNAVAILABLE source")

    if endpoint.semantics is TimeSemantics.MESSAGE_CREATION:
        if endpoint.source not in {
            TimestampSource.PLATFORM_MESSAGE_METADATA,
            TimestampSource.TRUSTED_BRIDGE,
        }:
            reasons.append("MESSAGE_CREATION requires PLATFORM_MESSAGE_METADATA or TRUSTED_BRIDGE")

    elif endpoint.semantics is TimeSemantics.GENERATION_INVOCATION_START:
        if endpoint.source is not TimestampSource.HOST_RUNTIME_CLOCK:
            reasons.append("GENERATION_INVOCATION_START requires HOST_RUNTIME_CLOCK")

    elif endpoint.semantics in {
        TimeSemantics.TURN_START,
        TimeSemantics.TURN_COMPLETION,
        TimeSemantics.INGESTION,
    }:
        reasons.append("telemetry/ingestion semantics are not valid TUL comparison endpoints")

    if endpoint.source is TimestampSource.CODEX_TURN_METADATA:
        reasons.append("CODEX_TURN_METADATA cannot establish message creation or generation invocation")

    return (not reasons, tuple(reasons))


def calculate_elapsed(
    start: TemporalEndpoint,
    end: TemporalEndpoint,
    *,
    policy: CalculatorPolicy | None = None,
    approximation: ApproximationEvidence | None = None,
) -> ElapsedResult:
    policy = policy or CalculatorPolicy()

    start_valid, start_reasons = validate_semantic_source(start)
    end_valid, end_reasons = validate_semantic_source(end)
    if not start_valid or not end_valid:
        return ElapsedResult(
            status=ElapsedStatus.CONFLICTED,
            reasons=tuple([*start_reasons, *end_reasons]),
        )

    if start.timestamp is None or end.timestamp is None:
        return ElapsedResult(
            status=ElapsedStatus.UNAVAILABLE,
            reasons=("one or both temporal endpoints are unavailable",),
        )

    clocks_compatible = policy.clocks_compatible(start.clock_domain, end.clock_domain)

    if clocks_compatible and start.uncertainty_seconds is not None and end.uncertainty_seconds is not None:
        start_u = start.uncertainty_seconds
        end_u = end.uncertainty_seconds
        s_min = start.timestamp - timedelta(seconds=start_u)
        s_max = start.timestamp + timedelta(seconds=start_u)
        e_min = end.timestamp - timedelta(seconds=end_u)
        e_max = end.timestamp + timedelta(seconds=end_u)

        if e_max < s_min:
            return ElapsedResult(
                status=ElapsedStatus.CONFLICTED,
                reasons=("end interval is demonstrably earlier than start interval",),
            )

        point_elapsed = (end.timestamp - start.timestamp).total_seconds()
        threshold = policy.exact_uncertainty_threshold_seconds
        if start_u <= threshold and end_u <= threshold and point_elapsed >= 0:
            return ElapsedResult(
                status=ElapsedStatus.EXACT,
                value_seconds=point_elapsed,
                reasons=(f"endpoint uncertainty accepted at threshold {threshold}s",),
            )

        upper = (e_max - s_min).total_seconds()
        if e_min <= s_max:
            return ElapsedResult(
                status=ElapsedStatus.BOUNDED,
                lower_bound_seconds=0.0,
                upper_bound_seconds=max(0.0, upper),
                reasons=("uncertainty intervals overlap",),
            )

        lower = (e_min - s_max).total_seconds()
        return ElapsedResult(
            status=ElapsedStatus.BOUNDED,
            lower_bound_seconds=max(0.0, lower),
            upper_bound_seconds=max(0.0, upper),
            reasons=("elapsed bounds derived from endpoint uncertainty intervals",),
        )

    if approximation is not None and approximation.is_documented():
        return ElapsedResult(
            status=ElapsedStatus.APPROXIMATE,
            value_seconds=approximation.estimated_elapsed_seconds,
            reasons=(
                f"documented approximation method: {approximation.method}",
                f"error model: {approximation.error_model}",
            ),
        )

    reasons: list[str] = []
    if not clocks_compatible:
        reasons.append("clock compatibility is unresolved")
    if start.uncertainty_seconds is None or end.uncertainty_seconds is None:
        reasons.append("endpoint uncertainty is incomplete")
    if approximation is not None and not approximation.is_documented():
        reasons.append("approximation evidence is undocumented or invalid")
    if not reasons:
        reasons.append("insufficient evidence for a supported elapsed status")

    return ElapsedResult(status=ElapsedStatus.UNAVAILABLE, reasons=tuple(reasons))
