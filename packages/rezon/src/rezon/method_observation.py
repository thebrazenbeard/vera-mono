"""Research-only in-process evidence for a real Rezon layer invocation.

This adapter is not an independent executable attestation, evaluator, learner,
authority source or QualifiedVeraRuntime installation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from types import CodeType, FunctionType
from typing import Literal

from .cascade import LayerResult, LayerSpec, ReasoningRequest


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                   allow_nan=False).encode("utf-8")
    ).hexdigest()


def measured_function_bytecode_sha256(fn: FunctionType) -> str:
    """Hash stable logical CPython code fields, not adaptive quickened caches.

    This deliberately excludes globals, defaults, closure cells, dependencies,
    mutable state, tools, providers and interpreter behavior.
    """
    if not isinstance(fn, FunctionType):
        raise TypeError("research adapter requires an ordinary Python function")

    def encode(value: object) -> object:
        if isinstance(value, CodeType):
            return {
                "code": value.co_code.hex(), "consts": [encode(x) for x in value.co_consts],
                "names": value.co_names, "varnames": value.co_varnames,
                "freevars": value.co_freevars, "cellvars": value.co_cellvars,
                "argcount": value.co_argcount, "posonly": value.co_posonlyargcount,
                "kwonly": value.co_kwonlyargcount, "flags": value.co_flags,
            }
        if value is None or type(value) in (bool, int, float, str, bytes):
            return {"bytes": value.hex()} if isinstance(value, bytes) else value
        if isinstance(value, tuple):
            return [encode(x) for x in value]
        if isinstance(value, frozenset):
            return sorted((encode(x) for x in value), key=repr)
        raise TypeError("unsupported code constant type")

    return _hash(encode(fn.__code__))


@dataclass(frozen=True)
class MethodExecutionEnvelope:
    method_id: str
    revision_id: str
    task_id: str
    selected_source_head: str
    expected_bytecode_sha256: str
    execution_cut_id: str
    budget_id: str
    dependency_closure_sha256: str | None = None
    mutable_state_sha256: str | None = None
    model_route_digest: str | None = None
    toolset_digest: str | None = None
    selection_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("method_id", "revision_id", "task_id", "execution_cut_id",
                     "budget_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} required")
        for name in ("selected_source_head", "expected_bytecode_sha256"):
            value = getattr(self, name)
            size = 40 if name == "selected_source_head" else 64
            if len(value) != size or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"{name} must be exact lowercase digest")
        for name in ("dependency_closure_sha256", "mutable_state_sha256",
                     "model_route_digest", "toolset_digest"):
            value = getattr(self, name)
            if value is not None and (
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError(f"{name} must be null or SHA256")
        if any(type(x) is not str or not x for x in self.selection_evidence_ids):
            raise ValueError("selection evidence must be nonempty strings")


@dataclass(frozen=True)
class MethodInvocationObservation:
    method_id: str
    revision_id: str
    task_id: str
    execution_cut_id: str
    invocation_number: int
    host_pid: int
    request_sha256: str
    result_sha256: str | None
    code_before_sha256: str
    code_after_sha256: str
    outcome: Literal["RETURNED", "RAISED"]
    exception_type: str | None
    dependency_closure_measured: bool = False
    mutable_state_measured: bool = False
    independent_execution_witness: bool = False
    evaluator_isolation_verified: bool = False
    downstream_method_use_verified: bool = False
    authorization_effect: str = "NONE"


class MethodInvocationObserver:
    """Records actual wrapper-local calls without claiming transitive identity."""

    def __init__(self, envelope: MethodExecutionEnvelope) -> None:
        if type(envelope) is not MethodExecutionEnvelope:
            raise TypeError("exact MethodExecutionEnvelope required")
        self.envelope = envelope
        self.invocations: list[MethodInvocationObservation] = []

    def bind_layer(self, layer: LayerSpec) -> LayerSpec:
        if type(layer) is not LayerSpec:
            raise TypeError("exact LayerSpec required")
        run = layer.run
        code = measured_function_bytecode_sha256(run)
        if code != self.envelope.expected_bytecode_sha256:
            raise ValueError("selected callable does not match expected bytecode")
        envelope = self.envelope

        def observed_run(request: ReasoningRequest) -> LayerResult:
            if type(request) is not ReasoningRequest:
                raise TypeError("exact ReasoningRequest required")
            before = measured_function_bytecode_sha256(run)
            if before != envelope.expected_bytecode_sha256:
                raise ValueError("callable code changed before invocation")
            req_digest = _hash({
                "prompt": request.prompt, "unresolved": request.unresolved,
                "prior_answer": request.prior_answer, "iteration": request.iteration,
            })
            result = None
            exc_type = None
            try:
                result = run(request)  # Actual execution seam; no synthetic invocation claim.
                return result
            except BaseException as exc:
                exc_type = type(exc).__name__
                raise
            finally:
                after = measured_function_bytecode_sha256(run)
                result_digest = (
                    _hash({
                        "answer": result.answer,
                        "unresolved": result.unresolved,
                        "confidence": result.confidence,
                        "evidence": result.evidence,
                        "changed_dimensions": result.changed_dimensions,
                    })
                    if type(result) is LayerResult else None
                )
                self.invocations.append(MethodInvocationObservation(
                    method_id=envelope.method_id, revision_id=envelope.revision_id,
                    task_id=envelope.task_id, execution_cut_id=envelope.execution_cut_id,
                    invocation_number=len(self.invocations) + 1, host_pid=os.getpid(),
                    request_sha256=req_digest, result_sha256=result_digest,
                    code_before_sha256=before, code_after_sha256=after,
                    outcome="RAISED" if exc_type else "RETURNED",
                    exception_type=exc_type,
                ))

        return LayerSpec(name=layer.name, run=observed_run,
                         min_confidence=layer.min_confidence,
                         max_iterations=layer.max_iterations)
