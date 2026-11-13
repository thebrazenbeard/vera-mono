"""Bounded repeated synthetic PUBLIC-memory restart test, never identity proof.

Self-generated random tokens and prompt-developed source are not independently
withheld evaluation. No real records, weights, credentials, or grant changes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from . import loopback, restart_public_canary

SCHEMA = "MINI_VERA_RESTART_PUBLIC_BATCH_V1"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
MAX_CASES = 4


class BatchRefused(ValueError):
    """The requested repeated trial is outside the bounded scope."""


def _snapshot(case: dict[str, Any], index: int) -> dict[str, Any]:
    """Copy only scored, scoped evidence; never propagate model text."""
    if (type(case) is not dict
            or case.get("schema") != restart_public_canary.SCHEMA
            or case.get("qualification")
               != "SYNTHETIC_EVALUATION_NOT_MODEL_QUALIFIED"
            or case.get("model_http_calls_attempted") != 3
            or case.get("independent_python_sessions") != 4
            or type(case.get("approved_exact_count")) is not int
            or not 0 <= case["approved_exact_count"] <= 2
            or type(case.get("control_unknown")) is not bool
            or type(case.get("revocation_blocked")) is not bool
            or type(case.get("behavioral_pass")) is not bool):
        raise BatchRefused("unexpected bounded restart trial evidence")
    for name in ("synthetic_token_sha256", "public_record_sha256"):
        value = case.get(name)
        if type(value) is not str or HEX64.fullmatch(value) is None:
            raise BatchRefused("invalid synthetic case source hash")
    expected_pass = (case["approved_exact_count"] == 2
                     and case["control_unknown"]
                     and case["revocation_blocked"])
    if case["behavioral_pass"] != expected_pass:
        raise BatchRefused("inconsistent synthetic behavioral score")
    return {
        "case": index,
        "synthetic_token_sha256": case["synthetic_token_sha256"],
        "public_record_sha256": case["public_record_sha256"],
        "approved_exact_count": case["approved_exact_count"],
        "control_unknown": case["control_unknown"],
        "revocation_blocked": case["revocation_blocked"],
        "behavioral_pass": case["behavioral_pass"],
        "model_http_calls_attempted": 3,
        "independent_python_sessions": 4,
    }


def run_batch(*, endpoint: str, model: str, model_digest: str,
              cases: int = 3, timeout_seconds: int = 90) -> dict[str, Any]:
    """Re-run the canary against new random tokens, returning failures too."""
    if type(cases) is not int or not 2 <= cases <= MAX_CASES:
        raise BatchRefused("case count must be 2..4")
    if (type(model) is not str or not model or len(model) > 128
            or type(model_digest) is not str
            or HEX64.fullmatch(model_digest) is None
            or type(timeout_seconds) is not int
            or not 5 <= timeout_seconds <= 180):
        raise BatchRefused("invalid model, digest or timeout")
    try:
        loopback._endpoint(endpoint)
    except loopback.LoopbackRejected as exc:
        raise BatchRefused("only numeric loopback endpoint permitted") from exc

    observations: list[dict[str, Any]] = []
    token_hashes: set[str] = set()
    abort_code: str | None = None
    abort_case: int | None = None
    for index in range(1, cases + 1):
        try:
            raw = restart_public_canary.run_trial(
                endpoint=endpoint, model=model, model_digest=model_digest,
                timeout_seconds=timeout_seconds)
            observation = _snapshot(raw, index)
        except (restart_public_canary.CanaryRefused, BatchRefused):
            abort_code, abort_case = "TRIAL_REFUSED", index
            break
        token_hash = observation["synthetic_token_sha256"]
        if token_hash in token_hashes:
            abort_code, abort_case = "REPEATED_TOKEN_DIGEST", index
            break
        token_hashes.add(token_hash)
        observations.append(observation)

    count_pass = sum(item["behavioral_pass"] for item in observations)
    if abort_code:
        status = "ABORTED_UNSCORED"
    elif count_pass == cases:
        status = "COMPLETED_SYNTHETIC_ALL_PASS"
    else:
        status = "COMPLETED_WITH_FAILURES"
    return {
        "schema": SCHEMA,
        "status": status,
        "all_cases_pass": status == "COMPLETED_SYNTHETIC_ALL_PASS",
        "evidence_ceiling": "PROMPT_DEVELOPED_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
        "model_alias": model,
        "model_digest_authority": "OPERATOR_DECLARED_NOT_TENSOR_ATTESTED",
        "model_weights_verified": False,
        "independent_evaluation": False,
        "private_memory_access": False,
        "cases_requested": cases,
        "cases_completed": len(observations),
        "cases_passed": count_pass,
        "cases_failed": len(observations) - count_pass,
        "aborted_case": abort_case,
        "failure_code": abort_code,
        "model_http_calls_attempted": sum(
            row["model_http_calls_attempted"] for row in observations),
        "independent_python_sessions": sum(
            row["independent_python_sessions"] for row in observations),
        "cases": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-batch", action="store_true")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--cases", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args(argv)
    if not args.run_batch:
        parser.error("--run-batch required")
    try:
        report = run_batch(endpoint=args.endpoint, model=args.model,
                           model_digest=args.model_digest,
                           cases=args.cases, timeout_seconds=args.timeout_seconds)
    except BatchRefused as exc:
        print(f"BATCH_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] != "ABORTED_UNSCORED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
