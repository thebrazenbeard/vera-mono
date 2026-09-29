"""Research-only closed-loop AGI frontier composition."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vera_identity import SemanticAdmissionReceipt, SemanticKnowledgeStore
from vera_memory import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceReceipt,
    LearnedRevision,
    ReviewDisposition,
)

from .durable_dispatch_gate import DispatchAdmission, DurableDispatchGate
from .corrective_learning import (
    CorrectiveLearningLedger,
    CorrectionState,
    CorrectiveStage,
)


@dataclass(frozen=True, slots=True)
class ClosedLoopTask:
    task_id: str
    prompt: str
    semantic_object: dict[str, object]


@dataclass(frozen=True, slots=True)
class ClosedLoopResult:
    task_id: str
    semantic_receipt: SemanticAdmissionReceipt
    reasoned_action: str
    evidence_refs: tuple[str, ...]
    observation: dict[str, object]
    effect_state: str
    corrective_state: CorrectionState | None
    learned_influence: LearnedInfluenceReceipt | None = None
    dispatch_admission: DispatchAdmission | None = None
    dispatch_completed: bool | None = None
    authorization_effect: str = "NONE"


class ClosedLoopFrontier:
    """Compose semantics, reasoning, observation and correction without authority."""

    def __init__(self, state_dir: str | Path) -> None:
        root = Path(state_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.semantic = SemanticKnowledgeStore(root / "semantic.db")
        self.corrections = CorrectiveLearningLedger(root / "corrections.db")
        self.learned_influence = DurableLearnedInfluenceGate(
            root / "learned_influence.db"
        )

    def run(
        self,
        task: ClosedLoopTask,
        *,
        reason: Callable[
            [str, dict[str, object]], tuple[str, tuple[str, ...]]
        ],
        act: Callable[[str], dict[str, object]],
    ) -> ClosedLoopResult:
        if type(task) is not ClosedLoopTask:
            raise TypeError("task must be exact ClosedLoopTask")
        receipt = self.semantic.admit(task.semantic_object)
        action, evidence_refs = reason(task.prompt, task.semantic_object)
        if type(action) is not str or not action:
            raise ValueError("reasoned action must be a non-empty exact string")
        if type(evidence_refs) is not tuple or not evidence_refs:
            raise ValueError("reasoning must return non-empty evidence refs")
        observation = act(action)
        if type(observation) is not dict:
            raise TypeError("act must return an observation dict")
        correction = None
        if observation.get("success") is not True:
            event = self.corrections.start(
                correction_id=f"correction:{task.task_id}",
                failure_signature_id=self._failure_signature(action, observation),
                summary=f"Observed unsuccessful action {action!r}",
                evidence_refs=tuple(evidence_refs),
            )
            correction = self.corrections.state(event.correction_id)
        return ClosedLoopResult(
            task_id=task.task_id,
            semantic_receipt=receipt,
            reasoned_action=action,
            evidence_refs=tuple(evidence_refs),
            observation=dict(observation),
            effect_state="EFFECT_OBSERVED",
            corrective_state=correction,
        )

    @staticmethod
    def _failure_signature(
        action: str, observation: dict[str, object]
    ) -> str:
        explicit = observation.get("failure_signature_id")
        if explicit is not None:
            if type(explicit) is not str or not explicit:
                raise ValueError(
                    "failure_signature_id must be a non-empty exact string"
                )
            return explicit
        return f"action_failed:{action}"

    def review_learning(
        self,
        revision: LearnedRevision,
        *,
        disposition: ReviewDisposition,
        evidence_ref: str,
    ) -> None:
        self.learned_influence.review(
            association_id=revision.association_id,
            memory_revision_id=revision.memory_revision_id,
            disposition=disposition,
            evidence_ref=evidence_ref,
        )

    def run_with_learning(
        self,
        task: ClosedLoopTask,
        *,
        revision: LearnedRevision,
        cue_event_id: str,
        reason: Callable[
            [str, dict[str, object], LearnedRevision],
            tuple[str, tuple[str, ...]],
        ],
        act: Callable[[str], dict[str, object]],
    ) -> ClosedLoopResult:
        influence = self.learned_influence.consume(
            revision, cue_event_id=cue_event_id
        )
        receipt = self.semantic.admit(task.semantic_object)
        action, evidence_refs = reason(
            task.prompt, task.semantic_object, revision
        )
        observation = act(action)
        correction = None
        correction_id = f"correction:{task.task_id}"
        try:
            correction = self.corrections.state(correction_id)
        except KeyError:
            pass
        if observation.get("success") is not True:
            if correction is None:
                event = self.corrections.start(
                    correction_id=correction_id,
                    failure_signature_id=self._failure_signature(action, observation),
                    summary=f"Observed unsuccessful action {action!r}",
                    evidence_refs=tuple(evidence_refs),
                )
                correction = self.corrections.state(event.correction_id)
        return ClosedLoopResult(
            task_id=task.task_id,
            semantic_receipt=receipt,
            reasoned_action=action,
            evidence_refs=tuple(evidence_refs),
            observation=dict(observation),
            effect_state="EFFECT_OBSERVED",
            corrective_state=correction,
            learned_influence=influence,
        )

    def run_bounded(
        self,
        task: ClosedLoopTask,
        *,
        cascade,
        dispatch_gate: DurableDispatchGate,
        holder: str,
        now: float,
        ttl: float,
        expected_generation: int,
        act: Callable[[str], dict[str, object]],
    ) -> ClosedLoopResult:
        receipt = self.semantic.admit(task.semantic_object)
        reasoning = cascade.resolve(task.prompt)
        if not reasoning.resolved or reasoning.answer is None:
            raise ValueError("reasoning did not resolve a bounded action")
        admission = dispatch_gate.claim(
            work_id=task.task_id,
            holder=holder,
            now=now,
            ttl=ttl,
            expected_generation=expected_generation,
            retry=False,
        )
        observation = act(reasoning.answer)
        completed = dispatch_gate.complete(admission, now=now)
        correction = None
        if observation.get("success") is not True:
            event = self.corrections.start(
                correction_id=f"correction:{task.task_id}",
                failure_signature_id=self._failure_signature(reasoning.answer, observation),
                summary=f"Observed unsuccessful action {reasoning.answer!r}",
                evidence_refs=reasoning.evidence or ("reasoning:no_evidence",),
            )
            correction = self.corrections.state(event.correction_id)
        return ClosedLoopResult(
            task_id=task.task_id,
            semantic_receipt=receipt,
            reasoned_action=reasoning.answer,
            evidence_refs=reasoning.evidence,
            observation=dict(observation),
            effect_state="EFFECT_OBSERVED",
            corrective_state=correction,
            dispatch_admission=admission,
            dispatch_completed=completed,
        )
