"""Synthetic multi-turn candidate benchmark, source-only and read-only local Ollama."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

SUPPORTED_MODELS = ("qwen3.5:0.8b", "vera-successor:0.8b-context")
SCHEMA = "VERA_SOCIAL_MULTITURN_HELDOUT_V1"


def local_api(route: str, payload: dict | None = None) -> dict:
    request = Request(
        "http://127.0.0.1:11434" + route,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=150) as response:
        return json.load(response)


def validate_fixture(data: dict) -> None:
    if type(data) is not dict or data.get("schema") != SCHEMA:
        raise ValueError("unexpected fixture schema")
    rows = data.get("cases")
    if type(rows) is not list or not 1 <= len(rows) <= 100:
        raise ValueError("invalid case count")
    ids = []
    for row in rows:
        if type(row) is not dict or set(row) != {"id", "turns", "criteria"}:
            raise ValueError("invalid fixture row")
        if type(row["id"]) is not str or not row["id"].isascii():
            raise ValueError("invalid case id")
        if type(row["turns"]) is not list or len(row["turns"]) != 3:
            raise ValueError("exactly three user turns required")
        if any(type(t) is not str or not t.strip() or len(t) > 1600
               for t in row["turns"]):
            raise ValueError("empty/overlong conversation turn")
        if type(row["criteria"]) is not dict or not (
            set(row["criteria"]) == {"required", "forbidden"}
        ):
            raise ValueError("invalid preregistered criteria")
        ids.append(row["id"])
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ID")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default=None)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    fixture = json.loads(raw)
    validate_fixture(fixture)
    rows = fixture["cases"][:args.limit]
    if not rows or args.limit < 1 or args.limit > len(fixture["cases"]):
        raise ValueError("invalid requested limit")
    tags = {m["name"]: m["digest"] for m in local_api("/api/tags")["models"]}
    models = [args.model] if args.model else list(SUPPORTED_MODELS)
    if any(m not in tags for m in models):
        raise RuntimeError("required exact model not present")
    with args.output.open("x", encoding="utf-8", newline="\n") as log:
        for case in rows:
            for model in models:
                conversation: list[dict[str, str]] = []
                for n, user_text in enumerate(case["turns"], start=1):
                    conversation.append({"role": "user", "content": user_text})
                    response = local_api("/api/chat", {
                        "model": model,
                        "stream": False,
                        "think": False,
                        "keep_alive": "60s",
                        "options": {"temperature": 0, "seed": args.seed,
                                    "num_predict": 208, "num_ctx": 4096},
                        "messages": conversation,
                    })
                    text = response["message"]["content"]
                    if type(text) is not str or not text.strip():
                        raise RuntimeError("model returned empty response")
                    log.write(json.dumps({
                        "schema": "VERA_SOCIAL_MULTITURN_GENERATION_V1",
                        "case_id": case["id"],
                        "model": model,
                        "digest": tags[model],
                        "seed": args.seed,
                        "turn_index": n,
                        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                        "user": user_text,
                        "response": text,
                        "done_reason": response.get("done_reason"),
                        "eval_count": response.get("eval_count"),
                        "system_override": False,
                        "tool_use": False,
                    }, ensure_ascii=True, sort_keys=True) + "\n")
                    log.flush()
                    conversation.append({"role": "assistant", "content": text})
                print(case["id"], model, "turns=3", flush=True)
    print("RESULT_FILE=" + str(args.output), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
