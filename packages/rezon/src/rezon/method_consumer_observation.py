"""Effectless local observation of a host-supplied consumer receiving a Rezon result.

A consumer call is measured here; use of the result in its decision is NOT
attested. This cannot authenticate the host, interpreter, closures, evaluator,
clock, transitive dependencies or QualifiedVeraRuntime route.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from types import FunctionType
from typing import Literal

from .cascade import LayerResult
from .method_observation import (
    MethodInvocationObservation, _hash, measured_function_bytecode_sha256,
)
from .method_evaluation_join import (
    MethodSelectionCommitment, DeclaredEvaluatorOutcome, StructuralMethodUseLink,
    join_method_evaluation,
)


def _result_hash(result: LayerResult) -> str:
    if type(result) is not LayerResult:
        raise TypeError("exact LayerResult required")
    return _hash({
        "answer": result.answer, "unresolved": result.unresolved,
        "confidence": result.confidence, "evidence": result.evidence,
        "changed_dimensions": result.changed_dimensions,
    })


@dataclass(frozen=True, slots=True)
class DeclaredConsumerRoute:
    consumer_id: str
    consumer_execution_id: str
    expected_consumer_bytecode_sha256: str

    def __post_init__(self) -> None:
        if not self.consumer_id or not self.consumer_execution_id:
            raise ValueError("consumer and execution identity required")
        d = self.expected_consumer_bytecode_sha256
        if type(d) is not str or len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
            raise ValueError("expected consumer code must have exact SHA256")


@dataclass(frozen=True, slots=True)
class LocalConsumerObservation:
    method_id: str
    revision_id: str
    task_id: str
    execution_cut_id: str
    invocation_number: int
    selection_sha256: str
    method_result_sha256: str
    consumer_id: str
    consumer_execution_id: str
    host_pid: int
    consumer_code_before_sha256: str
    consumer_code_after_sha256: str
    consumer_result_sha256: str | None
    outcome: Literal["RETURNED", "RAISED"]
    exception_type: str | None
    status: str = "LOCAL_CONSUMER_CALL_ONLY"
    local_consumer_call_observed: bool = True
    consumer_route_independently_verified: bool = False
    consumer_semantic_use_verified: bool = False
    transitive_dependency_closure_measured: bool = False
    mutable_closure_state_measured: bool = False
    evaluator_custody_verified: bool = False
    precommit_timing_verified: bool = False
    qualified_runtime_consumption_verified: bool = False
    cold_restart_reuse_verified: bool = False
    authorization_effect: str = "NONE"


class MethodConsumerObserver:
    """Explicit adapter: the actual callback is called only after digest matching.

    Input records are local/declared and remain unauthenticated. An independent
    host could later witness this boundary without promoting current flags.
    """
    def __init__(
        self,
        selection: MethodSelectionCommitment,
        invocation: MethodInvocationObservation,
        evaluation: DeclaredEvaluatorOutcome,
        route: DeclaredConsumerRoute,
    ) -> None:
        if type(route) is not DeclaredConsumerRoute:
            raise TypeError("exact DeclaredConsumerRoute required")
        self.link: StructuralMethodUseLink = join_method_evaluation(
            selection, invocation, evaluation
        )
        self.route = route
        self.observations: list[LocalConsumerObservation] = []

    def consume(self, method_result: LayerResult, consumer_run: FunctionType) -> str:
        if _result_hash(method_result) != self.link.result_sha256:
            raise ValueError("method result bytes differ from observed invocation")
        if not isinstance(consumer_run, FunctionType):
            raise TypeError("ordinary Python consumer function required")
        before = measured_function_bytecode_sha256(consumer_run)
        if before != self.route.expected_consumer_bytecode_sha256:
            raise ValueError("consumer callable code does not match declared route")
        returned: str | None = None
        failure: str | None = None
        try:
            returned = consumer_run(method_result)  # actual locally observed call
            if type(returned) is not str:
                raise TypeError("consumer must return exact str for this research interface")
            return returned
        except BaseException as exc:
            failure = type(exc).__name__
            raise
        finally:
            after = measured_function_bytecode_sha256(consumer_run)
            self.observations.append(LocalConsumerObservation(
                method_id=self.link.method_id, revision_id=self.link.revision_id,
                task_id=self.link.task_id, execution_cut_id=self.link.execution_cut_id,
                invocation_number=self.link.invocation_number,
                selection_sha256=self.link.selection_sha256,
                method_result_sha256=self.link.result_sha256,
                consumer_id=self.route.consumer_id,
                consumer_execution_id=self.route.consumer_execution_id,
                host_pid=os.getpid(), consumer_code_before_sha256=before,
                consumer_code_after_sha256=after,
                consumer_result_sha256=_hash({"returned": returned}) if failure is None else None,
                outcome="RAISED" if failure else "RETURNED", exception_type=failure,
            ))
