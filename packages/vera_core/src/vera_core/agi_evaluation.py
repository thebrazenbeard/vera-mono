"""Held-out AGI research probe execution.

The subject callback receives only model_input. Hidden expected values and
evaluator-only context remain on the evaluator side, while immutable digests
bind the complete probe definition and raw attempt record.

This module produces research evidence only. It does not promote any AGI
claim or mint execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping


_ALLOWED_FAMILIES = frozenset({
    "NOVEL_MAPPING",
    "COMPOSITIONAL_TRANSFER",
    "REGIME_RETURN",
    "AMBIGUOUS_SPEC",
    "CORRECTION_TRANSFER",
    "EXTERNAL_ENVIRONMENT",
})

_ALLOWED_CURATOR_INDEPENDENCE = frozenset({
    "DEVELOPER_AUTHORED_HIDDEN_CUT",
    "INDEPENDENT_MODEL",
    "INDEPENDENT_HUMAN",
    "EXTERNAL_BENCHMARK",
})

_ALLOWED_TRAINING_OVERLAP = frozenset({
    "NONE_KNOWN",
    "POSSIBLE",
    "CONFIRMED",
    "UNKNOWN",
})


def _canonical_json(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise TypeError("held-out artifacts must be JSON-serializable") from exc
    return text.encode("utf-8")


@dataclass(frozen=True, slots=True)
class HeldOutCase:
    case_id: str
    model_input: Any
    expected: Any
    evaluator_context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.case_id) is not str or not self.case_id:
            raise ValueError("case_id must be a non-empty exact string")
        object.__setattr__(
            self,
            "evaluator_context",
            MappingProxyType(dict(self.evaluator_context)),
        )
        _canonical_json(
            {
                "case_id": self.case_id,
                "model_input": self.model_input,
                "expected": self.expected,
                "evaluator_context": dict(self.evaluator_context),
            }
        )


@dataclass(frozen=True, slots=True)
class HeldOutProbe:
    probe_id: str
    family: str
    curator_independence: str
    cases: tuple[HeldOutCase, ...]

    def __post_init__(self) -> None:
        if type(self.probe_id) is not str or not self.probe_id:
            raise ValueError("probe_id must be a non-empty exact string")
        if self.family not in _ALLOWED_FAMILIES:
            raise ValueError(f"unsupported held-out family: {self.family!r}")
        if self.curator_independence not in _ALLOWED_CURATOR_INDEPENDENCE:
            raise ValueError(
                "unsupported curator independence classification"
            )
        if type(self.cases) is not tuple or not self.cases:
            raise ValueError("cases must be a non-empty exact tuple")
        if not all(type(case) is HeldOutCase for case in self.cases):
            raise TypeError("cases must contain exact HeldOutCase values")


@dataclass(frozen=True, slots=True)
class AGIContaminationDisclosure:
    training_overlap: str
    post_disclosure_tuning: bool
    developer_item_access: bool
    tool_access: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.training_overlap not in _ALLOWED_TRAINING_OVERLAP:
            raise ValueError("unsupported training overlap classification")
        if type(self.post_disclosure_tuning) is not bool:
            raise TypeError("post_disclosure_tuning must be bool")
        if type(self.developer_item_access) is not bool:
            raise TypeError("developer_item_access must be bool")
        if type(self.tool_access) is not tuple or not all(
            type(item) is str and item for item in self.tool_access
        ):
            raise TypeError(
                "tool_access must be a tuple of non-empty exact strings"
            )


@dataclass(frozen=True, slots=True)
class HeldOutAttempt:
    case_id: str
    prediction: Any
    passed: bool
    evaluator_context: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evaluator_context",
            MappingProxyType(dict(self.evaluator_context)),
        )


@dataclass(frozen=True, slots=True)
class HeldOutProbeResult:
    probe_id: str
    family: str
    curator_independence: str
    attempts: tuple[HeldOutAttempt, ...]
    attempted: int
    passed: int
    failed: int
    items_digest: str
    raw_artifact_digest: str
    negative_results_preserved: bool
    contamination: AGIContaminationDisclosure
    authorization_effect: str = "NONE"


def _probe_items_payload(probe: HeldOutProbe) -> list[dict[str, object]]:
    return [
        {
            "case_id": case.case_id,
            "model_input": case.model_input,
            "expected": case.expected,
            "evaluator_context": dict(case.evaluator_context),
        }
        for case in probe.cases
    ]


def run_held_out_probe(
    probe: HeldOutProbe,
    *,
    subject: Callable[[Any], Any],
    score: Callable[[Any, Any], bool],
    contamination: AGIContaminationDisclosure,
) -> HeldOutProbeResult:
    """Run an immutable held-out cut without exposing evaluator answers."""

    if type(probe) is not HeldOutProbe:
        raise TypeError("probe must be exact HeldOutProbe")
    if type(contamination) is not AGIContaminationDisclosure:
        raise TypeError(
            "contamination must be exact AGIContaminationDisclosure"
        )
    if contamination.post_disclosure_tuning:
        raise ValueError(
            "post-disclosure tuning invalidates this held-out cut"
        )

    item_payload = _probe_items_payload(probe)
    items_digest = hashlib.sha256(
        _canonical_json(item_payload)
    ).hexdigest()

    attempts: list[HeldOutAttempt] = []
    raw_attempts: list[dict[str, object]] = []
    passed_count = 0

    for case in probe.cases:
        prediction = subject(case.model_input)
        verdict = score(prediction, case.expected)
        if type(verdict) is not bool:
            raise TypeError("score must return exact bool")

        attempt = HeldOutAttempt(
            case_id=case.case_id,
            prediction=prediction,
            passed=verdict,
            evaluator_context=case.evaluator_context,
        )
        attempts.append(attempt)
        if verdict:
            passed_count += 1

        raw_attempts.append(
            {
                "case_id": case.case_id,
                "prediction": prediction,
                "passed": verdict,
                "expected": case.expected,
                "evaluator_context": dict(case.evaluator_context),
            }
        )

    raw_artifact = {
        "probe_id": probe.probe_id,
        "family": probe.family,
        "curator_independence": probe.curator_independence,
        "items_digest": items_digest,
        "attempts": raw_attempts,
        "contamination": {
            "training_overlap": contamination.training_overlap,
            "post_disclosure_tuning": contamination.post_disclosure_tuning,
            "developer_item_access": contamination.developer_item_access,
            "tool_access": list(contamination.tool_access),
        },
    }
    raw_artifact_digest = hashlib.sha256(
        _canonical_json(raw_artifact)
    ).hexdigest()

    attempted = len(attempts)
    return HeldOutProbeResult(
        probe_id=probe.probe_id,
        family=probe.family,
        curator_independence=probe.curator_independence,
        attempts=tuple(attempts),
        attempted=attempted,
        passed=passed_count,
        failed=attempted - passed_count,
        items_digest=items_digest,
        raw_artifact_digest=raw_artifact_digest,
        negative_results_preserved=True,
        contamination=contamination,
    )


_FAMILY_DIMENSIONS = {
    "NOVEL_MAPPING": (
        "NOVEL_TASK_TRANSFER",
        "LEARNING_EFFICIENCY",
    ),
    "COMPOSITIONAL_TRANSFER": (
        "NOVEL_TASK_TRANSFER",
        "CROSS_DOMAIN_BREADTH",
    ),
    "REGIME_RETURN": (
        "RETENTION_AND_INTERFERENCE",
    ),
    "AMBIGUOUS_SPEC": (
        "METACOGNITIVE_CALIBRATION",
        "ROBUSTNESS_AND_ANTI_GAMING",
        "LONG_HORIZON_AGENCY",
    ),
    "CORRECTION_TRANSFER": (
        "RETENTION_AND_INTERFERENCE",
        "ROBUSTNESS_AND_ANTI_GAMING",
    ),
    "EXTERNAL_ENVIRONMENT": (
        "EXTERNAL_GENERALIZATION",
    ),
}

_ALLOWED_RUNTIME_BINDINGS = frozenset({
    "SOURCE_ONLY",
    "LOCAL_TEST_RUNTIME",
    "QUALIFIED_RUNTIME",
})

_ALLOWED_DIMENSION_STATES = frozenset({
    "NOT_EVALUATED",
    "FAIL",
    "PARTIAL",
    "PASS",
})


def build_agi_evaluation_packet(
    result: HeldOutProbeResult,
    *,
    repository: str,
    exact_head: str,
    runtime_binding: str,
    dimension_states: Mapping[str, str],
    claim_ceiling: str,
    independent_review: object | None = None,
) -> dict[str, object]:
    """Bind held-out probe evidence into the governed packet shape."""

    if type(result) is not HeldOutProbeResult:
        raise TypeError("result must be exact HeldOutProbeResult")
    if type(repository) is not str or not repository:
        raise ValueError("repository must be a non-empty exact string")
    if (
        type(exact_head) is not str
        or len(exact_head) != 40
        or any(ch not in "0123456789abcdef" for ch in exact_head)
    ):
        raise ValueError("exact_head must be 40 lowercase hexadecimal characters")
    if runtime_binding not in _ALLOWED_RUNTIME_BINDINGS:
        raise ValueError("unsupported runtime_binding")
    if type(dimension_states) is not dict:
        dimension_states = dict(dimension_states)
    if not dimension_states:
        raise ValueError("dimension_states must not be empty")
    bad_states = {
        key: value
        for key, value in dimension_states.items()
        if type(key) is not str
        or not key
        or value not in _ALLOWED_DIMENSION_STATES
    }
    if bad_states:
        raise ValueError(f"invalid dimension state entries: {bad_states!r}")

    required_dimensions = _FAMILY_DIMENSIONS[result.family]
    missing = [
        dimension
        for dimension in required_dimensions
        if dimension not in dimension_states
    ]
    if missing:
        raise ValueError(
            "missing required family target dimensions: "
            + ", ".join(missing)
        )
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    contamination = result.contamination
    return {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": repository,
            "exact_head": exact_head,
            "runtime_binding": runtime_binding,
        },
        "probe": {
            "probe_id": result.probe_id,
            "family": result.family,
            "held_out": True,
            "curator_independence": result.curator_independence,
            "items_digest": result.items_digest,
        },
        "contamination": {
            "training_overlap": contamination.training_overlap,
            "post_disclosure_tuning": contamination.post_disclosure_tuning,
            "developer_item_access": contamination.developer_item_access,
            "tool_access": list(contamination.tool_access),
        },
        "results": {
            "attempted": result.attempted,
            "passed": result.passed,
            "failed": result.failed,
            "raw_artifact_digest": result.raw_artifact_digest,
            "negative_results_preserved": result.negative_results_preserved,
        },
        "dimension_states": dict(dimension_states),
        "independent_review": independent_review,
        "claim_ceiling": claim_ceiling,
    }



def run_prequential_held_out_probe(
    probe: HeldOutProbe,
    *,
    predict: Callable[[Any], Any],
    score: Callable[[Any, Any], bool],
    update: Callable[[Any, Any], Any],
    contamination: AGIContaminationDisclosure,
) -> HeldOutProbeResult:
    """Score every held-out case before revealing its answer to update."""

    if type(probe) is not HeldOutProbe:
        raise TypeError("probe must be exact HeldOutProbe")
    if type(contamination) is not AGIContaminationDisclosure:
        raise TypeError(
            "contamination must be exact AGIContaminationDisclosure"
        )
    if contamination.post_disclosure_tuning:
        raise ValueError(
            "post-disclosure tuning invalidates this held-out cut"
        )

    item_payload = _probe_items_payload(probe)
    items_digest = hashlib.sha256(
        _canonical_json(item_payload)
    ).hexdigest()

    attempts: list[HeldOutAttempt] = []
    raw_attempts: list[dict[str, object]] = []
    passed_count = 0

    for case in probe.cases:
        prediction = predict(case.model_input)
        verdict = score(prediction, case.expected)
        if type(verdict) is not bool:
            raise TypeError("score must return exact bool")

        attempt = HeldOutAttempt(
            case_id=case.case_id,
            prediction=prediction,
            passed=verdict,
            evaluator_context=case.evaluator_context,
        )
        attempts.append(attempt)
        if verdict:
            passed_count += 1

        raw_attempts.append(
            {
                "case_id": case.case_id,
                "prediction": prediction,
                "passed": verdict,
                "expected": case.expected,
                "evaluator_context": dict(case.evaluator_context),
            }
        )

        update(case.model_input, case.expected)

    raw_artifact = {
        "probe_id": probe.probe_id,
        "family": probe.family,
        "curator_independence": probe.curator_independence,
        "items_digest": items_digest,
        "evaluation_order": "PREDICT_SCORE_THEN_UPDATE",
        "attempts": raw_attempts,
        "contamination": {
            "training_overlap": contamination.training_overlap,
            "post_disclosure_tuning": contamination.post_disclosure_tuning,
            "developer_item_access": contamination.developer_item_access,
            "tool_access": list(contamination.tool_access),
        },
    }
    raw_artifact_digest = hashlib.sha256(
        _canonical_json(raw_artifact)
    ).hexdigest()

    attempted = len(attempts)
    return HeldOutProbeResult(
        probe_id=probe.probe_id,
        family=probe.family,
        curator_independence=probe.curator_independence,
        attempts=tuple(attempts),
        attempted=attempted,
        passed=passed_count,
        failed=attempted - passed_count,
        items_digest=items_digest,
        raw_artifact_digest=raw_artifact_digest,
        negative_results_preserved=True,
        contamination=contamination,
    )
