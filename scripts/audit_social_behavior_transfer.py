"""Verify a source-only local multi-turn A/B log against the exact frozen fixture.

This audits experimental provenance/completeness, not social response quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_social_behavior_simple_ab import (
    SCHEMA, messages_for_arm, render_turn,
)
from run_social_multiturn_eval import validate_fixture


def audit_records(
    fixture_raw: bytes, rows: list[dict], *, arms: tuple[str, str],
    model: str, digest: str, seed: int,
) -> dict:
    fixture = json.loads(fixture_raw)
    validate_fixture(fixture)
    if len(arms) != 2 or len(set(arms)) != 2:
        raise ValueError("distinct arms required")
    fixture_sha = hashlib.sha256(fixture_raw).hexdigest()
    expected = {}
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
    for n, row in enumerate(rows, start=1):
        if type(row) is not dict:
            raise ValueError(f"invalid row {n}")
        key = (row.get("case_id"), row.get("arm"), row.get("turn_index"))
        if key in observed:
            raise ValueError(f"duplicate record {key}")
        if key not in expected:
            raise ValueError(f"unexpected record {key}")
        for field, value in expected[key].items():
            if type(row.get(field)) is not type(value) or row[field] != value:
                raise ValueError(f"{field} mismatch for {key}")
        if not isinstance(row.get("response"), str) or not row["response"].strip():
            raise ValueError(f"response invalid for {key}")
        if row.get("done_reason") not in ("stop", "length"):
            raise ValueError(f"done_reason invalid for {key}")
        if not isinstance(row.get("eval_count"), int):
            raise ValueError(f"eval_count invalid for {key}")
        observed[key] = row
    missing = set(expected) - set(observed)
    if missing:
        raise ValueError(f"missing {len(missing)} records: {sorted(missing)[:3]}")
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
    args = p.parse_args()
    arms = tuple(x.strip() for x in args.arms.split(","))
    rows = [
        json.loads(line) for line in args.results.read_text(
            encoding="utf8"
        ).splitlines() if line.strip()
    ]
    report = audit_records(
        args.fixture.read_bytes(), rows, arms=arms, model=args.model,
        digest=args.digest, seed=args.seed,
    )
    if not args.show_final:
        del report["final_replies"]
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
