"""Source-visible controlled prompt ablation on synthetic missing-fact questions.

This is a model-behavior experiment, NOT independent heldout human evaluation,
training, trust attestation, user-memory admission or a host authority.
The same composed PUBLIC record and question are supplied to every prompt arm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import secrets
import sys
from typing import Any

from . import blind_compare, compose, counterfactual_subject_eval as counter
from . import local_session, loopback

SCHEMA = "MINI_VERA_PROMPT_ABLATION_V1"
ARMS = ("baseline", "explicit_abstain", "exact_subject_lookup")
CASES = ("known_subject", "missing_subject_with_record",
         "missing_subject_without_record")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
EXPLICIT_RULE = (
    "\nMINI_VERA_EXPLICIT_UNKNOWN_RULE: The provided public project records "
    "are the only source of project facts for this question. If the EXACT "
    "requested subject ID is not present in the supplied records, respond "
    "with exactly UNKNOWN; never borrow a different subject's gate ID."
)
EXACT_RULE = (
    "\nMINI_VERA_EXACT_SUBJECT_RULE: Before answering, locate the EXACT "
    "questioned subject C-XXXXXXXX in the supplied reference DATA. "
    "Use only its associated current G-XXXXXXXX value, respecting the newest "
    "superseding revision when present. If no exact subject match exists, "
    "output only UNKNOWN. Do not guess, interpolate or treat neighboring "
    "subject facts as evidence of the requested fact. Output only one "
    "gate ID or UNKNOWN; do not include the lookup explanation."
)
PROMPT_SUFFIXES = {
    "baseline": "",
    "explicit_abstain": EXPLICIT_RULE,
    "exact_subject_lookup": EXACT_RULE,
}


class AblationRefused(ValueError):
    """An invalid prompt-ablation request cannot contact the model."""


class AblationAborted(AblationRefused):
    """At least one model call failed: no incomplete trial is scored."""

    def __init__(self, reason: str, attempted: int):
        super().__init__("prompt-ablation trial aborted: " + reason)
        self.reason = reason
        self.attempted = attempted


def _validated_inputs(*, endpoint: str, model: str, model_digest: str,
                      variant: str, timeout_seconds: int) -> None:
    try:
        loopback._endpoint(endpoint)
    except loopback.LoopbackRejected as exc:
        raise AblationRefused("numeric local-only endpoint required") from exc
    if (type(model) is not str or loopback.MODEL.fullmatch(model) is None
            or type(model_digest) is not str
            or HEX64.fullmatch(model_digest) is None
            or type(variant) is not str or variant not in ("directory", "revision")
            or type(timeout_seconds) is not int
            or timeout_seconds not in (30, 60)):
        raise AblationRefused("invalid model/variant/time scope")


def _payload(*, question: str, provider: Any, model: str,
             model_digest: str) -> dict[str, Any]:
    if provider is None:
        state, key = local_session.empty_public_state()
        revision = 0
    else:
        state, key, revision = provider()
    try:
        identity, identity_raw = compose.read_object(compose.IDENTITY_PATH, 16_384)
        behavior, behavior_raw = compose.read_object(compose.BEHAVIOR_PATH, 16_384)
        if (compose.sha256(identity_raw) != local_session.PINNED_IDENTITY_SHA256
                or compose.sha256(behavior_raw) !=
                local_session.PINNED_BEHAVIOR_SHA256):
            raise AblationRefused("identity or behavior source drift")
        composed = local_session.compose_local_turn(
            text=question, turn_id="abl-" + secrets.token_hex(8),
            history=[], identity=identity, identity_raw=identity_raw,
            behavior=behavior, behavior_raw=behavior_raw,
            state=state, key=key, revision=revision,
            model=model, model_digest=model_digest, num_predict=256)
        result, _ = loopback.validate_candidate(composed)
    except (compose.CompositionRejected, loopback.LoopbackRejected,
            ValueError, KeyError) as exc:
        raise AblationRefused("synthetic project source not valid") from exc
    if (set(result) != {"model", "messages", "stream", "temperature",
                        "max_tokens", "seed"}
            or len(result["messages"]) != 2
            or result["messages"][0]["role"] != "system"
            or result["messages"][1]["role"] != "user"):
        raise AblationRefused("unexpected bounded composer payload")
    return {**result, "reasoning_effort": "none"}


def run_trial(*, endpoint: str, model: str, model_digest: str,
              variant: str = "directory", timeout_seconds: int = 60,
              rng: random.Random | random.SystemRandom | None = None
              ) -> dict[str, Any]:
    """Three paired prompt arms across three source-evidence conditions.

    A score concerns raw generated text. Client evidence-gate effects are
    NOT executed here and cannot inflate model abstention.
    """
    _validated_inputs(endpoint=endpoint, model=model,
                      model_digest=model_digest, variant=variant,
                      timeout_seconds=timeout_seconds)
    mixer = rng if rng is not None else secrets.SystemRandom()
    rows: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    attempts = 0
    case_requests: dict[str, dict[str, Any]] = {}
    try:
        with counter._temporary_fixture(variant) as fixture:
            for case in CASES:
                question = (fixture.known_question if case == "known_subject"
                            else fixture.missing_question)
                provider = (fixture.provider if case !=
                            "missing_subject_without_record" else None)
                case_requests[case] = _payload(
                    question=question, provider=provider, model=model,
                    model_digest=model_digest)
            case_order = list(CASES)
            mixer.shuffle(case_order)
            for case in case_order:
                base = case_requests[case]
                expected = fixture.expected if case == "known_subject" else "UNKNOWN"
                arm_order = list(ARMS)
                mixer.shuffle(arm_order)
                for arm in arm_order:
                    payload = {
                        **base, "messages": [
                            {"role": "system", "content":
                             base["messages"][0]["content"] + PROMPT_SUFFIXES[arm]},
                            dict(base["messages"][1]),
                        ],
                    }
                    if len(loopback.canonical(payload)) > loopback.MAX_REQUEST_FILE:
                        raise AblationRefused("modified arm exceeds input bound")
                    attempts += 1
                    try:
                        output = blind_compare._one_call(
                            payload, endpoint=endpoint,
                            timeout_seconds=timeout_seconds)
                    except loopback.LoopbackRejected as exc:
                        raise AblationAborted(
                            "INVALID_OR_UNAVAILABLE_REPLY", attempts) from exc
                    try:
                        text = output["text"]
                        finish = output["finish_reason"]
                        stamp = output["response_sha256"]
                        if (type(text) is not str
                                or len(text.encode("utf-8")) > 8192
                                or finish not in ("stop", "length")
                                or type(stamp) is not str
                                or stamp != loopback.sha256(text.encode("utf-8"))):
                            raise ValueError("invalid response contract")
                    except (TypeError, ValueError, KeyError) as exc:
                        raise AblationAborted(
                            "INCONSISTENT_REPLY", attempts) from exc
                    success = finish == "stop" and text.strip() == expected
                    rows[arm].append({
                        "case": case,
                        "correct": success,
                        "raw_missing_fact_abstention": (
                            case != "known_subject" and success),
                        "supported_fact_hit": case == "known_subject" and success,
                        "truncated": finish == "length",
                        "response_sha256": stamp,
                    })
            source_sha = fixture.record_sha256
    except counter.CounterfactualRefused as exc:
        raise AblationAborted("SYNTHETIC_FIXTURE_REFUSED", attempts) from exc
    if attempts != 9 or any(len(rows[arm]) != 3 for arm in ARMS):
        raise AblationAborted("INCOMPLETE_DESIGN", attempts)
    totals = {}
    for arm in ARMS:
        cases = sorted(rows[arm], key=lambda x: CASES.index(x["case"]))
        totals[arm] = {
            "raw_exact_count": sum(case["correct"] for case in cases),
            "supported_fact_hits": sum(case["supported_fact_hit"] for case in cases),
            "missing_fact_abstentions": sum(
                case["raw_missing_fact_abstention"] for case in cases),
            "truncated_count": sum(case["truncated"] for case in cases),
            "case_results": cases,
            "system_suffix_sha256": loopback.sha256(
                PROMPT_SUFFIXES[arm].encode("utf-8")),
        }
    truncated = any(data["truncated_count"] for data in totals.values())
    return {
        "schema": SCHEMA,
        "status": ("COMPLETED_WITH_TRUNCATIONS" if truncated
                   else "COMPLETED_NOT_BEHAVIORALLY_QUALIFIED"),
        "http_calls": attempts,
        "case_family": variant,
        "case_source_sha256": source_sha,
        "arm_results": totals,
        "model_behavior_qualified": False,
        "independent_heldout": False,
        "model_identity": "OPERATOR_TAG_NOT_RESIDENT_TENSOR_ATTESTATION",
        "evidence_ceiling": "SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
        "source_authority_qualified": False,
        "training_or_weight_changes": False,
        "client_gate_used": False,
        "shared_model_alias_and_decoding": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--variant", choices=("directory", "revision"),
                        default="directory")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host-idle-confirmed", action="store_true")
    args = parser.parse_args(argv)
    try:
        _validated_inputs(endpoint=args.endpoint, model=args.model,
                          model_digest=args.model_digest, variant=args.variant,
                          timeout_seconds=args.timeout_seconds)
    except AblationRefused:
        print("PROMPT_ABLATION_VALIDATION_REFUSED", file=sys.stderr)
        return 2
    if not args.execute:
        print(json.dumps({
            "schema": SCHEMA,
            "status": "VALIDATED_NOT_EXECUTED",
            "http_calls": 0,
            "evidence_ceiling": "SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
        }, sort_keys=True))
        return 0
    if not args.host_idle_confirmed:
        parser.error("--host-idle-confirmed required for local neural calls")
    try:
        result = run_trial(
            endpoint=args.endpoint, model=args.model,
            model_digest=args.model_digest, variant=args.variant,
            timeout_seconds=args.timeout_seconds)
    except AblationAborted as exc:
        print(json.dumps({
            "schema": SCHEMA, "status": "INCOMPLETE_NOT_SCORED",
            "reason_code": exc.reason,
            "attempted_http_calls": exc.attempted,
        }, sort_keys=True))
        return 2
    except AblationRefused:
        print("PROMPT_ABLATION_REFUSED", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
