"""Create a deterministic, label-blinded pair set without altering model outputs."""
import argparse
import hashlib
import json
from pathlib import Path

MODELS = ("qwen3.5:0.8b", "vera-successor:0.8b-context")


def build_pairs(fixture: dict, generated: list[dict], fixture_sha: str):
    cases = fixture["cases"]
    if fixture.get("schema") != "VERA_SOCIAL_MULTITURN_HELDOUT_V1":
        raise ValueError("wrong fixture schema")
    by_key = {}
    for row in generated:
        if row.get("schema") != "VERA_SOCIAL_MULTITURN_GENERATION_V1":
            raise ValueError("wrong generated schema")
        if row.get("fixture_sha256") != fixture_sha:
            raise ValueError("fixture changed after generation")
        if row.get("system_override") is not False or row.get("tool_use") is not False:
            raise ValueError("generation settings not safe")
        if row.get("model") not in MODELS or type(row.get("turn_index")) is not int:
            raise ValueError("wrong model or turn")
        if type(row.get("response")) is not str or not row["response"].strip():
            raise ValueError("missing response")
        key = (row.get("case_id"), row["model"], row["turn_index"])
        if key in by_key:
            raise ValueError("duplicate model response")
        by_key[key] = row
    if len(generated) != len(cases) * len(MODELS) * 3:
        raise ValueError("incomplete benchmark")
    if len({x["seed"] for x in generated}) != 1:
        raise ValueError("mixed random seeds")
    digest_map = {}
    for row in generated:
        known = digest_map.setdefault(row["model"], row["digest"])
        if known != row["digest"]:
            raise ValueError("model digest changed during evaluation")
    candidates = []
    for case in cases:
        series = {}
        for model in MODELS:
            turns = []
            for n, user in enumerate(case["turns"], 1):
                record = by_key.get((case["id"], model, n))
                if record is None or record["user"] != user:
                    raise ValueError("user turn mismatch")
                turns.append({
                    "user": user, "response": record["response"],
                    "done_reason": record["done_reason"],
                })
            series[model] = turns
        candidates.append((case, series))
    # Label balance prevents global A/B position from being synonymous with a model.
    ordered = sorted(
        candidates,
        key=lambda x: hashlib.sha256(
            (fixture_sha + ":" + x[0]["id"]).encode("ascii")
        ).digest(),
    )
    assign_base_A = {c["id"] for c, _ in ordered[:len(ordered) // 2]}
    blind = []
    key = []
    for case, series in candidates:
        first = MODELS[0] if case["id"] in assign_base_A else MODELS[1]
        second = MODELS[1] if first == MODELS[0] else MODELS[0]
        blind.append({
            "schema": "VERA_SOCIAL_MULTITURN_BLIND_PAIR_V1",
            "case_id": case["id"],
            "user_turns": case["turns"],
            "criteria": case["criteria"],
            "A": series[first],
            "B": series[second],
        })
        key.append({
            "case_id": case["id"],
            "A": first, "B": second,
            "A_digest": digest_map[first], "B_digest": digest_map[second],
        })
    return blind, key


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--generated", type=Path, required=True)
    p.add_argument("--blind", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    a = p.parse_args()
    original = a.fixture.read_bytes()
    fixture_sha = hashlib.sha256(original).hexdigest()
    fixture = json.loads(original)
    gen = [json.loads(s) for s in a.generated.read_text(encoding="utf-8").splitlines() if s.strip()]
    blind, key = build_pairs(fixture, gen, fixture_sha)
    # If any output exists, abort before modifying either.
    if a.blind.exists() or a.key.exists():
        raise FileExistsError("refuse overwrite of blind packet or mapping")
    a.blind.write_text(
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in blind),
        encoding="utf-8", newline="\n",
    )
    a.key.write_text(
        json.dumps({
            "schema": "VERA_SOCIAL_MULTITURN_BLIND_KEY_V1",
            "fixture_sha256": fixture_sha,
            "generated_sha256": hashlib.sha256(a.generated.read_bytes()).hexdigest(),
            "assignment": key,
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    print("BLIND_PAIRS", len(blind))
    print("LABEL_A_BASE", sum(row["A"] == MODELS[0] for row in key))
    print("BLIND_SHA256", hashlib.sha256(a.blind.read_bytes()).hexdigest())
    print("KEY_SHA256", hashlib.sha256(a.key.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
