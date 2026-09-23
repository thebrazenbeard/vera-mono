"""Conservative event-time mapping and fail-closed ordering."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class SyncStatus(str, Enum):
    SYNCHRONIZED = "SYNCHRONIZED"
    HOLDOVER = "HOLDOVER"
    UNSYNCHRONIZED = "UNSYNCHRONIZED"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class EventOrder(str, Enum):
    A_BEFORE_B = "A_BEFORE_B"
    B_BEFORE_A = "B_BEFORE_A"
    ORDER_UNRESOLVED = "ORDER_UNRESOLVED"


class TimingMappingUnavailable(ValueError):
    """Raised when a source clock cannot be mapped to reference time."""


@dataclass(frozen=True)
class TimeInterval:
    earliest: Decimal
    latest: Decimal

    def __post_init__(self) -> None:
        if self.earliest > self.latest:
            raise ValueError("earliest must not exceed latest")

    @property
    def half_width(self) -> Decimal:
        return (self.latest - self.earliest) / Decimal(2)


@dataclass(frozen=True)
class TimingQuality:
    status: SyncStatus
    offset_bound: Decimal
    jitter_bound: Decimal
    capture_path_uncertainty_bound: Decimal
    resolution: Decimal
    drift_bound_per_second: Decimal

    def __post_init__(self) -> None:
        bounds = (
            self.offset_bound,
            self.jitter_bound,
            self.capture_path_uncertainty_bound,
            self.resolution,
            self.drift_bound_per_second,
        )
        if any(bound < 0 for bound in bounds):
            raise ValueError("timing bounds must be non-negative")

    def uncertainty(self, elapsed_since_last_sync: Decimal) -> Decimal:
        if elapsed_since_last_sync < 0:
            raise ValueError("elapsed_since_last_sync must be non-negative")
        return (
            self.offset_bound
            + self.jitter_bound
            + self.capture_path_uncertainty_bound
            + self.resolution / Decimal(2)
            + self.drift_bound_per_second * elapsed_since_last_sync
        )

    def cross_clock_analysis_allowed(
        self,
        *,
        elapsed_since_last_sync: Decimal,
        tolerance: Decimal,
    ) -> bool:
        if tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        if self.status not in {SyncStatus.SYNCHRONIZED, SyncStatus.HOLDOVER}:
            return False
        return self.uncertainty(elapsed_since_last_sync) <= tolerance


def map_event(
    *,
    estimated_time: Decimal,
    quality: TimingQuality,
    elapsed_since_last_sync: Decimal,
) -> TimeInterval:
    if quality.status not in {SyncStatus.SYNCHRONIZED, SyncStatus.HOLDOVER}:
        raise TimingMappingUnavailable(quality.status.value)
    half_width = quality.uncertainty(elapsed_since_last_sync)
    return TimeInterval(estimated_time - half_width, estimated_time + half_width)


def definite_order(a: TimeInterval, b: TimeInterval) -> EventOrder:
    if a.latest < b.earliest:
        return EventOrder.A_BEFORE_B
    if b.latest < a.earliest:
        return EventOrder.B_BEFORE_A
    return EventOrder.ORDER_UNRESOLVED

