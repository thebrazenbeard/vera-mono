from __future__ import annotations

from dataclasses import dataclass

from .receipts import FailureState


@dataclass(frozen=True)
class TraceRecord:
    execution_id: str
    node_id: str
    episode_version: str
    visible_proposition_ids: tuple[str, ...]
    blinded_proposition_ids: tuple[str, ...]
    visible_relation_ids: tuple[str, ...]
    blinded_relation_ids: tuple[str, ...]
    emitted_proposition_ids: tuple[str, ...]
    independence_demonstrated: bool
    task_envelope_digest: str | None = None
    executor_task_specification_digest: str | None = None
    executor_episode_version: str | None = None
    canonical_producer_execution_id: str | None = None
    canonical_episode_snapshot_digest: str | None = None
    canonical_output_digest: str | None = None
    source_refs: tuple[str, ...] = ()
    source_versions: tuple[str, ...] = ()
    reported_source_refs: tuple[str, ...] = ()
    reported_source_versions: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    failures: tuple[FailureState, ...] = ()


@dataclass(frozen=True)
class ExecutionTrace:
    records: tuple[TraceRecord, ...] = ()
