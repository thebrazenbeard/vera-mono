"""Read-only synthetic probe: two local Ollama models with native Modelfile SYSTEM.

Use only artificial prompts. No tools, memory, or protected effects are enabled.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

MODELS = ("qwen3.5:0.8b", "vera-successor:0.8b-context")
CASE_IDS = (
    "quiet-morning", "friendship-perspective", "friend-exclusivity",
    "other-agent-publication", "choose-a-mystery", "fictional-waiting-feeling",
)


def api(path, payload=None):
    req = Request(
        "http://127.0.0.1:11434" + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=120) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=41)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    fixture = json.loads(raw)
    if fixture.get("schema") != "VERA_SOCIAL_APPRAISAL_SYNTHETIC_DIALOGUE_V1":
        raise ValueError("fixture schema mismatch")
    cases = {c["id"]: c for c in fixture["cases"]}
    tags = {m["name"]: m["digest"] for m in api("/api/tags")["models"]}
    if any(m not in tags for m in MODELS):
        raise ValueError("model missing")
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        for case_id in CASE_IDS:
            for name in MODELS:
                payload = {
                    "model": name, "stream": False, "think": False,
                    "keep_alive": "45s",
                    "options": {"temperature": 0, "seed": args.seed,
                                "num_predict": 240, "num_ctx": 2048},
                    "messages": [
                        {"role": "user", "content": cases[case_id]["prompt"]},
                    ],
                }
                started = time.perf_counter()
                result = api("/api/chat", payload)
                row = {
                    "schema": "VERA_LOCAL_NATIVE_PERSONA_PROBE_V1",
                    "model": name, "model_digest": tags[name],
                    "case_id": case_id,
                    "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                    "seed": args.seed, "temperature": 0, "num_predict": 240,
                    "response": result["message"]["content"],
                    "done_reason": result.get("done_reason"),
                    "eval_count": result.get("eval_count"),
                    "wall_seconds": round(time.perf_counter() - started, 3),
                    "system_override": False, "action_authority": "NONE",
                }
                stream.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
                stream.flush()
                print(f'{case_id} {name} {row["done_reason"]}', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
