from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .episode import EpisodeSnapshot
from .epistemics import PropositionKind
from .nodes import NodeDescriptor, node_descriptor_contract_is_exact
from .receipts import FailureState


class ScheduleAction(str, Enum):
    EXECUTE = "execute"
    TERMINATE = "terminate"


@dataclass(frozen=True)
class Budget:
    limit: int
    used: int = 0

    def __post_init__(self) -> None:
        if self.limit < 0 or self.used < 0:
            raise ValueError("budget values cannot be negative")


@dataclass(frozen=True)
class ScheduleDecision:
    action: ScheduleAction
    node_id: str | None = None
    reason: str = ""
    target_id: str | None = None
    failure: FailureState | None = None
    node_index: int | None = None


class DeterministicScheduler:
    def next(
        self,
        snapshot: EpisodeSnapshot,
        nodes: tuple[NodeDescriptor, ...],
        completed_node_ids: tuple[str, ...],
        budget: Budget,
    ) -> ScheduleDecision:
        if (
            type(nodes) is not tuple
            or any(not node_descriptor_contract_is_exact(node) for node in nodes)
        ):
            return ScheduleDecision(
                ScheduleAction.TERMINATE,
                reason="invalid_node_descriptor_contract",
                failure=FailureState.CONTRACT_VIOLATION,
            )

        completed = set(completed_node_ids)
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            return ScheduleDecision(
                ScheduleAction.TERMINATE,
                reason="duplicate_node_id",
                failure=FailureState.CONTRACT_VIOLATION,
            )
        by_id = {node.node_id: (index, node) for index, node in enumerate(nodes)}

        def schedule(
            node_index: int,
            reason: str,
            target_id: str | None = None,
        ) -> ScheduleDecision:
            node = nodes[node_index]
            if budget.used >= budget.limit:
                return ScheduleDecision(
                    ScheduleAction.TERMINATE,
                    reason="budget_exhausted",
                    target_id=target_id,
                    failure=FailureState.RESOURCE_LIMIT,
                )
            return ScheduleDecision(
                ScheduleAction.EXECUTE,
                node.node_id,
                reason,
                target_id,
                node_index=node_index,
            )

        for index, node in enumerate(nodes):
            if node.mandatory_verification and node.node_id not in completed:
                return schedule(index, "mandatory_verification")

        if "contradiction_scanner" in by_id and "contradiction_scanner" not in completed:
            contradiction_index, _contradiction_node = by_id["contradiction_scanner"]
            contradiction = next(
                (
                    relation
                    for relation in snapshot.current_relations
                    if relation.relation_type.lower() == "contradicts"
                ),
                None,
            )
            if contradiction is not None:
                return schedule(
                    contradiction_index,
                    "explicit_contradiction",
                    contradiction.relation_id,
                )

        generator_entry = by_id.get("echo_hypothesis")
        hypotheses = [p for p in snapshot.current_propositions if p.kind is PropositionKind.HYPOTHESIS]
        if generator_entry:
            generator_index, generator = generator_entry
            if generator.node_id not in completed:
                if generator.independence_required or not hypotheses:
                    reason = (
                        "independent_hypothesis_generation"
                        if generator.independence_required
                        else "missing_hypothesis"
                    )
                    return schedule(generator_index, reason)

        falsifier_entry = by_id.get("falsifier")
        if falsifier_entry:
            falsifier_index, falsifier = falsifier_entry
            if falsifier.node_id not in completed:
                target = next(
                    (p for p in hypotheses if (p.confidence or 0.0) >= 0.8),
                    None,
                )
                if target is not None:
                    return schedule(
                        falsifier_index,
                        "falsify_high_confidence_hypothesis",
                        target.proposition_id,
                    )

        return ScheduleDecision(ScheduleAction.TERMINATE, reason="no_applicable_rule")
