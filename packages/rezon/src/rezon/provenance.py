from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json

from .nodes import ExecutionResult


def canonical_episode_snapshot_digest(snapshot) -> str:
    payload = json.dumps(
        asdict(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def canonical_output_digest(result: ExecutionResult) -> str | None:
    if not result.emitted_propositions and not result.emitted_relations:
        return None

    payload = {
        "emitted_propositions": [
            asdict(replace(proposition, producer_execution_id=None))
            for proposition in result.emitted_propositions
        ],
        "emitted_relations": [
            asdict(replace(relation, producer_execution_id=None))
            for relation in result.emitted_relations
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def canonical_producer_execution_id(
    node_id: str,
    episode_snapshot_digest: str,
    task_specification_digest: str | None,
    output_digest: str,
) -> str:
    payload = "\x1f".join((
        node_id,
        episode_snapshot_digest,
        task_specification_digest or "no-task-spec",
        output_digest,
    ))
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return f"canonical:exec:{node_id}:{digest}"
