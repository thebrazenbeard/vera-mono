"""Run the bounded source-backed scene answerer on synthetic fixture data.

No model, no internet, no private history, no writes. Not a general NLU engine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_social_active_state_eval import validate_fixture, score_answer
from vera_core.social_active_state import answer_explicit_scene_question


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf8"))
    validate_fixture(fixture)
    total_correct = 0
    unsupported = 0
    for case in fixture["cases"]:
        result = answer_explicit_scene_question(case["turns"])
        if result is None:
            # The historical fixture's question about a *specific ship*
            # lacks an actual actor-to-ship source assertion. Preserve that
            # unsupported case rather than score a fabricated relationship.
            unsupported += 1
            print(json.dumps({
                "case_id":case["id"], "answer":None,
                "status":"UNSUPPORTED_SCOPE", "correct":None, "evidence":[],
                "external_effect_authorized":False,
            }, sort_keys=True))
            continue
        correct = score_answer(case["expected"], result.answer)
        total_correct += int(correct)
        print(json.dumps({
            "case_id":case["id"], "answer":result.answer,
            "status":result.status, "correct":correct,
            "evidence":[{"quote":q, "user_turn":n} for q,n in result.evidence],
            "external_effect_authorized":result.external_effect_authorized,
        }, sort_keys=True, ensure_ascii=True))
    print(json.dumps({
        "suite":"SOURCE_ONLY_SYNTHETIC_EXPLICIT_FACTS",
        "correct":total_correct, "total":len(fixture["cases"]),
        "supported":len(fixture["cases"])-unsupported,
        "unsupported":unsupported,
        "independent_review":False, "live_memory_admission":False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
