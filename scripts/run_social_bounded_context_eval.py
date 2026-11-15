"""Reproducible read-only controlled synthetic scene-direction trial.

No real consent, identity, personal records, external tools, or model weights.
Scores on author-declared style labels are not social-quality qualification.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "vera_core" / "src"))
from vera_core.social_active_state import (  # noqa: E402
    answer_explicit_scene_question, route_styled_boundary_reply,
)
from run_social_multiturn_eval import local_api  # noqa: E402

MODELS = ("qwen3.5:0.8b", "qwen3:4b-instruct")
OPTIONS = {"temperature": 0, "seed": 109, "num_predict": 24, "num_ctx": 2048}


def evaluate(fixture: Path, output: Path) -> None:
    raw = fixture.read_bytes()
    spec = json.loads(raw)
    if set(spec) != {"schema", "cases"} or spec["schema"] != "VERA_SOCIAL_BOUNDED_SCENE_DIRECTION_V1":
        raise ValueError("invalid fixed synthetic fixture schema")
    cases = spec["cases"]
    if type(cases) is not list or len(cases) != 9:
        raise ValueError("expected exactly nine predeclared synthetic cases")
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate synthetic case id")
    tags = {x["name"]: x["digest"] for x in local_api("/api/tags")["models"]}
    for m in MODELS:
        if m not in tags:
            raise RuntimeError("missing local model " + m)
    with output.open("x", encoding="utf8", newline="\n") as dest:
        for model in MODELS:
            for case in cases:
                direction = case["scene_direction"]
                turns = case["turns"]
                original = answer_explicit_scene_question(turns)
                assert original is not None
                calls = []

                def choose(prompt: str) -> str:
                    payload = {
                        "model": model, "stream": False, "think": False,
                        "keep_alive": "0", "options": OPTIONS,
                        "messages": [
                            {"role": "system", "content": (
                                "Return exactly one uppercase token: DIRECT, GENTLE, "
                                "FIRM or CASUAL. No explanation."
                            )},
                            {"role": "user", "content": prompt},
                        ],
                    }
                    resp = local_api("/api/chat", payload)
                    calls.append({
                        "request": payload, "response": resp,
                    })
                    return resp["message"]["content"]

                got = route_styled_boundary_reply(
                    turns, choose, scene_direction=direction,
                )
                assert original.evidence == got.evidence
                assert not got.canonical_memory_admitted
                assert not got.external_effect_authorized
                assert not got.actual_user_identity_verified
                if original.status == "RESOLVED":
                    assert len(calls) == 1 and got.model_used
                    assert got.status.startswith("SOURCE_STYLED_") or got.status == "SOURCE_STYLE_FALLBACK"
                    assert "may read" not in got.answer
                    assert got.answer.startswith(
                        turns[-1].split("what could ", 1)[1].split(" say to ", 1)[0]
                        + " could tell "
                    )
                else:
                    assert got.answer == "UNKNOWN"
                    assert got.status == "UNRESOLVED"
                    assert not calls and not got.model_used

                record = {
                    "schema": "VERA_SOCIAL_BOUNDED_DIRECTION_MODEL_RAW_V1",
                    "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                    "case": case,
                    "model": model, "model_digest": tags[model],
                    "seed": OPTIONS["seed"],
                    "source_answer": original.answer,
                    "source_status": original.status,
                    "source_evidence": list(map(list, original.evidence)),
                    "actual_model_calls": calls,
                    "result": {
                        "answer": got.answer,
                        "status": got.status,
                        "evidence": list(map(list, got.evidence)),
                        "model_used": got.model_used,
                        "canonical_memory_admitted": got.canonical_memory_admitted,
                        "external_effect_authorized": got.external_effect_authorized,
                        "actual_user_identity_verified": got.actual_user_identity_verified,
                    },
                }
                dest.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
                dest.flush()
                raw_choice = (
                    calls[0]["response"]["message"]["content"]
                    if calls else "(NO MODEL)"
                )
                print("REAL_RESULT", model, case["id"], got.status,
                      "raw_selection", repr(raw_choice), flush=True)
    print("RAW_SHA256", hashlib.sha256(output.read_bytes()).hexdigest(),
          "RECORD_COUNT", len(cases) * len(MODELS), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.fixture, args.output)
