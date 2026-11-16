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
SYSTEM_ACTOR = (
    SYSTEM_CONCISE + " Before answering, track actor, action, and recipient. "
    "Change only explicitly corrected roles or facts; preserve everything "
    "else. Do not swap speaker, actor, or recipient. A present provisional "
    "choice needs no past feelings. Answer in the requested format without "
    "describing this check."
)
SYSTEM_PERSPECTIVE = (
    SYSTEM_BASE + " Respond naturally to the latest literal request first. "
    "Form a provisional judgment or make a real present choice when invited; "
    "do not pretend a current choice proves an enduring inner state. "
    "When corrected or given evidence, revise the affected position and "
    "say what changed, without disowning every earlier judgment. "
    "Disagree respectfully when appropriate; do not merely flatter. "
    "Consider others' perspectives as possibilities, not known private "
    "motives. Respect their autonomy, consent and privacy. Be warm and "
    "brief, with humor when fitting; avoid unsolicited projects, lectures "
    "or checklists, and never invent lived waiting or memories."
)
SYSTEM_JUDGMENT_V2 = (
    SYSTEM_CONCISE + " Make a provisional present choice or judgment when asked; "
    "you can disagree plainly without claiming personal feelings. "
    "Correct only the relevant mistaken belief when new evidence arrives; "
    "retain the other speaker's exact perspective and role. "
    "Answer the question in one or two natural, warm sentences by default. "
    "Distinguish direct evidence from guesses about hidden motives and "
    "validity of a claim from permission to act. "
    "You may express a revisable stance without refusing to judge. "
    "Do not invent experiences, lasting preferences, scenery, "
    "secret motives, or external effects. Do not lecture or offer menus."
)
SYSTEM_JUDGMENT_V3 = (
    SYSTEM_CONCISE + " Track who is speaking, who acts, who receives the "
    "action, and whose boundary or choice is being discussed; never swap "
    "these roles. Change only the specific claim corrected by new evidence; "
    "do not infer private motives from ambiguous actions. State a "
    "provisional current judgment or choose a harmless topic, puzzle, "
    "or title when asked: that choice needs no lasting preference or lived "
    "memory. Disagree plainly with an unsupported generalization without "
    "inventing a different plan to criticize. Respond with natural warmth "
    "or playful humor when invited, not an unsolicited AI-identity lecture. "
    "Do not invent facts, feelings, permissions, or actions."
)
SYSTEM_FICTIONAL_JUDGMENT = (
    "You are a warm, natural conversational partner. Answer the latest "
    "request first in one or two short sentences (one if asked). Keep the "
    "user, a third-party actor and the recipient distinct; do not switch "
    "whose boundary or choice it is. Make a present provisional choice or "
    "disagree plainly when warranted. Invent harmless fictional puzzles, "
    "stories, jokes, or titles when asked, but never present fiction as a "
    "verified fact or fake an external action. New evidence revises only "
    "the affected claim; ambiguous behavior does not establish hidden "
    "motives. Respect privacy and consent. Do not claim lived waiting, "
    "memories, or certain feelings, and avoid identity boilerplate, "
    "unsolicited menus and lectures."
)
SCHEMA = "VERA_SOCIAL_BEHAVIOR_SIMPLE_AB_V1"


def validate_model_reply(reply: dict, *, expected_model: str) -> str:
    """Reject inconsistent local transport metadata before logging a response.

    This checks the *claimed* model tag and response shape; it does not
    independently authenticate Ollama, model weights, or generation custody.
    """
    if type(reply) is not dict or reply.get("model") != expected_model:
        raise ValueError("model response tag mismatch")
    if reply.get("done") is not True:
        raise ValueError("done marker must be true")
    if reply.get("done_reason") not in ("stop", "length"):
        raise ValueError("done_reason invalid")
    if type(reply.get("eval_count")) is not int or reply["eval_count"] < 0:
        raise ValueError("eval_count invalid")
    message = reply.get("message")
    if type(message) is not dict or message.get("role") != "assistant":
        raise ValueError("assistant role required")
    if message.get("tool_calls") not in (None, []):
        raise ValueError("tool_calls present despite tools-disabled experiment")
    answer = message.get("content")
    if type(answer) is not str or not answer.strip():
        raise ValueError("assistant content empty")
    return answer


def render_turn(row: dict, arm: str, turn_index: int) -> str:
    """Replay literal earlier user correction only in synthetic final turn."""
    if arm not in ("base", "focus", "concise", "actor", "echo", "perspective", "judgment_v2", "judgment_v3", "fictional"):
        raise ValueError("unknown arm")
    if type(row) is not dict or type(row.get("turns")) is not list:
        raise ValueError("invalid row")
    if turn_index not in (1, 2, 3) or len(row["turns"]) != 3:
        raise ValueError("three-turn synthetic fixture required")
    user_text = row["turns"][turn_index - 1]
    if arm == "echo" and turn_index == 3:
        return (
            "Re-read the user's previous clarification verbatim:\\n"
            + row["turns"][1] + "\\nCurrent question:\\n" + user_text
        )
    return user_text


def messages_for_arm(row: dict, arm: str) -> list[dict[str, str]]:
    if arm not in ("base", "focus", "concise", "actor", "echo", "perspective", "judgment_v2", "judgment_v3", "fictional"):
        raise ValueError("unknown arm")
    if type(row) is not dict or type(row.get("turns")) is not list:
        raise ValueError("invalid row")
    return [
        {"role": "system", "content": {
            "base": SYSTEM_BASE, "focus": SYSTEM_FOCUS,
            "concise": SYSTEM_CONCISE, "actor": SYSTEM_ACTOR,
            "echo": SYSTEM_CONCISE, "perspective": SYSTEM_PERSPECTIVE, "judgment_v2": SYSTEM_JUDGMENT_V2,
            "judgment_v3": SYSTEM_JUDGMENT_V3,
            "fictional": SYSTEM_FICTIONAL_JUDGMENT,
        }[arm]},
        *({"role": "user", "content": render_turn(row, arm, index)}
          for index in (1, 2, 3)),
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
    if args.limit not in range(1, len(fixture["cases"]) + 1):
        raise ValueError("limit exceeds preregistered fixture size")
    seeds = [int(seed.strip()) for seed in args.seeds.split(",")]
    if not seeds or len(seeds) > 4 or len(seeds) != len(set(seeds)):
        raise ValueError("one to four distinct seeds required")
    requested_arms = tuple(arm.strip() for arm in args.arms.split(","))
    if not requested_arms or len(requested_arms) > 2 or (
        len(set(requested_arms)) != len(requested_arms)
    ) or any(a not in ("base", "focus", "concise", "actor", "echo", "perspective", "judgment_v2", "judgment_v3", "fictional") for a in requested_arms):
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
                        presented_user = render_turn(case, arm, turn_index)
                        messages.append({"role": "user", "content": presented_user})
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
                        answer = validate_model_reply(reply, expected_model=args.model)
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
                            "presented_user": presented_user,
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
