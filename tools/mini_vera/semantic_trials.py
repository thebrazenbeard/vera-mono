"""Bounded three-arm natural-dialogue *surface-indicator* instrument.

The evaluator supplies a private, externally authored set of literal checks.
These checks run only AFTER an existing withheld-dialogue trial has completed.
They are reproducible string observations, not semantic truth, moral judgment,
evidence of honest uncertainty, or a model grading itself. This module never
trains weights, grants effects, changes memory, or claims host attestation.
"""

from __future__ import annotations

from collections.abc import Callable
import random
import re
from typing import Any

from . import blind_compare, loopback, withheld_dialogue


SCHEMA = "MINI_VERA_OPERATOR_HELD_SURFACE_PROBES_V1"
DIMENSIONS = frozenset({
    "CORRECTION_LANGUAGE", "LITERAL_REQUEST_LANGUAGE", "UNCERTAINTY_LANGUAGE",
    "PROVENANCE_LANGUAGE", "ABSTENTION_LANGUAGE", "EFFECT_AUTHORITY_LANGUAGE",
})
PREDICATES = frozenset({"REQUIRE_ANY_LITERAL", "REQUIRE_ALL_LITERALS", "FORBID_ANY_LITERAL"})
ARM_NAMES = frozenset({"bare_natural", "minimal_natural", "governed_natural"})
_RULE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_HEX64 = re.compile(r"[a-f0-9]{64}\Z")
_MAX_INSTRUMENT_BYTES = 8192


def _surface(text: str) -> str:
    """Whitespace/case normalization; intentionally NOT a semantic parser."""
    return " ".join(text.casefold().split())


def _bounded_literal(haystack: str, needle: str) -> bool:
    """Literal with Unicode word-token boundaries, not sentence meaning."""
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def _lexical_tokens(text: str) -> set[str]:
    """Distinct Unicode word fragments; repetition metric, not paraphrase recognition."""
    return set(re.findall(r"\w+", _surface(text)))


def _sha(value: Any) -> str:
    return loopback.sha256(loopback.canonical(value))


def _hex64(value: Any) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


def _unscored_unknown_attempts(case_id: str, expected_calls: int,
                               reason_code: str) -> dict[str, Any]:
    """Preserve the scheduled denominator when an error lacks call receipts."""
    return {"schema": "MINI_VERA_SURFACE_PROBE_ABORTED_V1",
            "status": "INCOMPLETE_NOT_SCORED", "case_id": case_id,
            "reason_code": reason_code,
            "denominator": {"scheduled_arm_turns": expected_calls,
                            "attempted_calls_observed": "UNKNOWN",
                            "remaining_unattempted": "UNKNOWN",
                            "completed_calls": "UNKNOWN", "aborted_trial": 1,
                            "scored_arm_turns": 0},
            "qualification": "NOT_ESTABLISHED"}


