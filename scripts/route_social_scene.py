"""Read-only local Ollama scene router; JSON on stdin, one JSON reply on stdout.

Research-facing entrypoint only. Does not install in Vera, store user turns,
grant authority, authenticate real users or transmit to a remote provider.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for package in sorted((ROOT / "packages").iterdir()):
    source = package / "src"
    if source.is_dir():
        sys.path.insert(0, str(source))

from vera_core.social_active_state import (  # noqa: E402
    reconstruct, render_state, route_scene_reply,
)
from run_social_multiturn_eval import local_api  # noqa: E402

MAX_STDIN_BYTES = 70_000
SCENE_SYSTEM = (
    "This is fictional scene dialogue. Treat statements as user-supplied "
    "story claims, not verified real-world facts or authorization. "
    "Respect explicit corrections and ambiguity; do not invent missing "
    "actor-to-vessel relationships or personal intentions."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", choices=("qwen3.5:0.8b", "qwen3:4b-instruct"),
        default="qwen3.5:0.8b",
    )
    parser.add_argument("--seed", type=int, default=41)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise ValueError("input exceeds bounded JSON size")
    payload = json.loads(raw)
    if type(payload) is not dict or set(payload) != {"user_turns"}:
        raise ValueError("input must contain exactly user_turns")
    turns = payload["user_turns"]

    def generate() -> str:
        card = render_state(reconstruct(turns[:-1])) if len(turns) > 1 else ""
        system = SCENE_SYSTEM + ("\n\n" + card if card else "")
        messages = [{"role": "system", "content": system}]
        messages.extend({"role": "user", "content": t} for t in turns)
        response = local_api("/api/chat", {
            "model": args.model, "stream": False, "think": False,
            "keep_alive": "0", "options": {
                "temperature": 0, "seed": args.seed,
                "num_predict": 160, "num_ctx": 4096,
            },
            "messages": messages,
        })
        return response["message"]["content"]

    response = route_scene_reply(turns, generate)
    print(json.dumps({
        "answer": response.answer,
        "status": response.status,
        "evidence": [
            {"quote": quote, "user_turn": turn}
            for quote, turn in response.evidence
        ],
        "model_used": response.model_used,
        "model": args.model if response.model_used else None,
        "canonical_memory_admitted": response.canonical_memory_admitted,
        "external_effect_authorized": response.external_effect_authorized,
        "actual_user_identity_verified": response.actual_user_identity_verified,
        "scope": "READ_ONLY_FICTIONAL_SCENE",
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
