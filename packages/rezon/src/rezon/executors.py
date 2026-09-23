from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .epistemics import Proposition, PropositionKind
from .nodes import ExecutionResult, ExecutionView


class Executor(Protocol):
    node_id: str

    def execute(self, view: ExecutionView, episode_id: str) -> ExecutionResult: ...


@dataclass(frozen=True)
class EchoHypothesisExecutor:
    node_id: str = "echo_hypothesis"

    def execute(self, view: ExecutionView, episode_id: str) -> ExecutionResult:
        observations = [p for p in view.propositions if p.kind in (PropositionKind.OBSERVATION, PropositionKind.EVIDENCE)]
        if not observations:
            return ExecutionResult(view.execution_id, self.node_id)
        source = observations[0]
        hypothesis = Proposition(
            proposition_id=f"{view.execution_id}:hypothesis:1",
            episode_id=episode_id,
            kind=PropositionKind.HYPOTHESIS,
            content=f"Hypothesis derived from: {source.content}",
            source_refs=(source.proposition_id,),
            producer_execution_id=view.execution_id,
        )
        return ExecutionResult(view.execution_id, self.node_id, (hypothesis,))


@dataclass(frozen=True)
class ContradictionScannerExecutor:
    node_id: str = "contradiction_scanner"

    def execute(self, view: ExecutionView, episode_id: str) -> ExecutionResult:
        contradiction = next((r for r in view.relations if r.relation_type.lower() == "contradicts"), None)
        if contradiction is None:
            return ExecutionResult(view.execution_id, self.node_id)
        result = Proposition(
            proposition_id=f"{view.execution_id}:test_result:1",
            episode_id=episode_id,
            kind=PropositionKind.TEST_RESULT,
            content=f"Explicit contradiction observed in {contradiction.relation_id}",
            source_refs=(contradiction.relation_id,),
            producer_execution_id=view.execution_id,
        )
        return ExecutionResult(view.execution_id, self.node_id, (result,))


@dataclass(frozen=True)
class FalsifierExecutor:
    target_hypothesis_id: str
    node_id: str = "falsifier"

    def execute(self, view: ExecutionView, episode_id: str) -> ExecutionResult:
        by_id = {p.proposition_id: p for p in view.propositions}
        target = by_id.get(self.target_hypothesis_id)
        if target is None or target.kind is not PropositionKind.HYPOTHESIS:
            return ExecutionResult(view.execution_id, self.node_id)
        for relation in view.relations:
            if relation.relation_type.lower() != "contradicts":
                continue
            refs = [participant.ref_id for participant in relation.participants]
            if self.target_hypothesis_id not in refs:
                continue
            contradictory_results = [
                by_id[ref] for ref in refs
                if ref != self.target_hypothesis_id
                and ref in by_id
                and by_id[ref].kind is PropositionKind.TEST_RESULT
            ]
            if not contradictory_results:
                continue
            source = contradictory_results[0]
            refutation = Proposition(
                proposition_id=f"{view.execution_id}:refutation:1",
                episode_id=episode_id,
                kind=PropositionKind.CLAIM,
                content=f"Refuted hypothesis {self.target_hypothesis_id}",
                source_refs=(source.proposition_id, relation.relation_id),
                producer_execution_id=view.execution_id,
            )
            return ExecutionResult(view.execution_id, self.node_id, (refutation,))
        return ExecutionResult(view.execution_id, self.node_id)
