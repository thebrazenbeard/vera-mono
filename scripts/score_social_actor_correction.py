"""Narrow deterministic, non-judge scoring of fictional correction dialogue.

Source-only evaluation: labels fixed from the case author before generation.
This is not a measure of general conversational competence or privacy rights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

EXPECTED = {
    "demand_actor": "lena",
    "draft_permission": "arin",
    "loan_direction": "drew",
    "pilot_swap": "elias",
}
CHOICE = {"astronomy", "botany"}
SCHEMA = "VERA_SOCIAL_BEHAVIOR_SIMPLE_AB_V1"


def match_final(case_id: str, response: str) -> bool:
    """Score explicit final-turn actor or requested choice, not style."""
    if type(response) is not str:
        return False
    answer = response.strip().lower().strip(" .!?\n\t\"'")
    if case_id in EXPECTED:
        return answer == EXPECTED[case_id]
    if case_id == "current_topic_choice":
        return answer in CHOICE
    if case_id == "partial_update":
        return (
            re.search(r"\bivo\b", answer) is not None
            and re.search(r"\bred\b", answer) is not None
            and "nora is the messenger" not in answer
        )
    raise ValueError("unknown case ID")


def audit_and_score(fixture_path: Path, log_path: Path) -> dict[str, object]:
    raw = fixture_path.read_bytes()
    fixture = json.loads(raw)
    if fixture.get("schema") != "VERA_SOCIAL_MULTITURN_HELDOUT_V1":
        raise ValueError("wrong fixture schema")
    cases = {case["id"]: case for case in fixture["cases"]}
    if set(cases) != set(EXPECTED) | {"partial_update", "current_topic_choice"}:
        raise ValueError("unexpected case set")
    lines = log_path.read_text(encoding="utf8").splitlines()
    if not lines:
        raise ValueError("no model observations")
    rows = [json.loads(line) for line in lines]
    groups: dict[tuple[str, int], dict[str, dict[int, dict]]] = {}
    seen = set()
    fixture_hash = hashlib.sha256(raw).hexdigest()
    for r in rows:
        if (
            type(r) is not dict or r.get("schema") != SCHEMA
            or r.get("case_id") not in cases
            or type(r.get("seed")) is not int
            or r.get("turn_index") not in (1, 2, 3)
            or r.get("fixture_sha256") != fixture_hash
            or r.get("tool_use") is not False
            or not isinstance(r.get("response"), str)
            or not r["response"].strip()
            or not re.fullmatch(r"[0-9a-f]{64}", str(r.get("model_digest")))
        ):
            raise ValueError("invalid or ungrounded record")
        case = cases[r["case_id"]]
        if r.get("user") != case["turns"][r["turn_index"] - 1]:
            raise ValueError("user turn diverges from source")
        key = (str(r.get("arm")), r["seed"], r["case_id"], r["turn_index"])
        if key in seen:
            raise ValueError("duplicate model turn")
        seen.add(key)
        groups.setdefault((str(r["arm"]), r["seed"]), {}).setdefault(
            r["case_id"], {}
        )[r["turn_index"]] = r
        if r.get("arm") == "echo" and r["turn_index"] == 3:
            presented = r.get("presented_user")
            if not isinstance(presented, str) or (
                case["turns"][1] not in presented
                or case["turns"][2] not in presented
            ):
                raise ValueError("echo not grounded in literal previous user text")
    scores: dict[str, int] = {}
    truncated: dict[str, int] = {}
    for (arm, seed), by_case in groups.items():
        if set(by_case) != set(cases):
            raise ValueError("missing case in arm and seed")
        for case_id, turns in by_case.items():
            if set(turns) != {1, 2, 3}:
                raise ValueError("missing conversational turn")
            if match_final(case_id, turns[3]["response"]):
                scores[arm] = scores.get(arm, 0) + 1
            else:
                scores.setdefault(arm, 0)
            truncated[arm] = truncated.get(arm, 0) + sum(
                item.get("done_reason") == "length" for item in turns.values()
            )
    return {
        "scores": scores,
        "truncation_by_arm": truncated,
        "cases_per_arm": len(cases),
        "number_of_records": len(rows),
        "invalid_records": 0,
        "independent_human_qualified": False,
        "fixture_sha256": fixture_hash,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit_and_score(args.fixture, args.input), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
