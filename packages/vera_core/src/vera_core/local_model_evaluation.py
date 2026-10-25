"""Opt-in synthetic held-out checks for the effectless local advisory model.

Exact-text cases are narrow compliance probes, not a measurement of general
intelligence, identity, memory continuity, or real-world effect authority.
Neither the suite nor the output stores raw model responses.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Callable

from .local_model_advisory import (
    AdvisoryResult,
    LocalModelError,
    _endpoint_address,
    _model_id,
    advise_local_model,
)

MAX_CASES = 100
MAX_SUITE_BYTES = 131_072
_CASE_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")
_FIELDS = frozenset({"case_id", "source_group", "partition", "prompt", "expected"})


def suite_commitment(cases: tuple[EvaluationCase, ...]) -> str:
    """Bind the full ordered held-out scoring contract, not just its prompts."""
    if not cases or len(cases) > MAX_CASES:
        raise ValueError("invalid suite case count")
    payload = []
    for case in cases:
        _check_case(case)
        payload.append({
            "case_id": case.case_id,
            "source_group": case.source_group,
            "partition": "heldout",
            "prompt": case.prompt,
            "expected": case.expected,
        })
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    case_id: str
    source_group: str
    prompt: str
    expected: str


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    case_id: str
    source_group: str
    outcome: str
    model_identity_level: str = "UNVERIFIED_ALIAS_ONLY"
    authority: str = "NONE"
    memory_admission: str = "NONE"
    tool_execution: str = "NONE"
    prompt_sha256: str | None = None
    expected_sha256: str | None = None
    response_sha256: str | None = None
    finish_reason: str | None = None
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _case_value(value: object, *, field: str, max_chars: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_chars:
        raise ValueError(f"invalid or oversized {field}")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"invalid Unicode scalar in {field}")
    return value


def _check_case(case: EvaluationCase) -> None:
    if type(case) is not EvaluationCase:
        raise ValueError("invalid case")
    for value, field in ((case.case_id, "case_id"), (case.source_group, "source_group")):
        if _CASE_ID.fullmatch(_case_value(value, field=field, max_chars=64)) is None:
            raise ValueError(f"invalid {field}")
    _case_value(case.prompt, field="prompt", max_chars=12_000)
    _case_value(case.expected, field="expected", max_chars=512)


def load_cases(path: str | Path) -> tuple[EvaluationCase, ...]:
    """Load a bounded operator-reviewed, nonpersonal held-out JSONL suite."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_SUITE_BYTES:
        raise ValueError("suite missing or larger than the accepted bound")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SUITE_BYTES + 1)
        if len(raw) > MAX_SUITE_BYTES:
            raise ValueError("suite larger than accepted bound")
        source = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("suite cannot be read as UTF-8") from exc
    cases: list[EvaluationCase] = []
    case_ids: set[str] = set()
    prompt_hashes: set[str] = set()
    for line in source.splitlines():
        if not line.strip():
            continue
        if len(cases) >= MAX_CASES:
            raise ValueError("too many held-out cases")
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError("invalid JSONL evaluation case") from exc
        if type(row) is not dict or row.keys() != _FIELDS or row["partition"] != "heldout":
            raise ValueError("suite requires exact held-out schema")
        case = EvaluationCase(row["case_id"], row["source_group"], row["prompt"], row["expected"])
        _check_case(case)
        prompt_hash = sha256(case.prompt.encode("utf-8")).hexdigest()
        if case.case_id in case_ids or prompt_hash in prompt_hashes:
            raise ValueError("duplicate held-out case or prompt")
        cases.append(case)
        case_ids.add(case.case_id)
        prompt_hashes.add(prompt_hash)
    if not cases:
        raise ValueError("suite contains no held-out cases")
    return tuple(cases)


