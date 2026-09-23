from __future__ import annotations

from dataclasses import dataclass

from .envelopes import TaskEnvelope
from .episode import EpisodeSnapshot
from .epistemics import PropositionKind
from .nodes import ExecutionView
from .receipts import IndependenceMetadata


@dataclass(frozen=True)
class VisibilityPolicy:
    allow_kinds: tuple[PropositionKind, ...] = ()
    allow_ids: tuple[str, ...] = ()
    blind_kinds: tuple[PropositionKind, ...] = ()
    blind_ids: tuple[str, ...] = ()


def visibility_policy_contract_is_exact(policy) -> bool:
    if type(policy) is not VisibilityPolicy:
        return False
    for kinds in (policy.allow_kinds, policy.blind_kinds):
        if (
            type(kinds) is not tuple
            or any(type(kind) is not PropositionKind for kind in kinds)
        ):
            return False
    for ids in (policy.allow_ids, policy.blind_ids):
        if type(ids) is not tuple or any(type(value) is not str for value in ids):
            return False
    return True


def build_execution_view(
    execution_id: str,
    snapshot: EpisodeSnapshot,
    policy: VisibilityPolicy,
    independence: IndependenceMetadata | None = None,
    task_envelope: TaskEnvelope | None = None,
) -> ExecutionView:
    visible = []
    blinded = []
    allow_ids = set(policy.allow_ids)
    blind_ids = set(policy.blind_ids)
    allow_kinds = set(policy.allow_kinds)
    blind_kinds = set(policy.blind_kinds)
    for proposition in snapshot.current_propositions:
        allowed = (
            (not allow_ids and not allow_kinds)
            or proposition.proposition_id in allow_ids
            or proposition.kind in allow_kinds
        )
        blocked = proposition.proposition_id in blind_ids or proposition.kind in blind_kinds
        if allowed and not blocked:
            visible.append(proposition)
        else:
            blinded.append(proposition.proposition_id)

    visible_ids = {p.proposition_id for p in visible}
    visible_relations = []
    blinded_relations = []
    for relation in snapshot.current_relations:
        refs = {participant.ref_id for participant in relation.participants}
        dependencies_visible = refs.issubset(
            visible_ids | {r.relation_id for r in visible_relations}
        )
        id_allowed = not allow_ids or relation.relation_id in allow_ids
        id_blocked = relation.relation_id in blind_ids
        if dependencies_visible and id_allowed and not id_blocked:
            visible_relations.append(relation)
        else:
            blinded_relations.append(relation.relation_id)

    return ExecutionView(
        execution_id=execution_id,
        episode_version=snapshot.version_ref,
        propositions=tuple(visible),
        relations=tuple(visible_relations),
        blinded_proposition_ids=tuple(blinded),
        blinded_relation_ids=tuple(blinded_relations),
        independence=independence or IndependenceMetadata(),
        task_envelope=task_envelope,
        task_specification=(
            task_envelope.to_task_specification()
            if task_envelope is not None
            else None
        ),
    )