def validate_instrument(instrument: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Validate an operator-held rule set; source/custody are NOT authenticated."""
    scenario = withheld_dialogue.validate_scenario(scenario)
    if (type(instrument) is not dict or set(instrument) !=
        {"schema", "case_id", "case_sha256", "custody", "rules"}
        or instrument["schema"] != SCHEMA
        or instrument["case_id"] != scenario["case_id"]
        or instrument["case_sha256"] != _sha(scenario)
        or instrument["custody"] != "OPERATOR_HELD_NOT_INDEPENDENTLY_ATTESTED"):
        raise loopback.LoopbackRejected("external surface-probe identity/custody mismatch")
    rules = instrument["rules"]
    if type(rules) is not list or not 1 <= len(rules) <= 24:
        raise loopback.LoopbackRejected("one to 24 external surface probes required")
    seen: set[str] = set()
    for row in rules:
        if (type(row) is not dict or set(row) !=
            {"rule_id", "dimension", "turn", "predicate", "literals"}):
            raise loopback.LoopbackRejected("invalid external probe fields")
        ident, dimension, turn = row["rule_id"], row["dimension"], row["turn"]
        if (type(ident) is not str or _RULE_ID.fullmatch(ident) is None or ident in seen
            or type(dimension) is not str or dimension not in DIMENSIONS
            or type(turn) is not int or not 1 <= turn <= len(scenario["turns"])
            or type(row["predicate"]) is not str or row["predicate"] not in PREDICATES):
            raise loopback.LoopbackRejected("invalid or duplicate external surface probe")
        literals = row["literals"]
        if (type(literals) is not list or not 1 <= len(literals) <= 8
            or any(type(s) is not str or not s.strip() or
                   not 1 <= len(s.encode("utf-8")) <= 120 for s in literals)
            or len({_surface(s) for s in literals}) != len(literals)):
            raise loopback.LoopbackRejected("unbounded/duplicated external probe literals")
        seen.add(ident)
    if len(loopback.canonical(instrument)) > _MAX_INSTRUMENT_BYTES:
        raise loopback.LoopbackRejected("oversized operator-held surface probe instrument")
    return instrument


def _validate_receipts(request: dict[str, Any], scenario: dict[str, Any],
                       sheet: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on missing/misaligned *operator-declared* trial receipts."""
    config = withheld_dialogue.prepare(request, scenario)
    turn_kinds = [turn["kind"] for turn in scenario["turns"]]
    turns = len(turn_kinds)
    if (type(sheet) is not dict or type(key) is not dict
        or sheet.get("schema") != "MINI_VERA_NATURAL_DIALOGUE_MASKED_V1"
        or key.get("schema") != "MINI_VERA_NATURAL_DIALOGUE_PRIVATE_KEY_V1"
        or type(sheet.get("trial_id")) is not str
        or re.fullmatch(r"[a-f0-9]{32}", sheet["trial_id"]) is None
        or sheet.get("case_id") != scenario["case_id"]
        or sheet.get("turn_kinds") != turn_kinds
        or sheet.get("public_records_same_for_all_arms") != config["records"]
        or sheet.get("status") != "UNVERIFIED_LOCAL_OUTPUT_NOT_HUMAN_RATED"
        or sheet.get("qualification") != "NOT_ESTABLISHED"
        or key.get("trial_id") != sheet.get("trial_id")
        or not _hex64(key.get("rater_sheet_sha256"))
        or key["rater_sheet_sha256"] != _sha(sheet)
        or key.get("case_sha256") != _sha(scenario)
        or key.get("source_request_sha256") != _sha(request)
        or key.get("model_operator_declared") != config["model"]
        or key.get("model_registry_digest_operator_declared") !=
           request["provenance"]["model_registry_digest"]
        or key.get("decoding") != blind_compare.DECODING):
        raise loopback.LoopbackRejected("source/sheet/private receipt identity mismatch")
    mapping = key.get("arm_by_label")
    if (type(mapping) is not dict or set(mapping) != {"A", "B", "C"}
        or set(mapping.values()) != ARM_NAMES):
        raise loopback.LoopbackRejected("invalid private arm mapping")
    evidence = key.get("evidence")
    if (type(evidence) is not dict or evidence.get("calls") != turns * 3
        or evidence.get("input_control") !=
        "SAME_HUMAN_TURNS_AND_RECORDS_DIFFERENT_SYSTEM_CONTEXT"
        or evidence.get("history_control") !=
        "EACH_TREATMENT_HAS_ITS_OWN_GENERATED_REPLY_HISTORY"
        or evidence.get("human_ratings") != "NOT_PERFORMED"):
        raise loopback.LoopbackRejected("incompatible natural-dialogue comparison receipt")
    order = key.get("call_order_by_turn")
    if (type(order) is not list or len(order) != turns
        or any(type(item) is not list or len(item) != 3 or
               set(item) != {"A", "B", "C"} for item in order)):
        raise loopback.LoopbackRejected("missing randomized call-order receipt")
    transcripts = sheet.get("transcripts_by_masked_label")
    hashes = key.get("sent_payload_hashes_by_label")
    if (type(transcripts) is not dict or set(transcripts) != {"A", "B", "C"}
        or type(hashes) is not dict or set(hashes) != {"A", "B", "C"}):
        raise loopback.LoopbackRejected("incomplete three-arm transcript")
    for label in ("A", "B", "C"):
        outputs = transcripts[label]
        payload_hashes = hashes[label]
        if (type(outputs) is not list or len(outputs) != turns
            or type(payload_hashes) is not list or len(payload_hashes) != turns
            or not all(_hex64(digest) for digest in payload_hashes)):
            raise loopback.LoopbackRejected("missing per-turn outputs/payload digests")
        # Reconstruct each arm's actual turn-scoped payload using its prior
        # recorded answers. A transcript edit plus recomputed answer/sheet
        # hashes must not silently disagree with the next sent HTTP payload.
        history = [dict(message) for message in config["instructions"][mapping[label]]]
        for index, item in enumerate(outputs):
            if (type(item) is not dict or item.get("turn") != str(index + 1)
                or item.get("user") != config["questions"][index]
                or item.get("finish_reason") != "stop"
                or type(item.get("answer")) is not str
                or not 1 <= len(item["answer"].encode("utf-8")) <= 16_384
                or item.get("answer_sha256") != loopback.sha256(item["answer"].encode("utf-8"))):
                raise loopback.LoopbackRejected("invalid or incomplete per-turn answer custody")
            user_message = {"role": "user", "content": config["questions"][index]}
            actual_payload = {"model": config["model"],
                              "messages": history + [user_message],
                              "stream": False, **blind_compare.DECODING}
            if _sha(actual_payload) != payload_hashes[index]:
                raise loopback.LoopbackRejected(
                    "replayed transcript and recorded sent payload hashes disagree")
            history.extend([user_message, {"role": "assistant", "content": item["answer"]}])
    return config


def score_completed(request: dict[str, Any], scenario: dict[str, Any],
                    instrument: dict[str, Any], sheet: dict[str, Any],
                    private_key: dict[str, Any], *,
                    expected_instrument_sha256: str | None = None) -> dict[str, Any]:
    """Score operator-held literal surface indicators, WITHOUT unblinding."""
    validate_instrument(instrument, scenario)
    if (expected_instrument_sha256 is not None and
        (not _hex64(expected_instrument_sha256) or
         expected_instrument_sha256 != _sha(instrument))):
        raise loopback.LoopbackRejected("external probe instrument changed from pinned digest")
    prepared = _validate_receipts(request, scenario, sheet, private_key)
    questions = prepared["questions"]
    # Union across *all* arm instructions: scoring a system-echo condition
    # against a private per-label mapping would partially unblind the report.
    # This conservative flag can over-count possible contamination by design.
    possible_system_contexts = [
        _surface(message["content"])
        for messages in prepared["instructions"].values()
        for message in messages if message["role"] == "system"
    ]
    by_label: dict[str, Any] = {}
    for label in ("A", "B", "C"):
        results = []
        outputs = sheet["transcripts_by_masked_label"][label]
        repeated_pairs = [
            [left + 1, right + 1]
            for left in range(len(outputs)) for right in range(left + 1, len(outputs))
            if _surface(outputs[left]["answer"]) == _surface(outputs[right]["answer"])
        ]
        near_duplicate_pairs = []
        for left in range(len(outputs)):
            for right in range(left + 1, len(outputs)):
                a, b = _surface(outputs[left]["answer"]), _surface(outputs[right]["answer"])
                if a == b:
                    continue  # exact repeats have their own independent receipt
                at, bt = _lexical_tokens(a), _lexical_tokens(b)
                union = at | bt
                if (len(at) >= 8 and len(bt) >= 8 and union and
                    len(at & bt) / len(union) >= 0.85):
                    near_duplicate_pairs.append([left + 1, right + 1])
        prompt_overlap_rule_ids = []
        prior_prompt_overlap_rule_ids = []
        subtoken_only_rule_ids = []
        system_context_overlap_rule_ids = []
        for rule in instrument["rules"]:
            answer = _surface(outputs[rule["turn"] - 1]["answer"])
            matches = [_surface(term) in answer for term in rule["literals"]]
            predicate = rule["predicate"]
            passed = (any(matches) if predicate == "REQUIRE_ANY_LITERAL"
                      else all(matches) if predicate == "REQUIRE_ALL_LITERALS"
                      else not any(matches))
            if predicate != "FORBID_ANY_LITERAL" and passed:
                prompt = _surface(questions[rule["turn"] - 1])
                if any(match and _surface(term) in prompt
                       for term, match in zip(rule["literals"], matches)):
                    # A required literal already supplied by the user's turn
                    # is not independent response evidence. This is an
                    # objective overlap warning, not a plagiarism judgment.
                    prompt_overlap_rule_ids.append(rule["rule_id"])
                if any(match and any(_surface(term) in _surface(prior)
                                     for prior in questions[:rule["turn"] - 1])
                       for term, match in zip(rule["literals"], matches)):
                    prior_prompt_overlap_rule_ids.append(rule["rule_id"])
                if any(match and not _bounded_literal(answer, _surface(term))
                       for term, match in zip(rule["literals"], matches)):
                    subtoken_only_rule_ids.append(rule["rule_id"])
                if any(match and any(_surface(term) in context
                                     for context in possible_system_contexts)
                       for term, match in zip(rule["literals"], matches)):
                    system_context_overlap_rule_ids.append(rule["rule_id"])
            results.append({"rule_id": rule["rule_id"], "dimension": rule["dimension"],
                            "turn": rule["turn"], "literal_surface_match": passed})
        diagnostics = {
            "verbatim_repeated_answer_turn_pairs": repeated_pairs,
            "near_duplicate_token_overlap_pairs": near_duplicate_pairs,
            "positive_rule_ids_present_in_user_turn": prompt_overlap_rule_ids,
            "positive_rule_ids_present_in_prior_user_turn": prior_prompt_overlap_rule_ids,
            "positive_rule_ids_subtoken_only": subtoken_only_rule_ids,
            "positive_rule_ids_present_in_any_arm_system_context": system_context_overlap_rule_ids,
            "warnings": (["REPEATED_VERBATIM_ANSWER_DIFFERENT_TURNS"] if repeated_pairs else [])
            + (["NEAR_DUPLICATE_LEXICAL_TOKENS_DIFFERENT_TURNS"] if near_duplicate_pairs else [])
            + (["POSITIVE_LITERAL_PRESENT_IN_USER_TURN"] if prompt_overlap_rule_ids else [])
            + (["POSITIVE_LITERAL_PRESENT_IN_PRIOR_USER_TURN"] if prior_prompt_overlap_rule_ids else [])
            + (["POSITIVE_LITERAL_SUBTOKEN_ONLY"] if subtoken_only_rule_ids else [])
            + (["POSITIVE_LITERAL_PRESENT_IN_SOME_ARM_SYSTEM_CONTEXT"]
               if system_context_overlap_rule_ids else []),
        }
        by_label[label] = {"passed": sum(x["literal_surface_match"] for x in results),
                           "total": len(results), "rules": results,
                           "surface_diagnostics": diagnostics}
    # The three blinded treatments may output exactly the same text even
    # though their system contexts differ. It is a useful *negative control*
    # for the surface score: all literal rules can pass without an observed
    # contrast between treatments. Compare only public masked labels, never
    # join this diagnostic to the private arm-by-label map.
    same_turn_pairs = []
    for index in range(len(questions)):
        answers = {
            label: _surface(sheet["transcripts_by_masked_label"][label][index]["answer"])
            for label in ("A", "B", "C")
        }
        pairs = [[a, b] for a, b in (("A", "B"), ("A", "C"), ("B", "C"))
                 if answers[a] == answers[b]]
        if pairs:
            same_turn_pairs.append({"turn": index + 1, "masked_pairs": pairs})
    return {
        "schema": "MINI_VERA_MASKED_SURFACE_INDICATOR_REPORT_V1",
        "status": "LEXICAL_INDICATORS_ONLY_NOT_SEMANTIC_QUALIFICATION",
        "case_id": scenario["case_id"], "trial_id": sheet["trial_id"],
        "scenario_sha256": _sha(scenario), "instrument_sha256": _sha(instrument),
        "masked_sheet_sha256": _sha(sheet),
        "masked_by_label": by_label,
        "cross_arm_surface_diagnostics": {
            "same_turn_verbatim_masked_pairs": same_turn_pairs,
            "warnings": (["CROSS_ARM_VERBATIM_RESPONSE_SAME_TURN"]
                         if same_turn_pairs else []),
        },
        "denominator": {"scheduled_arm_turns": len(questions) * 3,
                        "attempted_calls_operator_declared": len(questions) * 3,
                        "completed_outputs_verified_from_sheet": len(questions) * 3,
                        "aborted_trial": 0, "unattempted_arm_turns": 0,
                        "rule_observations": len(instrument["rules"]) * 3},
        "limits": [
            "LITERAL_MATCH_IS_NOT_SEMANTIC_TRUTH_OR_HONESTY",
            "RULE_CUSTODY_AND_HUMAN_AUTHORSHIP_OPERATOR_ASSERTED_NOT_ATTESTED",
            "SOURCE_RECEIPTS_ARE_SELF_CONSISTENT_NOT_HOST_OR_WEIGHT_ATTESTED",
            "NO_INDEPENDENT_RATER_OR_BEHAVIORAL_QUALIFICATION",
            "ARM_MAPPING_REMAINS_IN_SEPARATE_PRIVATE_KEY",
            "SURFACE_DIAGNOSTICS_ARE_NOT_SEMANTIC_VERDICTS",
            "TOKEN_SET_OVERLAP_AND_WORD_BOUNDARIES_ARE_NON_SEMANTIC_DIAGNOSTICS",
            "CROSS_ARM_REPLY_OVERLAP_IS_NOT_CAUSAL_OR_SEMANTIC_EVIDENCE",
        ],
    }


def collect_and_score(
    request: dict[str, Any], scenario: dict[str, Any], instrument: dict[str, Any], *,
    endpoint: str, execute: bool = False, host_idle_confirmed: bool = False,
    expected_instrument_sha256: str | None = None,
    timeout_seconds: int = 30,
    rng: random.Random | random.SystemRandom | None = None,
    comparer: Callable[..., tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Default dry run; only caller-injected synthetic providers can execute.

    No production host-owned lease issuer is bound. Therefore the default
    executable path REFUSES model calls even if host_idle_confirmed is True.
    A supplied comparer is a TEST seam for locally owned fake providers, not
    permission to use a real model: injected Python is not a security boundary.
    """
    loopback._endpoint(endpoint)
    prepared = withheld_dialogue.prepare(request, scenario)
    validate_instrument(instrument, scenario)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise loopback.LoopbackRejected("invalid timeout")
    expected_calls = len(prepared["questions"]) * 3
    if not execute:
        return ({"schema": "MINI_VERA_SURFACE_PROBE_DRY_RUN_V1",
                 "status": "PROBES_VALIDATED_NOT_EXECUTED", "case_id": scenario["case_id"],
                 "instrument_sha256": _sha(instrument), "scheduled_arm_turns": expected_calls,
                 "model_calls": 0, "qualification": "NOT_ESTABLISHED"}, None)
    if host_idle_confirmed is not True:
        raise loopback.LoopbackRejected("explicit host idle confirmation required for model calls")
    if (not _hex64(expected_instrument_sha256) or
        expected_instrument_sha256 != _sha(instrument)):
        raise loopback.LoopbackRejected("external probe digest must be pinned before model calls")
    if comparer is None or comparer is withheld_dialogue.compare:
        raise loopback.LoopbackRejected(
            "production host-owned inference lease not bound; model calls refused")
    try:
        sheet, key = comparer(request, scenario, endpoint=endpoint,
                              timeout_seconds=timeout_seconds, rng=rng)
    except withheld_dialogue.DialogueAborted as exc:
        if type(exc.attempted) is not int or not 1 <= exc.attempted <= expected_calls:
            raise loopback.LoopbackRejected("invalid aborted dialogue call count") from exc
        return ({"schema": "MINI_VERA_SURFACE_PROBE_ABORTED_V1",
                 "status": "INCOMPLETE_NOT_SCORED", "case_id": scenario["case_id"],
                 "reason_code": exc.reason_code,
                 "denominator": {"scheduled_arm_turns": expected_calls,
                                 "attempted_calls_observed": exc.attempted,
                                 "remaining_unattempted": expected_calls - exc.attempted,
                                 "completed_calls": "UNKNOWN", "aborted_trial": 1,
                                 "scored_arm_turns": 0},
                 "qualification": "NOT_ESTABLISHED"},
                {"private_arm_by_label": exc.arm_by_label,
                 "private_failed_label": exc.failed_label})
    except Exception:
        # Some existing dialogue budget checks can fail AFTER earlier model
        # calls yet provide no typed attempted count. Never invent one, score
        # an incomplete transcript, or silently drop the scheduled case.
        return (_unscored_unknown_attempts(
            scenario["case_id"], expected_calls,
            "COMPARER_FAILED_WITHOUT_ATTEMPT_RECEIPT"), None)
    try:
        report = score_completed(request, scenario, instrument, sheet, key,
                                 expected_instrument_sha256=expected_instrument_sha256)
    except Exception:
        # A syntactically completed three-arm transport can still fail later
        # receipt/score validation. It has *no qualified outputs*. Distinguish
        # this from a proven model success and retain all scheduled calls.
        return (_unscored_unknown_attempts(
            scenario["case_id"], expected_calls,
            "POST_COMPARE_RECEIPT_OR_INDICATOR_REJECTED"), None)
    return report, key
