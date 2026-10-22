"""Research-only structural join of selected, invoked, and adjudicated Rezon methods.

The join has no trusted clock, no independent evaluator authentication, no
transitive code/state attestation, and no inference of learning or authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .cascade import ReasoningRequest
from .method_observation import (
    MethodExecutionEnvelope,
    MethodInvocationObservation,
    _hash,
)


@dataclass(frozen=True, slots=True)
class MethodSelectionCommitment:
    """Prospective local commitment; storage alone cannot prove timing."""

    envelope: MethodExecutionEnvelope
    request_sha256: str
    prediction_commitment_sha256: str
    selection_sha256: str

    @classmethod
    def before_invocation(
        cls,
        envelope: MethodExecutionEnvelope,
        request: ReasoningRequest,
        *,
        prediction_commitment_sha256: str,
    ) -> "MethodSelectionCommitment":
        if type(envelope) is not MethodExecutionEnvelope:
            raise TypeError("exact MethodExecutionEnvelope required")
        if type(request) is not ReasoningRequest:
            raise TypeError("exact ReasoningRequest required")
        _digest(prediction_commitment_sha256)
        request_sha256 = _hash({
            "prompt": request.prompt,
            "unresolved": request.unresolved,
            "prior_answer": request.prior_answer,
            "iteration": request.iteration,
        })
        selection_sha256 = _hash({
            "envelope": asdict(envelope),
            "request_sha256": request_sha256,
            "prediction_commitment_sha256": prediction_commitment_sha256,
        })
        return cls(envelope, request_sha256, prediction_commitment_sha256,
                   selection_sha256)

    def validate(self) -> None:
        _digest(self.prediction_commitment_sha256)
        _digest(self.request_sha256)
        _digest(self.selection_sha256)
        if self.selection_sha256 != _hash({
            "envelope": asdict(self.envelope),
            "request_sha256": self.request_sha256,
            "prediction_commitment_sha256": self.prediction_commitment_sha256,
        }):
            raise ValueError("selection commitment changed")


def _digest(value: str) -> None:
    if type(value) is not str or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise ValueError("exact lowercase SHA256 required")


@dataclass(frozen=True, slots=True)
class DeclaredEvaluatorOutcome:
    """Evaluator-supplied datum; issuer/label custody is not authenticated."""

    task_id: str
    execution_cut_id: str
    invocation_number: int
    request_sha256: str
    result_sha256: str
    evaluator_id: str
    outcome_digest: str
    verdict: Literal["CORRECT", "INCORRECT", "UNKNOWN"]

    def __post_init__(self) -> None:
        if not self.task_id or not self.execution_cut_id or not self.evaluator_id:
            raise ValueError("task/cut/evaluator identifiers required")
        if type(self.invocation_number) is not int or self.invocation_number < 1:
            raise ValueError("invocation number must be positive exact integer")
        for value in (self.request_sha256, self.result_sha256, self.outcome_digest):
            _digest(value)
        if self.verdict not in ("CORRECT", "INCORRECT", "UNKNOWN"):
            raise ValueError("unsupported evaluation verdict")


@dataclass(frozen=True, slots=True)
class StructuralMethodUseLink:
    method_id: str
    revision_id: str
    task_id: str
    execution_cut_id: str
    invocation_number: int
    selection_sha256: str
    request_sha256: str
    result_sha256: str
    declared_verdict: str
    declared_evaluator_id: str
    status: str = "STRUCTURAL_MATCH_ONLY"
    precommit_timing_verified: bool = False
    independent_execution_witness: bool = False
    evaluator_label_custody_verified: bool = False
    dependency_closure_measured: bool = False
    mutable_state_measured: bool = False
    causal_improvement_verified: bool = False
    cold_restart_reuse_verified: bool = False
    authorization_effect: str = "NONE"


def join_method_evaluation(
    selection: MethodSelectionCommitment,
    invocation: MethodInvocationObservation,
    evaluation: DeclaredEvaluatorOutcome,
) -> StructuralMethodUseLink:
    """Match three local records; never issue independent proof or authority."""
    if type(selection) is not MethodSelectionCommitment:
        raise TypeError("exact selection commitment required")
    if type(invocation) is not MethodInvocationObservation:
        raise TypeError("exact invocation observation required")
    if type(evaluation) is not DeclaredEvaluatorOutcome:
        raise TypeError("exact declared evaluator outcome required")
    selection.validate()
    envelope = selection.envelope
    if (invocation.method_id, invocation.revision_id, invocation.task_id,
            invocation.execution_cut_id) != (
            envelope.method_id, envelope.revision_id, envelope.task_id,
            envelope.execution_cut_id):
        raise ValueError("observed invocation does not match selection")
    if (evaluation.task_id, evaluation.execution_cut_id,
            evaluation.invocation_number) != (
            envelope.task_id, envelope.execution_cut_id,
            invocation.invocation_number):
        raise ValueError("evaluator does not address the observed invocation")
    if (selection.request_sha256 != invocation.request_sha256
            or evaluation.request_sha256 != invocation.request_sha256):
        raise ValueError("request digest mismatch across domains")
    if (invocation.outcome != "RETURNED"
            or invocation.result_sha256 is None
            or evaluation.result_sha256 != invocation.result_sha256):
        raise ValueError("no matching returned method result to score")
    if (invocation.code_before_sha256 != envelope.expected_bytecode_sha256
            or invocation.code_after_sha256 != envelope.expected_bytecode_sha256):
        raise ValueError("observed method bytecode differs from selection")
    if (invocation.independent_execution_witness
            or invocation.evaluator_isolation_verified
            or invocation.downstream_method_use_verified):
        raise ValueError("unqualified observer cannot assert independent proof")
    return StructuralMethodUseLink(
        method_id=envelope.method_id,
        revision_id=envelope.revision_id,
        task_id=envelope.task_id,
        execution_cut_id=envelope.execution_cut_id,
        invocation_number=invocation.invocation_number,
        selection_sha256=selection.selection_sha256,
        request_sha256=invocation.request_sha256,
        result_sha256=invocation.result_sha256,
        declared_verdict=evaluation.verdict,
        declared_evaluator_id=evaluation.evaluator_id,
    )
