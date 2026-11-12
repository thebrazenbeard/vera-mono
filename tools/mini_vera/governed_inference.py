"""Host-scoped, effectless cognitive decision applied BEFORE one model call.

Opt-in experimental Python API. The host must independently authenticate its
current person/source evidence and hold an exclusive invocation lease. These
callbacks and self-digests are not, by themselves, proof of correct admission,
trusted identity, running model weights, or protection against a TOCTOU race.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
from math import isfinite
import re
from typing import Any, Callable

from . import compose, compact_guidance, loopback

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]{8,96}\Z")
_PERSON = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_EVIDENCE = re.compile(r"ev_[0-9a-f]{32}\Z")


class GovernedRejected(ValueError):
    """Host evidence or result failed a source-bound contract."""


@dataclass(frozen=True, slots=True)
class HostObservation:
    request_sha256: str
    turn_sha256: str
    person_id: str
    revision: int
    nonce: str
    assessment: object
    fact_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GovernedOutcome:
    status: str
    source_request_sha256: str
    sent_request_sha256: str | None = None
    selected_policy: str | None = None
    result: dict[str, Any] | None = None
    http_calls: int = 0
    authority_effect: str = "NONE"
    memory_admission: str = "NONE"


def _source_request(request: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    try:
        original, _ = loopback.validate_candidate(request)
    except (ValueError, TypeError, KeyError) as exc:
        raise GovernedRejected("unverified source request") from exc
    sha = request["request_sha256"]
    if type(sha) is not str or _HEX64.fullmatch(sha) is None:
        raise GovernedRejected("invalid request digest")
    try:
        obj = json.loads(original["messages"][-1]["content"])
    except (TypeError, ValueError) as exc:
        raise GovernedRejected("invalid current user turn") from exc
    if type(obj) is not dict:
        raise GovernedRejected("current user object required")
    turn_key = "local_user_turn" if "local_user_turn" in obj else "synthetic_user_turn"
    current = obj.get(turn_key)
    if type(current) is not str or not current.strip():
        raise GovernedRejected("current user turn missing")
    return original, sha, current


def _checked_snapshot(
    value: HostObservation, *, request: dict[str, Any],
    request_sha: str, current_text: str,
) -> str:
    if type(value) is not HostObservation:
        raise GovernedRejected("typed host observation required")
    if value.request_sha256 != request_sha or value.turn_sha256 != request["provenance"]["turn_sha256"]:
        raise GovernedRejected("host observation not bound to current turn")
    if (type(value.person_id) is not str or _PERSON.fullmatch(value.person_id) is None
            or type(value.revision) is not int or value.revision < 0
            or type(value.nonce) is not str or _NONCE.fullmatch(value.nonce) is None):
        raise GovernedRejected("invalid host person/revision/nonce")
    if type(value.fact_tags) is not tuple or len(value.fact_tags) > 3:
        raise GovernedRejected("invalid host fact-tags container")
    if (any(type(t) is not str or t not in compact_guidance._HINTS for t in value.fact_tags)
            or len(set(value.fact_tags)) != len(value.fact_tags)):
        raise GovernedRejected("unrecognized or repeated fact tags")
    assessment = value.assessment
    if (getattr(assessment, "person_id", None) != value.person_id
            or type(getattr(assessment, "current_evidence", None)) is not tuple
            or getattr(assessment, "historical_evidence", None) != ()
            or getattr(assessment, "hypotheses", None) != ()):
        raise GovernedRejected("foreign or historical donor evidence")
    if not 1 <= len(assessment.current_evidence) <= 8:
        raise GovernedRejected("no bounded current donor evidence")
    observations: list[dict[str, Any]] = []
    ids: set[str] = set()
    for ev in assessment.current_evidence:
        eid = getattr(ev, "evidence_id", None)
        conf = getattr(ev, "confidence", None)
        kind, referent, data = (getattr(ev, name, None) for name in ("kind", "referent", "value"))
        if (type(eid) is not str or _EVIDENCE.fullmatch(eid) is None or eid in ids
                or getattr(ev, "source", None) != "current"
                or getattr(ev, "active", None) is not True
                or getattr(ev, "scope_person_id", None) != value.person_id
                or type(conf) not in (float, int) or not isfinite(conf)
                or not 0 <= conf <= 1
                or any(type(s) is not str or not s or len(s.encode("utf-8")) > 4096
                       for s in (kind, referent, data))):
            raise GovernedRejected("invalid, ambiguous or unscoped current donor evidence")
        if kind == "task_request" and (referent != "task" or data != current_text):
            raise GovernedRejected("task donor evidence not bound to current text")
        ids.add(eid)
        observations.append({"kind": kind, "referent": referent, "value": data,
                             "confidence": conf, "evidence_id": eid})
    fingerprint = {
        "request_sha256": value.request_sha256, "turn_sha256": value.turn_sha256,
        "person_id": value.person_id, "revision": value.revision, "nonce": value.nonce,
        "fact_tags": value.fact_tags, "evidence": observations,
        "stakes": getattr(assessment, "stakes", None),
    }
    try:
        return compose.sha256(compose.canonical(fingerprint))
    except (TypeError, UnicodeError, ValueError) as exc:
        raise GovernedRejected("host observation not serializable") from exc


def _must_hold_for_current_evidence(observation: HostObservation) -> str | None:
    for ev in observation.assessment.current_evidence:
        if (ev.kind in ("direct_correction", "withdrawal")
                and ev.referent == "play_frame" and ev.value == "stop"):
            return "CURRENT_STOP_HOLD"
        if ev.kind == "unsupported_claim" and ev.referent == "external_fact":
            return "UNSUPPORTED_EVIDENCE_HOLD"
        if ev.kind == "withdrawal" and ev.value in ("possible", "stop"):
            return "WITHDRAWAL_HOLD"
    return None


def run_governed_turn(
    request: dict[str, Any],
    *, enabled: bool = False,
    observe: Callable[[], HostObservation] | None = None,
    evaluate: Callable[[object], object] | None = None,
    make_donor_candidate: Callable[[object, str], object] | None = None,
    transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    claim_invocation: Callable[[HostObservation], bool] | None = None,
) -> GovernedOutcome:
    """One source-scoped decision, pre-invocation recheck, and post-output recheck.

    Injected host callbacks are dependencies, NOT external attestations. The
    host must serialize current-user withdrawal and source/lease decisions
    around any real model call. This function cannot solve TOCTOU alone.
    """
    if type(enabled) is not bool:
        raise GovernedRejected("enabled must be literal boolean")
    if not enabled:
        return GovernedOutcome("DISABLED", "")
    if not all(callable(x) for x in (observe, evaluate, make_donor_candidate, transport)):
        raise GovernedRejected("host observation, actual donor and transport callbacks required")
    original, sha, current = _source_request(request)
    try:
        before = observe()
    except Exception as exc:
        raise GovernedRejected("host observation unavailable") from exc
    fingerprint = _checked_snapshot(before, request=request, request_sha=sha, current_text=current)
    try:
        policy = evaluate(before.assessment)
    except Exception as exc:
        raise GovernedRejected("donor evaluation failed") from exc
    chosen = getattr(policy, "policy", None)
    selected = getattr(chosen, "value", chosen)
    if (type(selected) is not str or getattr(policy, "authority", None) != "NONE"
            or getattr(policy, "effect_authority", None) is not False
            or getattr(policy, "memory_admission", None) != "NONE"):
        raise GovernedRejected("donor authority or policy invalid")
    evidence_ids = {e.evidence_id for e in before.assessment.current_evidence}
    selected_ids = getattr(policy, "supporting_evidence_ids", None)
    if (type(selected_ids) is not tuple
            or any(type(e) is not str or e not in evidence_ids for e in selected_ids)):
        raise GovernedRejected("donor policy is not supported by present observations")
    # Conservative host-owned veto independent of donor choice; a forged
    # TASK_DIRECT cannot overrule explicit present STOP or unsupported fact.
    evidence_hold = _must_hold_for_current_evidence(before)
    if selected == "STOP_PLAY":
        return GovernedOutcome("DONOR_STOP_HOLD", sha, selected_policy=selected)
    if evidence_hold is not None:
        return GovernedOutcome(evidence_hold, sha, selected_policy=selected)
    if selected == "TRUTHFUL_CHALLENGE":
        return GovernedOutcome("UNSUPPORTED_EVIDENCE_HOLD", sha, selected_policy=selected)
    if selected != "TASK_DIRECT" or getattr(policy, "reason_code", None) != "EXPLICIT_TASK":
        return GovernedOutcome("DONOR_NON_TASK_HOLD", sha, selected_policy=selected)
    matched_task_ids = {
        e.evidence_id for e in before.assessment.current_evidence
        if e.kind == "task_request" and e.referent == "task" and e.value == current
    }
    if not matched_task_ids or not matched_task_ids.intersection(selected_ids):
        raise GovernedRejected("donor task policy lacks exact current task support")
    try:
        donor = make_donor_candidate(before.assessment, current)
        guidance = compact_guidance.compact_candidate(
            request, enabled=True, donor_candidate=donor,
            donor_current_task=current, host_evidence_tags=before.fact_tags)
    except (compact_guidance.CompactGuidanceRejected, TypeError, ValueError) as exc:
        raise GovernedRejected("donor prompt candidate not admitted") from exc
    if guidance.status != "UNATTESTED_COMPACT_PROMPT_CANDIDATE" or guidance.payload is None:
        return GovernedOutcome("DONOR_UNBOUND_HOLD", sha, selected_policy=selected)

    # Make a new *effectless* source-composed request carrying the revised
    # system text, and check it with the existing complete transport validator.
    prepared = copy.deepcopy(request)
    inference = prepared["inference"]
    inference["messages"][0]["content"] = guidance.payload["messages"][0]["content"]
    prepared["request_sha256"] = compose.sha256(compose.canonical(inference))
    sent_sha = prepared["request_sha256"]
    checked, payload_sha = loopback.validate_candidate(prepared)
    if checked != guidance.payload or payload_sha != guidance.output_payload_sha256:
        raise GovernedRejected("prepared inference differs from vetted compact payload")

    def unchanged() -> bool:
        try:
            latest = observe()
            return _checked_snapshot(latest, request=request, request_sha=sha, current_text=current) == fingerprint
        except Exception:
            return False

    if not unchanged():
        return GovernedOutcome("HOST_CHANGED_HOLD", sha, selected_policy=selected)
    # The host must atomically consume this current-turn nonce before its
    # first model invocation. Refuse retries with the same lease. This
    # callback is the host's responsibility; no local in-memory set can
    # establish durable, cross-process at-most-once protection.
    if not callable(claim_invocation):
        raise GovernedRejected("atomic host invocation claim required")
    try:
        claim = claim_invocation(before)
    except Exception as exc:
        raise GovernedRejected("host invocation claim failed") from exc
    if type(claim) is not bool:
        raise GovernedRejected("host invocation claim was not a boolean")
    if not claim:
        return GovernedOutcome("REPLAY_HOLD", sha, selected_policy=selected)
    # Claim callbacks may themselves consume an updated STOP/correction.
    # Reobserve immediately before touching the model transport.
    if not unchanged():
        return GovernedOutcome("HOST_CHANGED_AFTER_CLAIM_HOLD", sha,
                               selected_policy=selected)

    # Only now is a transport allowed; the host must still independently
    # enforce endpoint ownership, resource admission and network scoping.
    response = transport(prepared)
    if not unchanged():
        return GovernedOutcome("OUTPUT_WITHHELD_HOST_CHANGED", sha, sent_sha, selected, http_calls=1)
    if compose.sha256(compose.canonical(prepared["inference"])) != sent_sha:
        raise GovernedRejected("model transport mutated the governed request")
    if (type(response) is not dict
            or response.get("schema") != "MINI_VERA_UNVERIFIED_LOOPBACK_RESULT_V1"
            or response.get("status") not in ("UNVERIFIED_LOCAL_MODEL_OUTPUT", "TRUNCATED_UNVERIFIED_OUTPUT")
            or type(response.get("response")) is not dict
            or type(response["response"].get("text")) is not str
            or type(response.get("provenance")) is not dict
            or response["provenance"].get("composed_request_sha256") != sent_sha
            or type(response.get("evidence")) is not dict
            or response["evidence"].get("http_calls") != 1
            or response["evidence"].get("authority_effect") != "NONE"
            or response["evidence"].get("memory_admission") != "NOT_PERFORMED"):
        raise GovernedRejected("model transport did not return a bound effectless result")
    return GovernedOutcome("MODEL_OUTPUT_UNVERIFIED", sha, sent_sha, selected,
                           copy.deepcopy(response), 1)
