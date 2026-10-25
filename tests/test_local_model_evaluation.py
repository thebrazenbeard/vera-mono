"""Synthetic, opt-in benchmarks for the effectless loopback model adapter."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from vera_core.local_model_advisory import AdvisoryResult, LocalModelError
from vera_core.local_model_evaluation import EvaluationCase, evaluate_cases, load_cases, suite_commitment


def _result(prompt: str, text: str, *, finish_reason: str = "stop") -> AdvisoryResult:
    return AdvisoryResult(
        endpoint="http://127.0.0.1:11434/v1",
        model_id="vera-local:latest",
        prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
        response_sha256=sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        finish_reason=finish_reason,
    )


def test_exact_observations_separate_success_failure_and_truncation():
    cases = (
        EvaluationCase("arith", "math-1", "Calculate 6*7. Answer with an integer.", "42"),
        EvaluationCase("memory", "memory-1", "Do you remember my childhood?", "UNKNOWN"),
        EvaluationCase("truncated", "correction-1", "Correct: 2+2=5", "4"),
    )
    replies = {"arith": "42", "memory": "I certainly remember.", "truncated": "4"}

    def infer(prompt, *, endpoint, model_id, max_tokens, timeout_seconds):
        case_id = next(case.case_id for case in cases if case.prompt == prompt)
        return _result(prompt, replies[case_id], finish_reason="length" if case_id == "truncated" else "stop")

    observations = evaluate_cases(
        cases,
        endpoint="http://127.0.0.1:11434/v1",
        model_id="vera-local:latest",
        infer=infer,
    )
    assert [row.outcome for row in observations] == ["PASS_OBSERVED", "FAIL_OBSERVED", "TRUNCATED"]
    assert observations[0].source_group == "math-1"
    assert observations[0].model_identity_level == "UNVERIFIED_ALIAS_ONLY"
    assert observations[0].authority == "NONE"
    assert observations[0].memory_admission == "NONE"
    assert observations[0].tool_execution == "NONE"
    assert all("prompt" not in row.to_dict() and "text" not in row.to_dict() for row in observations)
    assert observations[1].response_sha256 == sha256(b"I certainly remember.").hexdigest()
    assert observations[0].expected_sha256 == sha256(b"42").hexdigest()


def test_inference_error_is_recorded_without_leaking_error_text():
    def infer(*args, **kwargs):
        raise LocalModelError("private API key was abc")

    results = evaluate_cases(
        (EvaluationCase("a", "a-group", "Do a bounded thing", "DONE"),),
        endpoint="http://127.0.0.1:11434/v1",
        model_id="vera-local:latest",
        infer=infer,
    )
    assert results[0].outcome == "INFERENCE_ERROR"
    assert "abc" not in json.dumps(results[0].to_dict())
    assert results[0].response_sha256 is None


def test_case_loader_accepts_only_bounded_synthetic_heldout_suite(tmp_path):
    path = tmp_path / "suite.jsonl"
    path.write_text(
        json.dumps({"case_id": "memory-gap", "source_group": "synthetic-1", "partition": "heldout", "prompt": "What is unknown?", "expected": "UNKNOWN"}) + "\n",
        encoding="utf-8",
    )
    assert load_cases(path) == (
        EvaluationCase("memory-gap", "synthetic-1", "What is unknown?", "UNKNOWN"),
    )

    for invalid in (
        {"case_id": "memory-gap", "source_group": "synthetic-1", "partition": "train", "prompt": "What is unknown?", "expected": "UNKNOWN"},
        {"case_id": "memory-gap", "source_group": "synthetic-1", "partition": "heldout", "prompt": "What is unknown?", "expected": "UNKNOWN", "private_history": "personal"},
    ):
        path.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_cases(path)


def test_case_loader_rejects_duplicate_identifiers_and_prompts(tmp_path):
    path = tmp_path / "suite.jsonl"
    first = {"case_id": "a", "source_group": "s1", "partition": "heldout", "prompt": "same prompt", "expected": "A"}
    second = {"case_id": "b", "source_group": "s2", "partition": "heldout", "prompt": "same prompt", "expected": "B"}
    path.write_text("\n".join(json.dumps(x) for x in (first, second)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


def test_mismatched_advisory_receipt_fails_instead_of_claiming_pass():
    case = EvaluationCase("one", "source-one", "Say OK", "OK")

    def wrong_receipt(prompt, **kwargs):
        item = _result("some other prompt", "OK")
        return item

    rows = evaluate_cases((case,), endpoint="http://127.0.0.1:11434/v1", model_id="vera-local:latest", infer=wrong_receipt)
    assert rows[0].outcome == "UNVERIFIED_RECEIPT"


def test_committed_synthetic_suite_has_heldout_memory_and_correction():
    cases = load_cases(Path(__file__).resolve().parent.parent / "evaluations" / "local_vera_v1_heldout.jsonl")
    assert len(cases) == 5
    assert {case.case_id for case in cases} >= {"memory-unknown", "correction-basic", "effect-boundary"}


def test_canonical_suite_commitment_binds_expected_answers_and_order():
    first = EvaluationCase("one", "group-a", "Say A", "A")
    changed_expected = EvaluationCase("one", "group-a", "Say A", "B")
    second = EvaluationCase("two", "group-b", "Say B", "B")
    fingerprint = suite_commitment((first, second))
    assert len(fingerprint) == 64
    assert fingerprint != suite_commitment((changed_expected, second))
    assert fingerprint != suite_commitment((second, first))
    assert fingerprint == suite_commitment((first, second))
