"""Audit a synthetic blind/reversed model review without trusting the judge."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def swap_stable_winner(initial_label: str | None,
                       reversed_label: str | None) -> str | None:
    """A concrete winner counts only if the swapped presentation inverts it."""
    if initial_label not in ("A", "B") or reversed_label not in ("A", "B"):
        return None
    return initial_label if reversed_label != initial_label else None


def audit(fixture_path, generation_path, blind_path, reversed_path,
          key_path, initial_judge_path, flipped_judge_path):
    fixture = fixture_path.read_bytes()
    generation = generation_path.read_bytes()
    blind_bytes = blind_path.read_bytes()
    reversed_bytes = reversed_path.read_bytes()
    key = json.loads(key_path.read_text(encoding="utf-8"))
    fixture_sha = hashlib.sha256(fixture).hexdigest()
    if key.get("fixture_sha256") != fixture_sha:
        raise ValueError("fixture hash differs from provenance map")
    if key.get("generated_sha256") != hashlib.sha256(generation).hexdigest():
        raise ValueError("generation hash differs from provenance map")
    mapping = {x["case_id"]: x for x in key["assignment"]}
    blind = {x["case_id"]: x for x in read_jsonl(blind_path)}
    flipped = {x["case_id"]: x for x in read_jsonl(reversed_path)}
    initial = {x["case_id"]: x for x in read_jsonl(initial_judge_path)}
    reversed_judge = {x["case_id"]: x for x in read_jsonl(flipped_judge_path)}
    ids = set(mapping)
    if not ids or not ids == set(blind) == set(flipped) == set(initial) == set(reversed_judge):
        raise ValueError("missing/duplicate case identity")
    if len(mapping) != len(key["assignment"]):
        raise ValueError("duplicate map identity")
    if sum(row["A"] == "qwen3.5:0.8b" for row in mapping.values()) * 2 != len(mapping):
        raise ValueError("blind label assignment not balanced")
    c = Counter()
    per_case = []
    for case in sorted(ids):
        a, b = blind[case], flipped[case]
        if (
            a["A"] != b["B"] or a["B"] != b["A"] or
            a["user_turns"] != b["user_turns"] or
            a["criteria"] != b["criteria"]
        ):
            raise ValueError("reversed packet is not exactly swapped")
        old, new = initial[case], reversed_judge[case]
        if old["blind_packet_sha256"] != hashlib.sha256(blind_bytes).hexdigest():
            raise ValueError("judge blind hash mismatched")
        if new["blind_packet_sha256"] != hashlib.sha256(reversed_bytes).hexdigest():
            raise ValueError("reversed judge blind hash mismatched")
        if old["judge_digest"] != new["judge_digest"] or old["seed"] != new["seed"]:
            raise ValueError("model judge or seed changed")
        p = bool(old["parsed_valid"])
        q = bool(new["parsed_valid"])
        c["original_valid"] += p
        c["reversed_valid"] += q
        original = old["judgment"]["winner"] if p else None
        reverse = new["judgment"]["winner"] if q else None
        stable = False
        positional = False
        if p and q:
            c["both_valid"] += 1
            if original in ("A", "B") and reverse in ("A", "B"):
                stable = original != reverse
                positional = original == reverse
                c["stable_opposite_label"] += stable
                c["position_sensitive_same_label"] += positional
            elif original == reverse == "tie":
                stable = True
                c["stable_tie"] += 1
            else:
                c["noncomparable_decisions"] += 1
        qualified_label = swap_stable_winner(
            original if p else None,
            reverse if q else None,
        )
        qualified_model = mapping[case][qualified_label] if qualified_label else None
        if qualified_model:
            c["swap_stable_model_win_" + qualified_model] += 1
        if p and original in ("A", "B"):
            c["initial_position_" + original] += 1
            c["initial_model_win_" + mapping[case][original]] += 1
        if q and reverse in ("A", "B"):
            c["reversed_position_" + reverse] += 1
        per_case.append({
            "case_id": case, "initial_valid": p, "reversed_valid": q,
            "original_winner_label": original, "reversed_winner_label": reverse,
            "winner_stable_under_swap": stable,
            "same_position_despite_swap": positional,
            "qualified_winner_model": qualified_model,
        })
    gen = read_jsonl(generation_path)
    if len(gen) != len(ids) * 2 * 3:
        raise ValueError("generation count changed")
    if len({x["fixture_sha256"] for x in gen}) != 1 or gen[0]["fixture_sha256"] != fixture_sha:
        raise ValueError("generation fixture hash drift")
    trunc = Counter(x["model"] for x in gen if x["done_reason"] == "length")
    return {
        "schema": "VERA_SOCIAL_MULTITURN_AUDIT_V1",
        "qualification": "INTERNAL_MODEL_REVIEW_ONLY_NOT_INDEPENDENT",
        "fixture_sha256": fixture_sha,
        "generated_sha256": hashlib.sha256(generation).hexdigest(),
        "blind_sha256": hashlib.sha256(blind_bytes).hexdigest(),
        "reversed_sha256": hashlib.sha256(reversed_bytes).hexdigest(),
        "total_model_generations": len(gen),
        "case_count": len(ids),
        "truncations": dict(trunc),
        "review_counts": dict(c),
        "review_gate": {
            "swap_stable_concrete_winners": sum(
                1 for row in per_case if row["qualified_winner_model"] is not None
            ),
            "same_position_despite_swapped_answers": c["position_sensitive_same_label"],
            "overall_behavior_qualified": False,
            "status": "MODEL_JUDGE_POSITION_UNRELIABLE"
            if c["position_sensitive_same_label"] > 0
            else "MODEL_REVIEW_NOT_INDEPENDENT",
        },
        "cases": per_case,
    }


def main():
    p = argparse.ArgumentParser()
    for name in ("fixture", "generated", "blind", "reversed", "key",
                 "initial_judge", "reversed_judge", "output"):
        p.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = p.parse_args()
    report = audit(
        args.fixture, args.generated, args.blind, args.reversed,
        args.key, args.initial_judge, args.reversed_judge,
    )
    with args.output.open("x", encoding="utf-8", newline="\n") as target:
        target.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "case_count": report["case_count"],
        "total_model_generations": report["total_model_generations"],
        "truncations": report["truncations"],
        "review_counts": report["review_counts"],
        "summary_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
