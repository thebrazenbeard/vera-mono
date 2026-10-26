"""Synthetic, in-process correction/holdout/review/rollback command.

This lab is deliberately outside Vera's state, network, models and memory.
Caller-provided references do not authenticate a human or establish consent.
No samples, answers, or generated text are emitted or retained on disk.
"""

from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path

from vera_memory.local_feedback_learning import (
    FeedbackSample, HeldoutCase, LocalFeedbackLearner,
)


_MAX_FIXTURE_BYTES = 64 * 1024
_SCHEMA = "VERA_MONO_SYNTHETIC_FEEDBACK_LAB_V1"


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous duplicate JSON field")
        result[key] = value
    return result


def _records(value: object, kind: type) -> tuple:
    if type(value) is not list or not value or len(value) > 128:
        raise ValueError("synthetic fixture requires bounded non-empty record arrays")
    expected = {field.name for field in fields(kind)}
    rows = []
    for item in value:
        if type(item) is not dict or set(item) != expected:
            raise ValueError("synthetic fixture record fields do not match schema")
        row = kind(**item)
        row.validate()
        rows.append(row)
    return tuple(rows)


def _fixture(path: Path) -> tuple[tuple[FeedbackSample, ...], tuple[HeldoutCase, ...]]:
    # A bounded read prevents a race in which an untrusted file grows after stat.
    with path.open("rb") as stream:
        raw = stream.read(_MAX_FIXTURE_BYTES + 1)
    if len(raw) > _MAX_FIXTURE_BYTES:
        raise ValueError("synthetic feedback fixture exceeds 64 KiB")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    if (type(data) is not dict or set(data) != {"schema", "synthetic", "samples", "holdout"}
            or data["schema"] != _SCHEMA or data["synthetic"] is not True):
        raise ValueError("only explicitly labeled synthetic feedback fixtures are accepted")
    return (_records(data["samples"], FeedbackSample),
            _records(data["holdout"], HeldoutCase))


def evaluate_fixture(path: Path, *, approval_ref: str | None = None,
                     rollback_ref: str | None = None) -> dict[str, object]:
    """Exercise a local correction without granting durable learning authority.

    `approval_ref` is an unauthenticated CLI assertion: supplying it explicitly
    exercises the review gate, but it is not independent human approval proof.
    """
    for name, ref in (("approval", approval_ref), ("rollback", rollback_ref)):
        if ref is not None and (
            type(ref) is not str or not ref.strip() or len(ref) > 256
            or any(0xD800 <= ord(char) <= 0xDFFF for char in ref)
        ):
            raise ValueError(f"{name} reference must be a bounded exact string")
    if rollback_ref is not None and approval_ref is None:
        raise ValueError("rollback requires a prior explicit approval flag")
    if rollback_ref is not None and rollback_ref == approval_ref:
        raise ValueError("rollback requires an independent review reference")
    samples, holdout = _fixture(path)
    learner = LocalFeedbackLearner()
    genesis = learner.active_revision
    candidate = learner.stage(samples)
    evaluation = learner.evaluate(candidate, holdout)
    if rollback_ref is not None and not evaluation.qualified:
        raise ValueError("cannot roll back a correction that failed qualification")
    rolled_back = False
    if approval_ref is not None and evaluation.qualified:
        learner.approve(evaluation, approval_ref=approval_ref)
        if rollback_ref is not None:
            learner.rollback(genesis, approval_ref=rollback_ref)
            rolled_back = True
    return {
        "schema": "VERA_MONO_FEEDBACK_LAB_RESULT_V1",
        "claim_ceiling": "SYNTHETIC_PROCESS_LOCAL_EXACT_CUE_PROBE_NOT_SELF_LEARNING",
        "approval_authentication": "CALLER_ASSERTED_ONLY",
        "memory_admission": "NONE",
        "tool_execution": "NONE",
        "weight_training": "NONE",
        "baseline_revision": genesis,
        "candidate_revision": candidate,
        "heldout_sha256": evaluation.heldout_sha256,
        "heldout_cases": evaluation.heldout_cases,
        "baseline_passes": evaluation.baseline_passes,
        "candidate_passes": evaluation.candidate_passes,
        "candidate_qualified": evaluation.qualified,
        "active_candidate": learner.active_revision == candidate,
        "correction_active": learner.lookup(samples[0].cue) == samples[0].answer,
        "review_receipts": len(learner.review_receipts),
        "rolled_back": rolled_back,
    }
