"""Research-only closed-loop learning frontier composition.

This module composes existing Vera Mono semantic, reasoning, dispatch,
observation, corrective-learning, and reviewed-learning mechanisms. It does
not mint authority and callback observations are not external-effect claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from vera_identity import SemanticAdmissionReceipt, SemanticKnowledgeStore
from vera_memory import (
    LearnedInfluenceGate,
    LearnedInfluenceReceipt,
    LearnedRevision,
    ReviewDisposition,
)

from .corrective_learning import (
    CorrectionState,
    CorrectiveLearningLedger,
    CorrectiveStage,
)
from .durable_dispatch_gate import DispatchAdmission, DurableDispatchGate


CALLBACK_OBSERVATION_RECORDED = "CALLBACK_OBSERVATION_RECORDED"


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
    observation_state: str
    corrective_state: CorrectionState | None
    learned_influence: LearnedInfluenceReceipt | None = None
    dispatch_admission: DispatchAdmission | None = None
    dispatch_completed: bool | None = None
    authorization_effect: str = "NONE"


class ClosedLoopFrontier:
    """Compose bounded learning-loop mechanisms without authority promotion."""

    def __init__(self, state_dir: str | Path) -> None:
        root = Path(state_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.semantic = SemanticKnowledgeStore(root / "semantic.db")
        self.corrections = CorrectiveLearningLedger(root / "corrections.db")
        self.learned_influence = LearnedInfluenceGate()

    @staticmethod
    def _validate_reasoning(
        action: str,
        evidence_refs: tuple[str, ...],
    ) -> tuple[str, tuple[str, ...]]:
        if type(action) is not str or not action:
            raise ValueError("reasoned action must be a non-empty exact string")
        if type(evidence_refs) is not tuple or not evidence_refs:
            raise ValueError("reasoning must return non-empty evidence refs")
        return action, evidence_refs

    @staticmethod
    def _validate_observation(
        observation: dict[str, object],
    ) -> dict[str, object]:
        if type(observation) is not dict:
            raise TypeError("act must return an observation dict")
        return dict(observation)

    def _record_failure(
        self,
        *,
        task: ClosedLoopTask,
        action: str,
        evidence_refs: tuple[str, ...],
    ) -> CorrectionState:
        correction_id = f"correction:{task.task_id}"
        try:
            return self.corrections.state(correction_id)
        except KeyError:
            event = self.corrections.start(
                correction_id=correction_id,
                failure_signature_id=f"observed_failure:{action}",
                summary=f"Observed unsuccessful action {action!r}",
                evidence_refs=evidence_refs,
            )
            return self.corrections.state(event.correction_id)

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
        action, evidence_refs = self._validate_reasoning(
            *reason(task.prompt, task.semantic_object)
        )
        observation = self._validate_observation(act(action))

        correction = None
        if observation.get("success") is not True:
            correction = self._record_failure(
                task=task,
                action=action,
                evidence_refs=evidence_refs,
            )

        return ClosedLoopResult(
            task_id=task.task_id,
            semantic_receipt=receipt,
            reasoned_action=action,
            evidence_refs=evidence_refs,
            observation=observation,
            observation_state=CALLBACK_OBSERVATION_RECORDED,
            corrective_state=correction,
        )

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
        if type(task) is not ClosedLoopTask:
            raise TypeError("task must be exact ClosedLoopTask")

        influence = self.learned_influence.consume(
            revision,
            cue_event_id=cue_event_id,
        )
        receipt = self.semantic.admit(task.semantic_object)
        action, evidence_refs = self._validate_reasoning(
            *reason(task.prompt, task.semantic_object, revision)
        )
        observation = self._validate_observation(act(action))

        correction_id = f"correction:{task.task_id}"
        try:
            correction = self.corrections.state(correction_id)
        except KeyError:
            correction = None

        if observation.get("success") is not True:
            if correction is None:
                correction = self._record_failure(
                    task=task,
                    action=action,
                    evidence_refs=evidence_refs,
                )
        elif correction is not None and not correction.completed:
            if correction.current_stage is CorrectiveStage.FLAG:
                self.corrections.advance(
                    correction_id,
                    stage=CorrectiveStage.UNDERSTAND,
                    summary=(
                        "Reviewed learned revision produced successful retry"
                    ),
                    evidence_refs=evidence_refs,
                )
                correction = self.corrections.state(correction_id)

        return ClosedLoopResult(
            task_id=task.task_id,
            semantic_receipt=receipt,
            reasoned_action=action,
            evidence_refs=evidence_refs,
            observation=observation,
            observation_state=CALLBACK_OBSERVATION_RECORDED,
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
        if type(task) is not ClosedLoopTask:
            raise TypeError("task must be exact ClosedLoopTask")

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
        observation = self._validate_observation(act(reasoning.answer))
        completed = dispatch_gate.complete(admission, now=now)

        correction = None
        if observation.get("success") is not True:
            correction = self._record_failure(
                task=task,
                action=reasoning.answer,
                evidence_refs=(
                    reasoning.evidence or ("reasoning:no_evidence",)
                ),
            )

        return ClosedLoopResult(
            task_id=task.task_id,
            semantic_receipt=receipt,
            reasoned_action=reasoning.answer,
            evidence_refs=reasoning.evidence,
            observation=observation,
            observation_state=CALLBACK_OBSERVATION_RECORDED,
            corrective_state=correction,
            dispatch_admission=admission,
            dispatch_completed=completed,
        )
