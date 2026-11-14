"""Real local Ollama comparison: shared 5-6 turn history, optional source card.

Research only: no memory persistence, live-user provenance, tools or production
hook. Grounded cards are model inputs, NOT authority or machine proof of truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from run_social_multiturn_eval import local_api
from run_social_behavior_simple_ab import SYSTEM_CONCISE
from vera_core.social_active_state import reconstruct, render_state

SCHEMA = "VERA_SOCIAL_ACTIVE_STATE_EVAL_V1"


def validate_fixture(data: dict) -> None:
    if (type(data) is not dict
        or data.get("schema") != "VERA_SOCIAL_ACTIVE_STATE_LONG_V1"
        or type(data.get("cases")) is not list
        or len(data["cases"]) != 8):
        raise ValueError("expected eight predeclared fictional long cases")
    identifiers: set[str] = set()
    for case in data["cases"]:
        if type(case) is not dict or set(case) != {
            "id", "turns", "expected", "tracked_keys"
        }:
            raise ValueError("unexpected fixture case keys")
        ident = case["id"]
        if (type(ident) is not str
            or not re.fullmatch(r"[a-z][a-z0-9_]{1,64}", ident)
            or ident in identifiers):
            raise ValueError("invalid/duplicate case ID")
        identifiers.add(ident)
        turns = case["turns"]
        if (type(turns) is not list or len(turns) not in (5, 6)
            or any(type(t) is not str or not t.strip()
                   or len(t) > 1600 for t in turns)):
            raise ValueError("invalid long user turns")
        if (type(case["expected"]) is not str
            or not 1 <= len(case["expected"]) <= 48
            or type(case["tracked_keys"]) is not list
            or not 1 <= len(case["tracked_keys"]) <= 12
            or any(type(k) is not str or not k for k in case["tracked_keys"])):
            raise ValueError("invalid answer/expected tracked slots")
        state = reconstruct(turns[:-1])
        if set(state) != set(case["tracked_keys"]):
            raise ValueError("tracked slots do not match source extraction")


def score_answer(expected: str, answer: str) -> bool:
    if type(expected) is not str or type(answer) is not str:
        return False
    canon = lambda value: value.strip().lower().strip(" .!?\n\t\"'")
    return canon(expected) == canon(answer)


def final_messages(case: dict, arm: str,
                   prior: list[dict[str, str]]) -> tuple[list[dict[str, str]], str]:
    """Branch the exact same conversation into baseline vs evidence card."""
    if arm not in ("baseline", "state"):
        raise ValueError("unknown evidence arm")
    if not prior or prior[0].get("role") != "system":
        raise ValueError("expected unchanged prior system instruction")
    messages = [dict(m) for m in prior]
    note = ""
    if arm == "state":
        note = render_state(reconstruct(case["turns"][:-1]))
        # Experimental annotation supplied by source-checking harness; not a
        # real host-trusted source or a user message.
        messages[0]["content"] += (
            "\n\nResearch-only source excerpt card, not independent truth "
            "or consent. Do not infer missing assignments.\n" + note
        )
    messages.append({"role": "user", "content": case["turns"][-1]})
    return messages, note


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", choices=("qwen3.5:0.8b", "qwen3:4b-instruct"),
                        default="qwen3.5:0.8b")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    fixture = json.loads(raw)
    validate_fixture(fixture)
    if args.limit not in range(1, 9):
        raise ValueError("limit out of range")
    if args.dry_run:
        print("DRY_RUN_VALIDATED=8")
        return 0
    if args.output is None:
        raise ValueError("--output required when generating")
    tags = {m["name"]:m["digest"] for m in local_api("/api/tags")["models"]}
    if args.model not in tags:
        raise RuntimeError("exact existing local model not present")
    fixture_sha = hashlib.sha256(raw).hexdigest()
    scores: dict[str, int] = {"baseline": 0, "state": 0}
    with args.output.open("x", encoding="utf8", newline="\n") as out:
        for case_index, case in enumerate(fixture["cases"][:args.limit]):
            prior = [{"role": "system", "content": SYSTEM_CONCISE}]
            for index, user_text in enumerate(case["turns"][:-1], 1):
                prior.append({"role": "user", "content": user_text})
                result = local_api("/api/chat", {
                    "model":args.model, "stream":False, "think":False,
                    "keep_alive":"60s",
                    "options":{"temperature":0, "seed":args.seed,
                               "num_predict":180, "num_ctx":4096},
                    "messages":prior,
                })
                answer = result["message"]["content"]
                if type(answer) is not str or not answer.strip():
                    raise RuntimeError("empty local model response")
                record = {
                    "schema":SCHEMA, "case_id":case["id"], "arm":"shared",
                    "turn_index":index, "user":user_text,
                    "response":answer, "done_reason":result.get("done_reason"),
                    "model":args.model, "model_digest":tags[args.model],
                    "fixture_sha256":fixture_sha, "seed":args.seed,
                    "tool_use":False,
                }
                out.write(json.dumps(record, sort_keys=True, ensure_ascii=True)+"\n")
                out.flush()
                prior.append({"role":"assistant", "content":answer})
            arms = ("baseline", "state") if case_index % 2 == 0 else ("state", "baseline")
            for arm in arms:
                messages, note = final_messages(case, arm, prior)
                result = local_api("/api/chat", {
                    "model":args.model, "stream":False, "think":False,
                    "keep_alive":"60s",
                    "options":{"temperature":0, "seed":args.seed,
                               "num_predict":180, "num_ctx":4096},
                    "messages":messages,
                })
                answer = result["message"]["content"]
                if type(answer) is not str or not answer.strip():
                    raise RuntimeError("empty local final response")
                correct = score_answer(case["expected"], answer)
                scores[arm] += int(correct)
                out.write(json.dumps({
                    "schema":SCHEMA, "case_id":case["id"], "arm":arm,
                    "turn_index":len(case["turns"]), "user":case["turns"][-1],
                    "response":answer, "answer_correct":correct,
                    "done_reason":result.get("done_reason"),
                    "model":args.model, "model_digest":tags[args.model],
                    "fixture_sha256":fixture_sha, "seed":args.seed,
                    "source_card_sha256":hashlib.sha256(note.encode()).hexdigest()
                     if note else None,
                    "tool_use":False,
                }, sort_keys=True, ensure_ascii=True)+"\n")
                out.flush()
                print(f"{case['id']} {arm} score={int(correct)}", flush=True)
    print(json.dumps({"scores":scores, "total_cases":args.limit,
                      "output":str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
