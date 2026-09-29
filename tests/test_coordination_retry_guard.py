from __future__ import annotations

import importlib
import threading

import pytest

from coordination_bus import (
    ALL_PERMISSIONS,
    ActorContext,
    CoordinationBus,
    CoordinationEventDraft,
    InMemoryCoordinationRepository,
    PERMISSION_POST,
)


def _api():
    try:
        module = importlib.import_module("coordination_bus.retry_guard")
    except ModuleNotFoundError:
        pytest.fail("coordination retry guard behavior is not implemented")
    return module


def _draft(*, target: str = "workstream/time") -> CoordinationEventDraft:
    return CoordinationEventDraft(
        thread_key="retry-guard-v1",
        source_branch="workstream/memory",
        target_branch=target,
        event_type="STATUS",
        status="IN_PROGRESS",
        objective="Exercise retry-safe coordination writes",
        summary="Same logical status payload.",
        payload={"value": 1},
        reference_data={"source": "test"},
    )


def test_exact_immediate_retry_is_suppressed_without_second_write():
    api = _api()
    repo = InMemoryCoordinationRepository()
    bus = CoordinationBus(repo)
    actor = ActorContext("workstream/memory", ALL_PERMISSIONS)
    guard = api.CoordinationRetryGuard(window_ms=500)
    draft = _draft()

    first = api.guarded_coordination_post(
        bus, guard, actor, draft, now_ms=1_000
    )
    second = api.guarded_coordination_post(
        bus, guard, actor, draft, now_ms=1_200
    )

    assert first.state is api.RetryGuardState.WRITTEN
    assert first.coordination_result is not None
    assert first.coordination_result.receipt.database_write_confirmed
    assert second.state is api.RetryGuardState.DUPLICATE_SUPPRESSED
    assert second.coordination_result is None
    assert len(repo.list_thread("retry-guard-v1")) == 1


def test_retry_key_binds_route_so_different_target_is_not_suppressed():
    api = _api()
    repo = InMemoryCoordinationRepository()
    bus = CoordinationBus(repo)
    actor = ActorContext("workstream/memory", ALL_PERMISSIONS)
    guard = api.CoordinationRetryGuard(window_ms=500)

    first = api.guarded_coordination_post(
        bus, guard, actor, _draft(target="workstream/time"), now_ms=2_000
    )
    second = api.guarded_coordination_post(
        bus,
        guard,
        actor,
        _draft(target="workstream/integration"),
        now_ms=2_100,
    )

    assert first.state is api.RetryGuardState.WRITTEN
    assert second.state is api.RetryGuardState.WRITTEN
    assert first.idempotency_key != second.idempotency_key
    assert len(repo.list_thread("retry-guard-v1")) == 2


def test_same_exact_draft_is_admitted_again_after_window():
    api = _api()
    repo = InMemoryCoordinationRepository()
    bus = CoordinationBus(repo)
    actor = ActorContext("workstream/memory", ALL_PERMISSIONS)
    guard = api.CoordinationRetryGuard(window_ms=500)
    draft = _draft()

    first = api.guarded_coordination_post(
        bus, guard, actor, draft, now_ms=3_000
    )
    later = api.guarded_coordination_post(
        bus, guard, actor, draft, now_ms=3_501
    )

    assert first.state is api.RetryGuardState.WRITTEN
    assert later.state is api.RetryGuardState.WRITTEN
    assert len(repo.list_thread("retry-guard-v1")) == 2


def test_failed_write_rolls_back_reservation_for_authorized_retry():
    api = _api()
    repo = InMemoryCoordinationRepository()
    bus = CoordinationBus(repo)
    denied = ActorContext("workstream/memory", frozenset())
    authorized = ActorContext(
        "workstream/memory", frozenset({PERMISSION_POST})
    )
    guard = api.CoordinationRetryGuard(window_ms=500)
    draft = _draft()

    failed = api.guarded_coordination_post(
        bus, guard, denied, draft, now_ms=4_000
    )
    retry = api.guarded_coordination_post(
        bus, guard, authorized, draft, now_ms=4_100
    )

    assert failed.state is api.RetryGuardState.FAILED
    assert failed.reservation_rolled_back is True
    assert failed.coordination_result is not None
    assert failed.coordination_result.receipt.result_class == "DENIED"
    assert retry.state is api.RetryGuardState.WRITTEN
    assert len(repo.list_thread("retry-guard-v1")) == 1


def test_retry_guard_rejects_clock_regression():
    api = _api()
    guard = api.CoordinationRetryGuard(window_ms=500)
    assert guard.accept("a" * 64, 5_000) is True

    with pytest.raises(ValueError, match="RETRY_GUARD_CLOCK_REGRESSION"):
        guard.accept("b" * 64, 4_999)


def test_retry_guard_concurrent_exact_reservation_has_one_winner():
    api = _api()
    guard = api.CoordinationRetryGuard(window_ms=500)
    results: list[bool] = []
    barrier = threading.Barrier(3)

    def worker():
        barrier.wait()
        results.append(guard.accept("c" * 64, 6_000))

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    second.start()
    barrier.wait()
    first.join(5)
    second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(results) == [False, True]


def test_retry_key_changes_when_actor_changes_even_for_same_draft():
    api = _api()
    memory = ActorContext("workstream/memory", ALL_PERMISSIONS)
    # Build an equivalent draft for a different legitimate actor/source.
    time_draft = CoordinationEventDraft(
        thread_key="retry-guard-v1",
        source_branch="workstream/time",
        target_branch="workstream/memory",
        event_type="STATUS",
        status="IN_PROGRESS",
        objective="Exercise retry-safe coordination writes",
        summary="Same logical status payload.",
        payload={"value": 1},
        reference_data={"source": "test"},
    )
    time_actor = ActorContext("workstream/time", ALL_PERMISSIONS)

    memory_key = api.coordination_retry_key(memory, _draft())
    time_key = api.coordination_retry_key(time_actor, time_draft)

    assert memory_key != time_key