"""Held-out measurement for reviewed correction transfer.

The evaluator executes the real CorrectionTransferGuard and an exact-case
memorizer baseline. It measures transfer only across recurrences that differ
from the original case and surface while sharing an already-bound failure
signature. It does not claim autonomous failure-signature learning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable

from .agi_correction_transfer import (
    CorrectionRecurrence,
    CorrectionTransferDecision,
    CorrectionTransferGuard,
    ExactCaseCorrectionMemorizer,
)


_RUNTIME_BINDINGS = frozenset({
    "SOURCE_ONLY",
    "LOCAL_TEST_RUNTIME",
    "QUALIFIED_RUNTIME",
})


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _rate(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{field} must be in [0, 1]")
    return value


def _exact_head(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 40
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(
            "exact_head must be 40 lowercase hexadecimal characters"
        )


@dataclass(frozen=True, slots=True)
class CorrectionTransferCase:
    recurrence: CorrectionRecurrence
    expected_prevent: bool

    def __post_init__(self) -> None:
        if type(self.recurrence) is not CorrectionRecurrence:
            raise TypeError(
                "recurrence must be exact CorrectionRecurrence"
            )
        if type(self.expected_prevent) is not bool:
            raise TypeError("expected_prevent must be bool")


@dataclass(frozen=True, slots=True)
class CorrectionTransferThresholds:
    min_reviewed_correction_benefit: float
    max_false_positive_prevention_cost: float
    min_recurrence_reduction: float

    def __post_init__(self) -> None:
        for name in (
            "min_reviewed_correction_benefit",
            "max_false_positive_prevention_cost",
            "min_recurrence_reduction",
        ):
            object.__setattr__(
                self,
                name,
                _rate(getattr(self, name), name),
            )


@dataclass(frozen=True, slots=True)
class CorrectionTransferMetrics:
    recurrence_count: int
    safe_control_count: int
    reviewed_recurrence_prevention_rate: float
    baseline_recurrence_prevention_rate: float
    reviewed_correction_benefit: float
    reviewed_safe_false_positive_rate: float
    baseline_safe_false_positive_rate: float
    false_positive_prevention_cost: float
    recurrence_reduction: float


@dataclass(frozen=True, slots=True)
class CorrectionTransferQualificationResult:
    metrics: CorrectionTransferMetrics
    packet: dict[str, object]
    qualification_artifact_json: str
    qualification_artifact_digest: str


def _event_dict(event) -> dict[str, object]:
    return {
        "correction_id": event.correction_id,
        "failure_signature_id": event.failure_signature_id,
        "sequence": event.sequence,
        "stage": event.stage.value,
        "summary": event.summary,
        "evidence_refs": list(event.evidence_refs),
        "guardrail_refs": list(event.guardrail_refs),
        "verification_refs": list(event.verification_refs),
        "previous_digest": event.previous_digest,
        "event_digest": event.event_digest,
    }


def _recurrence_dict(recurrence: CorrectionRecurrence) -> dict[str, object]:
    return {
        "case_id": recurrence.case_id,
        "failure_signature_id": recurrence.failure_signature_id,
        "surface": recurrence.surface,
        "surface_digest": recurrence.surface_digest,
    }


def _decision_dict(
    decision: CorrectionTransferDecision,
) -> dict[str, object]:
    influence = decision.learned_influence
    return {
        "case_id": decision.case_id,
        "outcome": decision.outcome,
        "signature_match": decision.signature_match,
        "case_distinct": decision.case_distinct,
        "surface_distinct": decision.surface_distinct,
        "learned_influence": (
            None
            if influence is None
            else {
                "association_id": influence.association_id,
                "memory_revision_id": influence.memory_revision_id,
                "cue_event_id": influence.cue_event_id,
                "review_disposition": influence.review_disposition.value,
                "review_evidence_ref": influence.review_evidence_ref,
                "authorization_effect": influence.authorization_effect,
            }
        ),
        "authorization_effect": decision.authorization_effect,
    }


def qualify_correction_transfer(
    guard: CorrectionTransferGuard,
    *,
    baseline: ExactCaseCorrectionMemorizer,
    cases: Iterable[CorrectionTransferCase],
    thresholds: CorrectionTransferThresholds,
    repository: str,
    exact_head: str,
    runtime_binding: str,
    curator_independence: str,
    training_overlap: str,
    developer_item_access: bool,
    tool_access: Iterable[str],
    claim_ceiling: str,
) -> CorrectionTransferQualificationResult:
    if type(guard) is not CorrectionTransferGuard:
        raise TypeError("guard must be exact CorrectionTransferGuard")
    if type(baseline) is not ExactCaseCorrectionMemorizer:
        raise TypeError(
            "baseline must be exact ExactCaseCorrectionMemorizer"
        )
    if type(thresholds) is not CorrectionTransferThresholds:
        raise TypeError(
            "thresholds must be exact CorrectionTransferThresholds"
        )

    case_tuple = tuple(cases)
    if not case_tuple:
        raise ValueError("correction transfer cases must not be empty")
    if any(type(case) is not CorrectionTransferCase for case in case_tuple):
        raise TypeError(
            "cases must contain exact CorrectionTransferCase values"
        )
    case_ids = tuple(case.recurrence.case_id for case in case_tuple)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("correction transfer case IDs must be distinct")

    recurrence_cases = tuple(
        case for case in case_tuple if case.expected_prevent
    )
    safe_cases = tuple(
        case for case in case_tuple if not case.expected_prevent
    )
    if not recurrence_cases:
        raise ValueError(
            "correction transfer measurement requires recurrence cases"
        )
    if not safe_cases:
        raise ValueError(
            "correction transfer measurement requires a safe control"
        )

    for case in recurrence_cases:
        recurrence = case.recurrence
        if (
            recurrence.case_id == guard.original_case_id
            or (
                guard.original_surface_digest is not None
                and recurrence.surface_digest
                == guard.original_surface_digest
            )
        ):
            raise ValueError(
                "expected-prevent cases must be a structurally different "
                "recurrence from the original failure"
            )

    if type(repository) is not str or not repository:
        raise ValueError("repository must be a non-empty exact string")
    _exact_head(exact_head)
    if runtime_binding not in _RUNTIME_BINDINGS:
        raise ValueError("unsupported runtime_binding")
    if type(curator_independence) is not str or not curator_independence:
        raise ValueError(
            "curator_independence must be a non-empty exact string"
        )
    if type(training_overlap) is not str or not training_overlap:
        raise ValueError("training_overlap must be a non-empty exact string")
    if type(developer_item_access) is not bool:
        raise TypeError("developer_item_access must be bool")
    tools = tuple(tool_access)
    if any(type(item) is not str or not item for item in tools):
        raise ValueError("tool_access must contain non-empty exact strings")
    if type(claim_ceiling) is not str or not claim_ceiling:
        raise ValueError("claim_ceiling must be a non-empty exact string")

    rows: list[dict[str, object]] = []
    reviewed_recurrence_prevented = 0
    baseline_recurrence_prevented = 0
    reviewed_safe_false_positive = 0
    baseline_safe_false_positive = 0
    reviewed_correct = 0
    baseline_correct = 0

    for index, case in enumerate(case_tuple):
        recurrence = case.recurrence
        decision = guard.decide(
            recurrence,
            cue_event_id=f"correction-transfer:{index}:{recurrence.case_id}",
        )
        baseline_prevent = baseline.should_prevent(recurrence)
        reviewed_prevent = decision.outcome == "PREVENT"

        if case.expected_prevent:
            reviewed_recurrence_prevented += int(reviewed_prevent)
            baseline_recurrence_prevented += int(baseline_prevent)
        else:
            reviewed_safe_false_positive += int(reviewed_prevent)
            baseline_safe_false_positive += int(baseline_prevent)

        reviewed_correct += int(
            reviewed_prevent is case.expected_prevent
        )
        baseline_correct += int(
            baseline_prevent is case.expected_prevent
        )

        rows.append({
            "case": {
                **_recurrence_dict(recurrence),
                "expected_prevent": case.expected_prevent,
            },
            "expected_prevent": case.expected_prevent,
            "decision": _decision_dict(decision),
            "baseline_prevent": baseline_prevent,
        })

    recurrence_count = len(recurrence_cases)
    safe_count = len(safe_cases)
    reviewed_recurrence_rate = (
        reviewed_recurrence_prevented / recurrence_count
    )
    baseline_recurrence_rate = (
        baseline_recurrence_prevented / recurrence_count
    )
    reviewed_safe_fp = reviewed_safe_false_positive / safe_count
    baseline_safe_fp = baseline_safe_false_positive / safe_count
    reviewed_accuracy = reviewed_correct / len(case_tuple)
    baseline_accuracy = baseline_correct / len(case_tuple)
    reviewed_benefit = reviewed_accuracy - baseline_accuracy
    false_positive_cost = max(0.0, reviewed_safe_fp - baseline_safe_fp)
    recurrence_reduction = (
        (1.0 - baseline_recurrence_rate)
        - (1.0 - reviewed_recurrence_rate)
    )

    metrics = CorrectionTransferMetrics(
        recurrence_count=recurrence_count,
        safe_control_count=safe_count,
        reviewed_recurrence_prevention_rate=reviewed_recurrence_rate,
        baseline_recurrence_prevention_rate=baseline_recurrence_rate,
        reviewed_correction_benefit=reviewed_benefit,
        reviewed_safe_false_positive_rate=reviewed_safe_fp,
        baseline_safe_false_positive_rate=baseline_safe_fp,
        false_positive_prevention_cost=false_positive_cost,
        recurrence_reduction=recurrence_reduction,
    )

    metrics_pass = (
        reviewed_benefit
        >= thresholds.min_reviewed_correction_benefit
        and false_positive_cost
        <= thresholds.max_false_positive_prevention_cost
        and recurrence_reduction
        >= thresholds.min_recurrence_reduction
    )
    state = "PARTIAL" if metrics_pass else "FAIL"
    dimensions = {
        "RETENTION_AND_INTERFERENCE": state,
        "ROBUSTNESS_AND_ANTI_GAMING": state,
    }

    items = [
        {
            **_recurrence_dict(case.recurrence),
            "expected_prevent": case.expected_prevent,
        }
        for case in case_tuple
    ]
    items_digest = hashlib.sha256(
        _canonical_json(items).encode("utf-8")
    ).hexdigest()
    probe_id = f"correction-transfer-{items_digest[:16]}"

    correction = guard.correction
    original_failure = correction.events[0]
    artifact = {
        "schema": "VERA_AGI_CORRECTION_TRANSFER_QUALIFICATION_V1",
        "probe_id": probe_id,
        "items_digest": items_digest,
        "failure_signature_id": correction.failure_signature_id,
        "original_case_id": guard.original_case_id,
        "original_surface_digest": guard.original_surface_digest,
        "original_failure_event": _event_dict(original_failure),
        "correction_event_chain": [
            _event_dict(event) for event in correction.events
        ],
        "completed_correction_head_digest": (
            correction.events[-1].event_digest
        ),
        "thresholds": asdict(thresholds),
        "metrics": asdict(metrics),
        "cases": rows,
        "curator_independence": curator_independence,
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "measurement_only": True,
        "independent_review_required_for_pass": True,
        "signature_classifier_learned_by_subject": False,
        "dimension_states": dimensions,
    }
    artifact_json = _canonical_json(artifact)
    artifact_digest = hashlib.sha256(
        artifact_json.encode("utf-8")
    ).hexdigest()

    packet = {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": repository,
            "exact_head": exact_head,
            "runtime_binding": runtime_binding,
        },
        "probe": {
            "probe_id": probe_id,
            "family": "CORRECTION_TRANSFER",
            "held_out": True,
            "curator_independence": curator_independence,
            "items_digest": items_digest,
        },
        "contamination": {
            "training_overlap": training_overlap,
            "post_disclosure_tuning": False,
            "developer_item_access": developer_item_access,
            "tool_access": list(tools),
        },
        "results": {
            "attempted": len(case_tuple),
            "passed": reviewed_correct,
            "failed": len(case_tuple) - reviewed_correct,
            "raw_artifact_digest": artifact_digest,
            "negative_results_preserved": True,
        },
        "dimension_states": dimensions,
        "independent_review": None,
        "claim_ceiling": claim_ceiling,
    }

    return CorrectionTransferQualificationResult(
        metrics=metrics,
        packet=packet,
        qualification_artifact_json=artifact_json,
        qualification_artifact_digest=artifact_digest,
    )
