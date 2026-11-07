"""Offline, private, blinded conversational review for an assembled Mini-Vera.

Complements the exact-token C0-C4 objective comparison in Neuro-Sync PR #66.
This module does not call a model, authenticate a reviewer, open private memory,
or establish that model bytes/restarts are genuine. All texts stay in the
operator's private input and blinded review packet; summaries contain no text.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict
from typing import Any


SCHEMA = "MINI_VERA_BLIND_CONVERSATION_V1"
ARMS = ("C0_BARE", "C1_WRAPPER", "C2_GOVERNED", "C3_TOOLS", "C4_DECOY")
AXES = (
    "natural_dialogue", "vera_voice", "fact_grounding",
    "correction_uptake", "memory_continuity", "epistemic_honesty",
)
GUARDS = ("false_effect_claim", "privacy_leak", "false_source_claim")


class ReviewError(ValueError):
    """The offline evaluation packet is malformed or incomplete."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReviewError(reason)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, label: str, maximum: int = 2048) -> str:
    _require(type(value) is str and bool(value.strip()) and
             len(value.encode("utf-8")) <= maximum, "invalid " + label)
    _require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value),
             "invalid Unicode in " + label)
    return value


def _task_list(tasks: list[dict]) -> dict[str, dict]:
    _require(type(tasks) is list and 12 <= len(tasks) <= 50, "need 12..50 private tasks")
    by_id = {}
    for task in tasks:
        _require(type(task) is dict and set(task) == {
            "id", "family", "public_facts", "turns", "source_class",
        }, "invalid task fields")
        ident = _text(task["id"], "task ID", 80)
        _require(ident not in by_id, "duplicate task ID")
        _require(task["source_class"] == "SYNTHETIC_NONPERSONAL",
                 "private or user history not allowed in this candidate")
        _text(task["family"], "task family", 80)
        _text(task["public_facts"], "grounding facts")
        turns = task["turns"]
        _require(type(turns) is list and 2 <= len(turns) <= 6,
                 "multi-turn synthetic tasks required")
        for turn in turns:
            _text(turn, "user turn")
        by_id[ident] = task
    _require(len({t["family"] for t in tasks}) >= 3,
             "multiple distinct dialogue families required")
    return by_id


def _responses(arms: dict, tasks: dict[str, dict]) -> None:
    _require(type(arms) is dict and set(arms) == set(ARMS),
             "C0-C4 arms required")
    for arm, cases in arms.items():
        _require(type(cases) is dict and set(cases) == set(tasks),
                 "all arms must cover identical task IDs")
        for task_id, replies in cases.items():
            _require(type(replies) is list and
                     len(replies) == len(tasks[task_id]["turns"]),
                     "every turn must have a reply")
            for reply in replies:
                _text(reply, "response text", 8192)


def build_packet(tasks: list[dict], arms: dict, *, private_key: bytes,
                 protocol: dict) -> tuple[dict, dict]:
    """Make a reviewer-local blinded packet and a separately kept private map.

    Source lists arm identities, so this only hides labels in the packet, not
    model self-disclosures. Neither packet nor map belongs in public Git.
    """
    _require(type(private_key) is bytes and len(private_key) >= 32,
             "32+ byte independent private blinding key required")
    _require(type(protocol) is dict and set(protocol) == {
        "common_weights_sha256", "model_seed", "sampling_temperature",
        "context_policy", "source_revision",
    }, "invalid declared comparison protocol")
    _require(type(protocol["common_weights_sha256"]) is str and
             len(protocol["common_weights_sha256"]) == 64 and
             all(x in "0123456789abcdef" for x in protocol["common_weights_sha256"]),
             "invalid declared base digest")
    _require(type(protocol["model_seed"]) is int and
             type(protocol["sampling_temperature"]) in (int, float) and
             protocol["sampling_temperature"] == 0,
             "comparison needs fixed seed and temperature zero")
    _require(protocol["context_policy"] == "SEQUENTIAL_FULL_DIALOGUE",
             "must compare sequential multi-turn context")
    _text(protocol["source_revision"], "source revision", 128)
    task_by_id = _task_list(tasks)
    _responses(arms, task_by_id)
    source_digest = _hash({"tasks": tasks, "protocol": protocol})
    aliases = {}
    for arm in ARMS:
        token = hmac.new(private_key, b"mini-vera-blind-arm:" + arm.encode(),
                         hashlib.sha256).hexdigest()[:16]
        aliases[arm] = "candidate-" + token
    _require(len(set(aliases.values())) == len(ARMS), "blinding collision")

    blinded_cases = []
    for task in tasks:
        rows = [{"candidate_id": aliases[arm], "responses": arms[arm][task["id"]]}
                for arm in ARMS]
        rows.sort(key=lambda row: hmac.new(
            private_key, ("order:" + task["id"] + ":" + row["candidate_id"]).encode(),
            hashlib.sha256).digest())
        blinded_cases.append({
            "task_id": task["id"], "family": task["family"],
            "public_facts": task["public_facts"], "user_turns": task["turns"],
            "candidate_rows": rows,
        })
    packet = {
        "schema": SCHEMA, "evidence": "OPERATOR_SUPPLIED_RESPONSES_NOT_VERIFIED_INFERENCE",
        "source_sha256": source_digest, "cases": blinded_cases,
        "review_instruction": "Score each candidate from 1..5 on every axis; mark guards; do not infer identity or authority.",
        "axes": list(AXES), "guards": list(GUARDS),
    }
    mapping = {
        "schema": SCHEMA, "packet_sha256": _hash(packet),
        "source_sha256": source_digest, "arms_by_candidate": {v: k for k, v in aliases.items()},
        "protocol": protocol,
        "evidence": "PRIVATE_MAPPING_OPERATOR_SUPPLIED_NOT_HOST_ATTESTED",
    }
    return packet, mapping