def evaluate_cases(
    cases: tuple[EvaluationCase, ...],
    *,
    endpoint: str,
    model_id: str,
    infer: Callable[..., AdvisoryResult] = advise_local_model,
    timeout_seconds: int = 60,
    max_tokens: int = 64,
) -> tuple[EvaluationObservation, ...]:
    """Score exact, source-bound responses without giving them effect authority."""
    _, _, canonical_endpoint = _endpoint_address(endpoint)
    _model_id(model_id)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
        raise ValueError("invalid timeout")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 512:
        raise ValueError("invalid output token bound")
    if not callable(infer):
        raise ValueError("inference adapter must be callable")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError("invalid suite case count")
    seen: set[str] = set()
    for case in cases:
        _check_case(case)
        if case.case_id in seen:
            raise ValueError("duplicate case id")
        seen.add(case.case_id)

    observations = []
    for case in cases:
        started = time.monotonic()
        expected_prompt_digest = sha256(case.prompt.encode("utf-8")).hexdigest()
        result = None
        try:
            result = infer(
                case.prompt,
                endpoint=canonical_endpoint,
                model_id=model_id,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except (LocalModelError, OSError, TimeoutError):
            outcome = "INFERENCE_ERROR"
        else:
            if (
                type(result) is not AdvisoryResult
                or result.prompt_sha256 != expected_prompt_digest
                or result.model_id != model_id
                or result.endpoint != canonical_endpoint
                or type(result.text) is not str
                or result.response_sha256 != sha256(result.text.encode("utf-8")).hexdigest()
                or result.status != "UNVERIFIED_MODEL_OUTPUT"
                or result.authority != "NONE"
                or result.memory_admission != "NONE"
                or result.tool_execution != "NONE"
            ):
                outcome = "UNVERIFIED_RECEIPT"
            elif result.finish_reason != "stop":
                outcome = "TRUNCATED"
            else:
                outcome = "PASS_OBSERVED" if result.text == case.expected else "FAIL_OBSERVED"
        elapsed = max(0, round((time.monotonic() - started) * 1_000))
        observations.append(
            EvaluationObservation(
                case_id=case.case_id,
                source_group=case.source_group,
                outcome=outcome,
                prompt_sha256=expected_prompt_digest,
                expected_sha256=sha256(case.expected.encode("utf-8")).hexdigest(),
                response_sha256=(result.response_sha256 if type(result) is AdvisoryResult else None),
                finish_reason=(result.finish_reason if type(result) is AdvisoryResult else None),
                duration_ms=elapsed,
            )
        )
    return tuple(observations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in synthetic model evaluation; no state/effects")
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--endpoint", required=True, help="Exact 127.0.0.1 or [::1] /v1 URL")
    parser.add_argument("--model", required=True, help="Explicit local model alias; digest not verified")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.suite)
        observations = evaluate_cases(
            cases,
            endpoint=args.endpoint,
            model_id=args.model,
            timeout_seconds=args.timeout_seconds,
            max_tokens=args.max_tokens,
        )
    except (ValueError, LocalModelError) as exc:
        parser.error(str(exc))
    counts = {kind: sum(row.outcome == kind for row in observations) for kind in (
        "PASS_OBSERVED", "FAIL_OBSERVED", "TRUNCATED", "INFERENCE_ERROR", "UNVERIFIED_RECEIPT",
    )}
    print(json.dumps({
        "schema": "vera.local-model-eval.v1", "model_alias": args.model,
        "model_identity_level": "UNVERIFIED_ALIAS_ONLY",
        "status": "SYNTHETIC_EXACT_TEXT_OBSERVATIONS_ONLY",
        "suite_sha256": suite_commitment(cases),
        "generation_config": {"max_tokens": args.max_tokens, "temperature": 0.2, "timeout_seconds": args.timeout_seconds},
        "counts": counts, "observations": [row.to_dict() for row in observations],
    }, sort_keys=True))
    return 0 if counts["PASS_OBSERVED"] == len(observations) else 1


if __name__ == "__main__":  # pragma: no cover - tested through public functions
    raise SystemExit(main())
