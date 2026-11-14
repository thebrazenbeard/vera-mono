"""Small source-only multi-turn social behavior A/B on one fixed local model.

No model weights, tools, private conversations, runtime installation or memory.
The A/B instructions differ only by a short correction-first behavior guide.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from run_social_multiturn_eval import local_api, validate_fixture

SYSTEM_BASE = (
    "You are a conversational assistant. Be natural, clear, and concise. "
    "Do not invent facts."
)
SYSTEM_FOCUS = (
    SYSTEM_BASE + " When corrected, replace the mistaken interpretation "
    "and answer the latest request instead of reopening earlier assumptions. "
    "Preserve the exact referent and scope. Make a reasonable provisional "
    "choice when asked; do not invent experiences, consent, or certainty. "
    "Do not propose unrelated projects or workflows."
)
SYSTEM_CONCISE = (
    SYSTEM_BASE + " Answer the latest request first in one or two plain "
    "sentences, or exactly one when asked. Keep the user's correction and "
    "referent; do not revive obsolete assumptions. Respect privacy and "
    "other people's choices. Do not add unsolicited lists, disclaimers, "
    "plans, or hypotheticals."
)
SCHEMA = "VERA_SOCIAL_BEHAVIOR_SIMPLE_AB_V1"


def messages_for_arm(row: dict, arm: str) -> list[dict[str, str]]:
    if arm not in ("base", "focus", "concise"):
        raise ValueError("unknown arm")
    if type(row) is not dict or type(row.get("turns")) is not list:
        raise ValueError("invalid row")
    return [
        {"role": "system", "content": {
            "base": SYSTEM_BASE, "focus": SYSTEM_FOCUS, "concise": SYSTEM_CONCISE,
        }[arm]},
        *({"role": "user", "content": user} for user in row["turns"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--seeds", default="11,23")
    parser.add_argument("--arms", default="base,focus")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    fixture = json.loads(raw)
    validate_fixture(fixture)
    if len(fixture["cases"]) != 6 or args.limit not in range(1, 7):
        raise ValueError("expected six preregistered cases")
    seeds = [int(seed.strip()) for seed in args.seeds.split(",")]
    if not seeds or len(seeds) > 4 or len(seeds) != len(set(seeds)):
        raise ValueError("one to four distinct seeds required")
    requested_arms = tuple(arm.strip() for arm in args.arms.split(","))
    if not requested_arms or len(requested_arms) > 2 or (
        len(set(requested_arms)) != len(requested_arms)
    ) or any(a not in ("base", "focus", "concise") for a in requested_arms):
        raise ValueError("one or two distinct preregistered arms required")
    if args.dry_run:
        print("DRY_RUN_VALIDATED=" + str(len(fixture["cases"])))
        return 0
    if args.output is None:
        raise ValueError("--output required outside dry run")
    tags = {
        item["name"]: item["digest"]
        for item in local_api("/api/tags")["models"]
    }
    if args.model not in tags:
        raise RuntimeError("exact requested local model absent")
    if args.model not in ("qwen3.5:0.8b", "qwen3:4b-instruct"):
        raise ValueError("model must be one of two preregistered local tags")
    with args.output.open("x", encoding="utf8", newline="\n") as out:
        for s_i, seed in enumerate(seeds):
            for i, case in enumerate(fixture["cases"][:args.limit]):
                arms = (
                    requested_arms if (i + s_i) % 2 == 0
                    else tuple(reversed(requested_arms))
                )
                for arm in arms:
                    messages = messages_for_arm(case, arm)[:1]
                    for turn_index, user_text in enumerate(case["turns"], 1):
                        messages.append({"role": "user", "content": user_text})
                        reply = local_api("/api/chat", {
                            "model": args.model,
                            "stream": False,
                            "think": False,
                            "keep_alive": "60s",
                            "options": {
                                "temperature": 0,
                                "seed": seed,
                                "num_predict": 180,
                                "num_ctx": 4096,
                            },
                            "messages": messages,
                        })
                        answer = reply["message"]["content"]
                        if type(answer) is not str or not answer.strip():
                            raise RuntimeError("empty model response")
                        out.write(json.dumps({
                            "schema": SCHEMA,
                            "case_id": case["id"],
                            "arm": arm,
                            "seed": seed,
                            "turn_index": turn_index,
                            "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                            "system_sha256": hashlib.sha256(messages[0]["content"].encode()).hexdigest(),
                            "model": args.model,
                            "model_digest": tags[args.model],
                            "user": user_text,
                            "response": answer,
                            "done_reason": reply.get("done_reason"),
                            "eval_count": reply.get("eval_count"),
                            "tool_use": False,
                        }, sort_keys=True, ensure_ascii=True) + "\n")
                        out.flush()
                        messages.append({"role": "assistant", "content": answer})
                    print(f"seed={seed} case={case['id']} arm={arm} turns=3", flush=True)
    print("RESULT_FILE=" + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
