from pathlib import Path

import pytest

from vera_core.work_checkpoint import (
    RecoveryCheckpoint,
    RecoveryCheckpointStore,
    StaleCheckpointGeneration,
)


def test_recovery_checkpoint_preserves_fact_inference_and_cas(tmp_path: Path):
    path = tmp_path / "checkpoint.sqlite3"
    store = RecoveryCheckpointStore(path, workspace_id="vera-wave3")

    first = store.append(
        RecoveryCheckpoint(
            objective="Continue bounded portfolio ingestion.",
            observed=("main@abc was read back",),
            inferred=("WIP checkpoint semantics are useful",),
            completed=("Discovery gate implemented",),
            unfinished=("Project Runner validation remains",),
            next_action="Run the combined verification gate.",
            do_not_repeat=("Do not recreate the already-landed Discovery adapter.",),
        ),
        expected_generation=0,
    )
    assert first.generation == 1
    assert first.checkpoint_id == "cp-000001"
    assert first.authorization_effect == "NONE"

    with pytest.raises(StaleCheckpointGeneration):
        store.append(
            RecoveryCheckpoint(
                objective="stale writer",
                observed=(),
                inferred=(),
                completed=(),
                unfinished=(),
                next_action="refresh",
                do_not_repeat=(),
            ),
            expected_generation=0,
        )

    restarted = RecoveryCheckpointStore(path, workspace_id="vera-wave3")
    head = restarted.head()
    assert head.generation == 1
    assert head.checkpoint.observed == ("main@abc was read back",)
    assert head.checkpoint.inferred == ("WIP checkpoint semantics are useful",)
    assert head.checkpoint.do_not_repeat == (
        "Do not recreate the already-landed Discovery adapter.",
    )
