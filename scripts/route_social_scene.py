"""Read-only local Ollama scene router; JSON on stdin, one JSON reply on stdout.

Research-facing entrypoint only. Does not install in Vera, store user turns,
grant authority, authenticate real users or transmit to a remote provider.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import importlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
for package in sorted((ROOT / "packages").iterdir()):
    source = package / "src"
    if source.is_dir():
        sys.path.insert(0, str(source))

from vera_core.social_active_state import (  # noqa: E402
    reconstruct, render_state, route_scene_reply,
    route_styled_boundary_reply,
)
from run_social_multiturn_eval import local_api  # noqa: E402

MAX_STDIN_BYTES = 70_000
SCENE_SYSTEM = (
    "This is fictional scene dialogue. Treat statements as user-supplied "
    "story claims, not verified real-world facts or authorization. "
    "Respect explicit corrections and ambiguity; do not invent missing "
    "actor-to-vessel relationships or personal intentions."
)


PINNED_PERSONIFICATION_HEAD = "8fe35557e9a6c7b99c8f50a532e20c8f8c43f4cc"


def plan_from_personification_checkout(
    checkout: Path, *, actor_id: str, subject_id: str, request: str,
    interaction_kind: str, preferred_register: str, allow_humor: bool,
):
    """Opt-in source-only donor, guarded to a reviewed, clean candidate HEAD."""
    root = checkout.resolve(strict=True)
    entrypoint = root / "src" / "personification" / "__init__.py"
    if not entrypoint.is_file():
        raise ValueError("Personification src checkout is required")
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if head != PINNED_PERSONIFICATION_HEAD:
        raise ValueError("Personification checkout is not the pinned reviewed source")
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("Personification source has local modifications")
    source = str(root / "src")
    sys.path.insert(0, source)
    try:
        donor = importlib.import_module("personification")
        if Path(donor.__file__).resolve() != entrypoint.resolve():
            raise ValueError("Personification import did not resolve to pinned checkout")
        profile = donor.ActorProfile(
            actor_id, donor.Register(preferred_register), allow_humor
        )
        interaction = donor.Interaction(
            actor_id, subject_id, request, donor.InteractionKind(interaction_kind)
        )
        return donor.plan_interaction(profile, interaction)
    finally:
        sys.path.remove(source)


def note_from_personification_plan(plan, literal_request: str) -> tuple[str, dict]:
    """Reject changed target/authority; pass only bounded style guidance."""
    register = getattr(getattr(plan, "register", None), "value", None)
    humor = getattr(plan, "humor_allowed", None)
    if (
        type(literal_request) is not str
        or getattr(plan, "answer_target", None) != literal_request
        or getattr(plan, "answer_literal_request_first", None) is not True
        or getattr(plan, "permission_to_act", None) is not False
        or register not in ("DIRECT", "CONVERSATIONAL", "GENTLE")
        or type(humor) is not bool
    ):
        raise ValueError("Personification guidance violated proposition or authority boundary")
    summary = {
        "register": register, "humor_allowed": humor,
        "literal_request_preserved": True, "permission_to_act": False,
        "source": "PINNED_PERSONIFICATION_RESEARCH_CANDIDATE",
    }
    note = (
        "Read-only Personification advisory: register " + register
        + "; humor allowed: " + str(humor).lower()
        + ". Answer the literal final user request first without rewriting it."
        " Do not infer emotions, identity, current consent or permission."
    )
    return note, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model", choices=("qwen3.5:0.8b", "qwen3:4b-instruct"),
        default="qwen3.5:0.8b",
    )
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--personification-checkout", type=Path)
    parser.add_argument("--actor-id")
    parser.add_argument("--subject-id")
    parser.add_argument("--interaction-kind", choices=(
        "GENERAL", "FACT_CHECK", "CASUAL", "SENSITIVE", "CORRECTION",
    ), default="GENERAL")
    parser.add_argument("--preferred-register", choices=(
        "DIRECT", "CONVERSATIONAL", "GENTLE",
    ), default="CONVERSATIONAL")
    parser.add_argument("--allow-humor", action="store_true")
    parser.add_argument(
        "--bounded-tone", action="store_true",
        help="Experimental source-grounded fictional dialogue; model selects tone only",
    )
    args = parser.parse_args()
    if args.bounded_tone and args.personification_checkout is not None:
        parser.error("--bounded-tone and --personification-checkout are separate trials")
    if args.personification_checkout is None:
        if (args.actor_id is not None or args.subject_id is not None
            or args.interaction_kind != "GENERAL"
            or args.preferred_register != "CONVERSATIONAL" or args.allow_humor):
            parser.error("Personification options require an explicit checkout")
    elif not args.actor_id or not args.subject_id:
        parser.error("opt-in Personification requires actor-id and subject-id")
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    if len(raw) > MAX_STDIN_BYTES:
        raise ValueError("input exceeds bounded JSON size")
    payload = json.loads(raw)
    if type(payload) is not dict:
        raise ValueError("input must be a JSON object")
    allowed = (
        ({"user_turns"}, {"user_turns", "scene_direction"})
        if args.bounded_tone else ({"user_turns"},)
    )
    if set(payload) not in allowed:
        raise ValueError("input keys are outside the selected research route")
    scene_direction = payload.get("scene_direction")
    if "scene_direction" in payload and (
        type(scene_direction) is not str
        or not scene_direction.strip()
        or len(scene_direction) > 320
        or any(c in scene_direction for c in ("\n", "\r", "\x00"))
    ):
        raise ValueError("scene_direction must be a bounded one-line string")
    turns = payload["user_turns"]
    advisory = None

    def generate() -> str:
        nonlocal advisory
        card = render_state(reconstruct(turns[:-1])) if len(turns) > 1 else ""
        system = SCENE_SYSTEM + ("\n\n" + card if card else "")
        if args.personification_checkout is not None:
            plan = plan_from_personification_checkout(
                args.personification_checkout, actor_id=args.actor_id,
                subject_id=args.subject_id, request=turns[-1],
                interaction_kind=args.interaction_kind,
                preferred_register=args.preferred_register,
                allow_humor=args.allow_humor,
            )
            note, advisory = note_from_personification_plan(plan, turns[-1])
            system += "\n\n" + note
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

    if args.bounded_tone:
        def select_tone(prompt: str) -> str:
            answer = local_api("/api/chat", {
                "model": args.model, "stream": False, "think": False,
                "keep_alive": "0",
                "options": {
                    "temperature": 0, "seed": args.seed,
                    "num_predict": 24, "num_ctx": 2048,
                },
                "messages": [
                    {"role": "system", "content": (
                        "Return exactly one uppercase token: DIRECT, GENTLE, "
                        "FIRM or CASUAL. No explanation."
                    )},
                    {"role": "user", "content": prompt},
                ],
            })
            return answer["message"]["content"]
        response = route_styled_boundary_reply(
            turns, select_tone, scene_direction=scene_direction,
        )
    else:
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
        "personification_advisory": advisory,
        "canonical_memory_admitted": response.canonical_memory_admitted,
        "external_effect_authorized": response.external_effect_authorized,
        "actual_user_identity_verified": response.actual_user_identity_verified,
        "scope": "READ_ONLY_FICTIONAL_SCENE",
    }, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
