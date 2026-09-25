from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
import threading

from .contracts import (
    ActorContext,
    CoordinationEventDraft,
    CoordinationResult,
    canonical_hash,
)
from .core import CoordinationBus


class RetryGuardState(StrEnum):
    WRITTEN = "WRITTEN"
    DUPLICATE_SUPPRESSED = "DUPLICATE_SUPPRESSED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class GuardedCoordinationPostResult:
    state: RetryGuardState
    idempotency_key: str
    coordination_result: CoordinationResult | None
    reservation_rolled_back: bool = False


def coordination_retry_key(
    actor: ActorContext,
    draft: CoordinationEventDraft,
) -> str:
    """Bind retry identity to the exact actor and complete coordination draft."""
    if not isinstance(actor, ActorContext):
        raise TypeError("actor must be ActorContext")
    if not isinstance(draft, CoordinationEventDraft):
        raise TypeError("draft must be CoordinationEventDraft")
    actor.validate()
    draft.validate()
    if draft.source_branch != actor.canonical_workstream:
        raise ValueError("draft source_branch must equal actor workstream")
    return canonical_hash(
        {
            "schema": "VERA_COORDINATION_RETRY_KEY_V1",
            "operation": "coordination_post",
            "actor_workstream": actor.canonical_workstream,
            "draft": draft.canonical_dict(),
        }
    )


class CoordinationRetryGuard:
    """Thread-safe, process-local short-window retry suppression.

    This does not provide durable or exactly-once delivery. The lock is held
    across reservation and the guarded downstream write so a concurrent retry
    cannot observe an uncommitted reservation.
    """

    def __init__(self, *, window_ms: int = 500) -> None:
        if type(window_ms) is not int or window_ms < 0:
            raise ValueError("window_ms must be a non-negative integer")
        self.window_ms = window_ms
        self._seen: OrderedDict[str, int] = OrderedDict()
        self._last_now_ms: int | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _validate_key(idempotency_key: str) -> None:
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError("INVALID_RETRY_GUARD_KEY")

    @staticmethod
    def _validate_time(now_ms: int) -> None:
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("INVALID_RETRY_GUARD_TIME")

    def accept(self, idempotency_key: str, now_ms: int) -> bool:
        self._validate_key(idempotency_key)
        self._validate_time(now_ms)
        with self._lock:
            if self._last_now_ms is not None and now_ms < self._last_now_ms:
                raise ValueError("RETRY_GUARD_CLOCK_REGRESSION")
            self._last_now_ms = now_ms

            previous = self._seen.get(idempotency_key)
            if previous is not None and now_ms - previous <= self.window_ms:
                return False

            self._seen[idempotency_key] = now_ms
            self._seen.move_to_end(idempotency_key)
            cutoff = now_ms - self.window_ms
            while self._seen:
                oldest_key, oldest_seen = next(iter(self._seen.items()))
                if oldest_seen >= cutoff:
                    break
                if oldest_key == idempotency_key:
                    break
                self._seen.popitem(last=False)
            return True

    def rollback_accept(
        self,
        idempotency_key: str,
        accepted_at_ms: int,
    ) -> bool:
        self._validate_key(idempotency_key)
        self._validate_time(accepted_at_ms)
        with self._lock:
            if self._seen.get(idempotency_key) != accepted_at_ms:
                return False
            del self._seen[idempotency_key]
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)


def guarded_coordination_post(
    bus: CoordinationBus,
    guard: CoordinationRetryGuard,
    actor: ActorContext,
    draft: CoordinationEventDraft,
    *,
    now_ms: int,
) -> GuardedCoordinationPostResult:
    """Post once within the retry window, rolling back failed reservations."""
    if not isinstance(bus, CoordinationBus):
        raise TypeError("bus must be CoordinationBus")
    if not isinstance(guard, CoordinationRetryGuard):
        raise TypeError("guard must be CoordinationRetryGuard")

    key = coordination_retry_key(actor, draft)
    CoordinationRetryGuard._validate_time(now_ms)

    with guard._lock:
        if not guard.accept(key, now_ms):
            return GuardedCoordinationPostResult(
                state=RetryGuardState.DUPLICATE_SUPPRESSED,
                idempotency_key=key,
                coordination_result=None,
            )

        try:
            result = bus.coordination_post(actor, draft)
        except Exception:
            guard.rollback_accept(key, now_ms)
            raise

        if result.receipt.database_write_confirmed:
            return GuardedCoordinationPostResult(
                state=RetryGuardState.WRITTEN,
                idempotency_key=key,
                coordination_result=result,
            )

        rolled_back = guard.rollback_accept(key, now_ms)
        return GuardedCoordinationPostResult(
            state=RetryGuardState.FAILED,
            idempotency_key=key,
            coordination_result=result,
            reservation_rolled_back=rolled_back,
        )


__all__ = [
    "CoordinationRetryGuard",
    "GuardedCoordinationPostResult",
    "RetryGuardState",
    "coordination_retry_key",
    "guarded_coordination_post",
]