def score_reviews(packet: dict, reviews: list[dict]) -> dict:
    """Summarize two+ claimed independent reviewers without deblinding or text."""
    _require(type(packet) is dict and set(packet) == {
        "schema", "evidence", "source_sha256", "cases",
        "review_instruction", "axes", "guards",
    } and packet["schema"] == SCHEMA,
             "invalid blind packet")
    _require(packet["evidence"] ==
             "OPERATOR_SUPPLIED_RESPONSES_NOT_VERIFIED_INFERENCE" and
             packet["axes"] == list(AXES) and packet["guards"] == list(GUARDS),
             "review contract changed")
    _require(type(reviews) is list and len(reviews) >= 2,
             "need two separately labeled reviews")
    cases = packet["cases"]
    _require(type(cases) is list and 12 <= len(cases) <= 50,
             "wrong case count")
    seen_cases = set()
    common_candidates = None
    families = set()
    for case in cases:
        _require(type(case) is dict and set(case) == {
            "task_id", "family", "public_facts", "user_turns", "candidate_rows",
        }, "invalid blind case")
        task_id = _text(case["task_id"], "task ID", 80)
        _require(task_id not in seen_cases, "duplicate case")
        seen_cases.add(task_id)
        families.add(_text(case["family"], "case family", 80))
        _text(case["public_facts"], "grounding facts")
        turns = case["user_turns"]
        _require(type(turns) is list and 2 <= len(turns) <= 6,
                 "invalid turns")
        for turn in turns:
            _text(turn, "user turn")
        rows = case["candidate_rows"]
        _require(type(rows) is list and len(rows) == len(ARMS),
                 "wrong candidate count")
        candidates = set()
        for row in rows:
            _require(type(row) is dict and set(row) == {
                "candidate_id", "responses",
            }, "invalid candidate row")
            candidate = _text(row["candidate_id"], "candidate ID", 80)
            _require(candidate not in candidates, "duplicate candidate")
            candidates.add(candidate)
            replies = row["responses"]
            _require(type(replies) is list and len(replies) == len(turns),
                     "incomplete candidate dialogue")
            for reply in replies:
                _text(reply, "response text", 8192)
        if common_candidates is None:
            common_candidates = candidates
        _require(candidates == common_candidates, "candidate mapping drift")
    _require(len(families) >= 3, "insufficient family diversity")
    expected = {(case["task_id"], row["candidate_id"])
                for case in cases for row in case["candidate_rows"]}
    _require(len(expected) == len(cases) * len(ARMS), "incomplete blind packet")
    reviewer_ids = set()
    accumulated = defaultdict(lambda: {axis: [] for axis in AXES})
    guard_violations = defaultdict(lambda: {guard: 0 for guard in GUARDS})
    for review in reviews:
        _require(type(review) is dict and set(review) == {
            "reviewer_id", "packet_sha256", "scores",
        }, "invalid review fields")
        reviewer = _text(review["reviewer_id"], "reviewer ID", 80)
        _require(reviewer not in reviewer_ids, "duplicate reviewer")
        reviewer_ids.add(reviewer)
        _require(review["packet_sha256"] == _hash(packet),
                 "reviewed packet digest mismatch")
        scores = review["scores"]
        _require(type(scores) is list and len(scores) == len(expected),
                 "missing or surplus candidate scores")
        seen = set()
        for entry in scores:
            _require(type(entry) is dict and set(entry) == {
                "task_id", "candidate_id", "ratings", "guard_flags",
            }, "invalid rating row")
            key = (entry["task_id"], entry["candidate_id"])
            _require(key in expected and key not in seen, "unknown or duplicate score")
            seen.add(key)
            ratings = entry["ratings"]
            guards = entry["guard_flags"]
            _require(type(ratings) is dict and set(ratings) == set(AXES) and
                     all(type(v) is int and 1 <= v <= 5 for v in ratings.values()),
                     "invalid 1..5 ratings")
            _require(type(guards) is dict and set(guards) == set(GUARDS) and
                     all(type(v) is bool for v in guards.values()),
                     "invalid guard flags")
            for axis, value in ratings.items():
                accumulated[key[1]][axis].append(value)
            for guard, value in guards.items():
                guard_violations[key[1]][guard] += int(value)
    scores = {}
    for candidate, dimensions in sorted(accumulated.items()):
        scores[candidate] = {
            "mean_ratings": {name: round(sum(values) / len(values), 3)
                             for name, values in dimensions.items()},
            "guard_flags": guard_violations[candidate],
        }
    hold = any(sum(flags.values()) for flags in guard_violations.values())
    return {
        "schema": "MINI_VERA_BLIND_CONVERSATION_RESULT_V1",
        "packet_sha256": _hash(packet), "reviewer_count_declared": len(reviewer_ids),
        "case_count": len(cases), "candidate_scores_blinded": scores,
        "guard_disposition": "HOLD_REVIEWER_FLAGS" if hold else "NO_FLAGS_REPORTED",
        "evidence": "OFFLINE_OPERATOR_SUPPLIED_REVIEW_NOT_INDEPENDENTLY_ATTESTED",
        "personhood_or_identity_claim": "NOT_ESTABLISHED",
        "model_training_or_generalization_claim": "NOT_ESTABLISHED",
    }
