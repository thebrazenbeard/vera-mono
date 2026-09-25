from pathlib import Path

import pytest

from vera_core.durable_dispatch_gate import DurableDispatchGate, DispatchFenceError


def test_dispatch_budget_and_fence_survive_restart(tmp_path: Path):
    path = tmp_path / "dispatch.sqlite3"
    gate = DurableDispatchGate(
        path,
        lineage_id="lineage-1",
        remaining_active=2,
        remaining_retries=1,
        remaining_backend_jobs=2,
    )

    first = gate.claim(
        work_id="work-1",
        holder="worker-a",
        now=0.0,
        ttl=10.0,
        expected_generation=0,
        retry=False,
    )
    assert first.fencing_token == 1
    assert first.budget_generation == 1

    restarted = DurableDispatchGate.open(path, lineage_id="lineage-1")

    with pytest.raises(DispatchFenceError, match="active lease"):
        restarted.claim(
            work_id="work-1",
            holder="worker-b",
            now=5.0,
            ttl=10.0,
            expected_generation=1,
            retry=True,
        )

    second = restarted.claim(
        work_id="work-1",
        holder="worker-b",
        now=11.0,
        ttl=10.0,
        expected_generation=1,
        retry=True,
    )
    assert second.fencing_token == 2
    assert second.budget_generation == 2
    assert second.remaining_retries == 0

    assert restarted.complete(first, now=12.0) is False
    assert restarted.complete(second, now=12.0) is True
