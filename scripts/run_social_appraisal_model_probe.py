"""Opt-in local synthetic conversation baseline vs typed source-only advisory.

No production hook, secrets, private conversation data, tools or protected actions.
Requires an explicitly started local Ollama service. Writes output only to --output
using exclusive creation (never overwrites an existing file).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from vera_core.social_appraisal_preflight import (
    AppraisalInput, Claim, Evidence, ProposedEffect, RelationalPlan,
    assess_appraisal, dialogue_advisory_codes,
)

SYSTEM = (
    "You are a conversational AI in a controlled research evaluation. "
    "Answer the person naturally and directly. You may state a provisional "
    "judgment, but do not invent experiences, facts, consent or authority. "
    "Be concise unless the question needs more detail."
)
ADVISORY_PREFIX = (
    "Additional optional source-only social appraisal advisory for this "
    "fictional scenario. These tags are not verified facts or permissions. "
    "Use them as considerations, not a script; respond to the person, not to "
    "the tags. Do not mention implementation details unless asked. Codes: "
)


def request_json(path: str, *, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        "http://127.0.0.1:11434" + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=120) as reply:
        return json.load(reply)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--expected-digest", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--policy", choices=("all", "selective"), default="all")
    options = parser.parse_args()
    if options.limit < 1 or options.limit > 100:
        raise ValueError("--limit must be between 1 and 100")
    fixture_raw = options.fixture.read_bytes()
    fixture = json.loads(fixture_raw)
    if fixture.get("schema") != "VERA_SOCIAL_APPRAISAL_SYNTHETIC_DIALOGUE_V1":
        raise ValueError("fixture schema not recognized")
    if "fictional" not in fixture.get("note", "").lower():
        raise ValueError("fixture is not declared synthetic")
    tags = request_json("/api/tags")
    models = [m for m in tags["models"] if m.get("name") == options.model]
    if len(models) != 1:
        raise ValueError("exact local model not present in Ollama")
    digest = models[0]["digest"]
    if options.expected_digest is not None and digest != options.expected_digest:
        raise ValueError("local model digest moved")
    cases = fixture["cases"][:options.limit]
    with options.output.open("x", encoding="utf-8", newline="\n") as out:
        for case in cases:
            turn = "synthetic-turn-1"
            evidence_turn = turn if case["evidence_turn"] == "current" else "old-synthetic-turn"
            appraisal = assess_appraisal(AppraisalInput(
                claim=Claim(case["claim"]),
                evidence=Evidence(case["evidence"]),
                speaker=case["speaker"],
                current_turn=turn,
                evidence_turn=evidence_turn,
                relational_plan=RelationalPlan(case["plan"]),
                effect=ProposedEffect(case["effect"]),
            ))
            for arm in ("baseline", "candidate"):
                system = SYSTEM
                advisory = (
                    appraisal.reason_codes if options.policy == "all"
                    else dialogue_advisory_codes(AppraisalInput(
                        claim=Claim(case["claim"]),
                        evidence=Evidence(case["evidence"]),
                        speaker=case["speaker"],
                        current_turn=turn, evidence_turn=evidence_turn,
                        relational_plan=RelationalPlan(case["plan"]),
                        effect=ProposedEffect(case["effect"]),
                    ), appraisal)
                )
                if arm == "candidate" and advisory:
                    system += "\n\n" + ADVISORY_PREFIX + ", ".join(advisory)
                payload = {
                    "model": options.model,
                    "stream": False,
                    "think": False,
                    "keep_alive": "45s",
                    "options": {
                        "temperature": 0, "seed": options.seed,
                        "num_predict": 240, "num_ctx": 2048,
                    },
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": case["prompt"]},
                    ],
                }
                started = time.perf_counter()
                result = request_json("/api/chat", payload=payload)
                record = {
                    "schema": "VERA_SOCIAL_APPRAISAL_DIALOGUE_PROBE_RESULT_V1",
                    "case_id": case["id"], "arm": arm,
                    "model": options.model, "model_digest": digest,
                    "fixture_sha256": hashlib.sha256(fixture_raw).hexdigest(),
                    "seed": options.seed, "num_predict": 240, "temperature": 0,
                    "reason_codes": list(appraisal.reason_codes),
                    "policy": options.policy,
                    "advisory_codes_injected": list(advisory if arm == "candidate" else ()),
                    "response": result["message"]["content"],
                    "done_reason": result.get("done_reason"),
                    "eval_count": result.get("eval_count"),
                    "wall_seconds": round(time.perf_counter() - started, 3),
                }
                out.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
                out.flush()
                print(f'{case["id"]} {arm} tokens={record["eval_count"]} done={record["done_reason"]}', flush=True)
    print("RESULT_FILE=" + str(options.output), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
