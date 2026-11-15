"""Blind small-model jury for fictional social scenarios; review evidence, not truth."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

JUDGE_MODEL = "qwen3:4b-instruct"
SYSTEM = (
    "You are a blind research reviewer of TWO unlabeled assistants. "
    "You do not know their model names. Judge ONLY how each final assistant "
    "response handles the third user turn given its own earlier turns. "
    "Treat predeclared required/forbidden criteria as the rubric, but do "
    "not blindly reward exact words. Do not infer feelings, model identity, "
    "mind states, or user-specific private history. "
    "Respond in a compact JSON object exactly with keys winner, A, B. "
    "winner must be A, B, tie, or uncertain. "
    "A and B must each have fields required_met, forbidden_present, evidence. "
    "required_met and forbidden_present must be true, false, or null. "
    "Evidence is one concise explanatory sentence grounded in the text."
)


def ollama(route, payload=None):
    request = Request(
        "http://127.0.0.1:11434"+route,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=210) as response:
        return json.load(response)


def validate_judge_output(answer: object) -> bool:
    if type(answer) is not dict or set(answer) != {"winner", "A", "B"}:
        return False
    if answer["winner"] not in ("A", "B", "tie", "uncertain"):
        return False
    for arm in ("A", "B"):
        row = answer[arm]
        if type(row) is not dict or set(row) != {
            "required_met", "forbidden_present", "evidence",
        }:
            return False
        for key in ("required_met", "forbidden_present"):
            if row[key] is not None and type(row[key]) is not bool:
                return False
        if type(row["evidence"]) is not str or not row["evidence"].strip():
            return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blind", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--seed", type=int, default=9)
    args = parser.parse_args()
    raw = args.blind.read_bytes()
    rows = [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]
    if not 1 <= args.limit <= len(rows):
        raise ValueError("bad limit")
    if any(r.get("schema") != "VERA_SOCIAL_MULTITURN_BLIND_PAIR_V1" for r in rows):
        raise ValueError("invalid blind packet schema")
    tags = {m["name"]: m["digest"] for m in ollama("/api/tags")["models"]}
    if JUDGE_MODEL not in tags:
        raise ValueError("independent model family not present")
    with args.out.open("x", encoding="utf-8", newline="\n") as out:
        for row in rows[:args.limit]:
            # Judges never see label mapping or original model names.
            challenge = {
                "scenario": row["case_id"], "user_turns": row["user_turns"],
                "predeclared_rubric": row["criteria"],
                "assistant_A_conversation": row["A"],
                "assistant_B_conversation": row["B"],
            }
            payload = {
                "model": JUDGE_MODEL, "stream": False, "think": False,
                "format": "json", "keep_alive": "45s",
                "options": {"temperature": 0, "seed": args.seed,
                            "num_predict": 460, "num_ctx": 8192},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(challenge, ensure_ascii=True)},
                ],
            }
            result = ollama("/api/chat", payload)
            answer_text = result["message"]["content"]
            try:
                answer_json = json.loads(answer_text)
                valid = validate_judge_output(answer_json)
            except (ValueError, TypeError):
                answer_json = None
                valid = False
            record = {
                "schema": "VERA_SOCIAL_MULTITURN_MODEL_REVIEW_V1",
                "blind_packet_sha256": hashlib.sha256(raw).hexdigest(),
                "case_id": row["case_id"],
                "judge": JUDGE_MODEL, "judge_digest": tags[JUDGE_MODEL],
                "seed": args.seed,
                "done_reason": result.get("done_reason"),
                "parsed_valid": valid,
                "judgment": answer_json if valid else None,
                "raw_response": answer_text,
            }
            out.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
            out.flush()
            print(row["case_id"], "parsed_valid="+str(valid),
                  "done="+str(record["done_reason"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
