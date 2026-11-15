"""Verify a source-only local multi-turn A/B log against the exact frozen fixture.

This audits experimental provenance/completeness, not social response quality.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path

from run_social_behavior_simple_ab import (
    SCHEMA, messages_for_arm, render_turn,
)
from run_social_multiturn_eval import validate_fixture


def check_results_digest(raw: bytes, expected_results_sha256: str | None) -> dict:
    """Bind log bytes to a separately retained expected hash, when supplied.

    A matching hash detects file modification relative to that expected value.
    It cannot authenticate a model or a host that generated the log.
    """
    actual = hashlib.sha256(raw).hexdigest()
    if expected_results_sha256 is None:
        return {"sha256": actual, "pinned": False}
    if (
        type(expected_results_sha256) is not str
        or len(expected_results_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in expected_results_sha256)
    ):
        raise ValueError("expected_results_sha256 must be lowercase hex SHA256")
    if not hmac.compare_digest(actual, expected_results_sha256):
        raise ValueError("results sha256 mismatch with pinned digest")
    return {"sha256": actual, "pinned": True}


def _strict_json_loads(raw: str | bytes):
    """Reject ambiguous keys and non-standard JSON numeric constants."""
    def distinct_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"non-standard JSON constant: {value}")

    return json.loads(
        raw, object_pairs_hook=distinct_keys, parse_constant=invalid_constant,
    )


def parse_results_bytes(raw: bytes) -> list[dict]:
    """Decode exact JSONL rows without silently overriding duplicate fields."""
    return [
        _strict_json_loads(line)
        for line in raw.decode("utf8").splitlines() if line.strip()
    ]


def audit_records(
    fixture_raw: bytes, rows: list[dict], *, arms: tuple[str, str],
    model: str, digest: str, seed: int,
) -> dict:
    fixture = _strict_json_loads(fixture_raw)
    validate_fixture(fixture)
    if len(arms) != 2 or len(set(arms)) != 2:
        raise ValueError("distinct arms required")
    fixture_sha = hashlib.sha256(fixture_raw).hexdigest()
    expected = {}
    # The generator alternates arm order per case and emits turns sequentially.
    # Exact row order is evidence of expected stream structure, not proof
    # that an external model actually generated the response text.
    expected_order = [
        (case["id"], arm, turn)
        for index, case in enumerate(fixture["cases"])
        for arm in (arms if index % 2 == 0 else tuple(reversed(arms)))
        for turn in (1, 2, 3)
    ]
    for case in fixture["cases"]:
        for arm in arms:
            system_sha = hashlib.sha256(
                messages_for_arm(case, arm)[0]["content"].encode()
            ).hexdigest()
            for turn in (1, 2, 3):
                key = (case["id"], arm, turn)
                expected[key] = {
                    "schema": SCHEMA,
                    "case_id": case["id"],
                    "arm": arm,
                    "turn_index": turn,
                    "seed": seed,
                    "model": model,
                    "model_digest": digest,
                    "fixture_sha256": fixture_sha,
                    "system_sha256": system_sha,
                    "user": case["turns"][turn - 1],
                    "presented_user": render_turn(case, arm, turn),
                    "tool_use": False,
                }
    observed = {}
    observed_order = []
    for n, row in enumerate(rows, start=1):
        if type(row) is not dict:
            raise ValueError(f"invalid row {n}")
        key = (row.get("case_id"), row.get("arm"), row.get("turn_index"))
        if key in observed:
            raise ValueError(f"duplicate record {key}")
        if key not in expected:
            raise ValueError(f"unexpected record {key}")
        unknown = set(row) - (
            set(expected[key]) | {"response", "done_reason", "eval_count"}
        )
        if unknown:
            raise ValueError(f"unexpected fields for {key}: {sorted(unknown)}")
        for field, value in expected[key].items():
            if type(row.get(field)) is not type(value) or row[field] != value:
                raise ValueError(f"{field} mismatch for {key}")
        if not isinstance(row.get("response"), str) or not row["response"].strip():
            raise ValueError(f"response invalid for {key}")
        if row.get("done_reason") not in ("stop", "length"):
            raise ValueError(f"done_reason invalid for {key}")
        if type(row.get("eval_count")) is not int or row["eval_count"] < 0:
            raise ValueError(f"eval_count invalid for {key}")
        observed[key] = row
        observed_order.append(key)
    missing = set(expected) - set(observed)
    if missing:
        raise ValueError(f"missing {len(missing)} records: {sorted(missing)[:3]}")
    if observed_order != expected_order:
        raise ValueError("record order mismatch with sequential generator")
    final = {
        case["id"]: {
            arm: observed[(case["id"], arm, 3)]["response"]
            for arm in arms
        }
        for case in fixture["cases"]
    }
    truncated = sum(row["done_reason"] == "length" for row in observed.values())
    return {
        "records": len(observed),
        "cases": len(fixture["cases"]),
        "complete": len(observed) - truncated,
        "truncated": truncated,
        "model": model,
        "model_digest": digest,
        "seed": seed,
        "arms": list(arms),
        "fixture_sha256": fixture_sha,
        "final_replies": final,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--digest", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--arms", default="base,judgment_v3")
    p.add_argument("--show-final", action="store_true")
    p.add_argument("--expected-results-sha256")
    args = p.parse_args()
    arms = tuple(x.strip() for x in args.arms.split(","))
    raw_results = args.results.read_bytes()
    log_digest = check_results_digest(raw_results, args.expected_results_sha256)
    rows = parse_results_bytes(raw_results)
    report = audit_records(
        args.fixture.read_bytes(), rows, arms=arms, model=args.model,
        digest=args.digest, seed=args.seed,
    )
    report["results_sha256"] = log_digest["sha256"]
    report["result_hash_pinned"] = log_digest["pinned"]
    report["model_response_authenticated"] = False
    if not args.show_final:
        del report["final_replies"]
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
