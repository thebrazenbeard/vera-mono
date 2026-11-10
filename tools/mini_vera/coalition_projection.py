"""Experimental zero-weight HC + social-policy advisory for Mini-Vera.

This uses the existing HC projector and the public *interfaces* of Empathy's
ResponsePolicyHint and Personification's SocialPlan. It imports no sibling
implementation, model, tool broker or private history. All inputs are
caller-supplied; an authorized host must independently establish their source,
scope, currentness and right to be used. No model call or state write occurs.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .hc_projection import project_public_context


class CoalitionProjectionRejected(ValueError):
    """A component cannot safely join the ephemeral advisory coalition."""


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_EVIDENCE = re.compile(r"ev_[a-f0-9]{32}\Z")
_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
_POLICIES = frozenset({
    "CLARIFY_MEANING", "TASK_DIRECT", "REPAIR_FIRST", "CELEBRATE_FIRST",
    "TRUTHFUL_CHALLENGE", "PRESERVE_PLAY", "STOP_PLAY",
})
_REGISTERS = frozenset({"DIRECT", "CONVERSATIONAL", "GENTLE"})
_ABLATIONS = frozenset({"HC", "EMPATHY", "PERSONIFICATION"})
_HINT_FIELDS = frozenset({
    "policy", "reason_code", "confidence_band", "supporting_evidence_ids",
    "superseded_hypothesis_ids", "focus_needed", "schema", "consumer",
    "authority", "persistence", "volition_want_authority", "effect_authority",
})
_PLAN_FIELDS = frozenset({
    "actor_id", "subject_id", "answer_target", "answer_literal_request_first",
    "terminology_suggestion", "register", "humor_allowed", "classified_claims",
    "permission_to_act",
})


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise CoalitionProjectionRejected(f"invalid {name}")
    return value


def _plain(value: object, name: str) -> dict[str, Any]:
    """Read a sibling interface result; never execute a supplied callback."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if type(value) is not dict:
        raise CoalitionProjectionRejected(f"{name} must be a typed-result mapping")
    return value


def _empathy(value: object, admitted_ids: frozenset[str]) -> dict[str, Any]:
    hint = _plain(value, "Empathy hint")
    if set(hint) != _HINT_FIELDS or (
        hint["schema"] != "EMPATHY_RESPONSE_POLICY_HINT_V1"
        or hint["consumer"] != "RESPONSE_POLICY_ONLY"
        or hint["authority"] != "NONE"
        or hint["persistence"] != "EPHEMERAL"
        or hint["volition_want_authority"] is not False
        or hint["effect_authority"] is not False
    ):
        raise CoalitionProjectionRejected("Empathy schema or authority mismatch")
    if (type(hint["policy"]) is not str or hint["policy"] not in _POLICIES
        or type(hint["reason_code"]) is not str
        or _REASON.fullmatch(hint["reason_code"]) is None
        or hint["confidence_band"] not in ("NONE", "TENTATIVE", "HIGH_SCORE")
        or type(hint["focus_needed"]) is not bool):
        raise CoalitionProjectionRejected("invalid Empathy policy")
    refs = hint["supporting_evidence_ids"]
    superseded = hint["superseded_hypothesis_ids"]
    if (type(refs) not in (tuple, list) or len(refs) > 12
        or any(type(r) is not str or _EVIDENCE.fullmatch(r) is None for r in refs)
        or len(refs) != len(set(refs)) or not set(refs).issubset(admitted_ids)
        or type(superseded) not in (tuple, list) or len(superseded) > 12
        or any(type(r) is not str or re.fullmatch(r"hyp_[a-f0-9]{32}", r) is None
               for r in superseded)
        or len(superseded) != len(set(superseded))):
        raise CoalitionProjectionRejected("Empathy evidence not admitted for this turn")
    if not refs and hint["policy"] not in ("CLARIFY_MEANING", "TASK_DIRECT"):
        raise CoalitionProjectionRejected("non-default Empathy advice lacks current evidence")
    return {"policy": hint["policy"], "reason_code": hint["reason_code"],
            "confidence_band": hint["confidence_band"], "focus_needed": hint["focus_needed"],
            "evidence_ids": list(refs)}


def _personification(value: object, *, actor_id: str, subject_id: str,
                    literal_request: str) -> dict[str, Any]:
    plan = _plain(value, "Personification plan")
    if set(plan) != _PLAN_FIELDS or plan["permission_to_act"] is not False:
        raise CoalitionProjectionRejected("Personification plan or authority mismatch")
    if (plan["actor_id"] != actor_id or plan["subject_id"] != subject_id
        or plan["answer_target"] != literal_request
        or plan["answer_literal_request_first"] is not True
        or type(plan["humor_allowed"]) is not bool):
        raise CoalitionProjectionRejected("Personification scope or literal request mismatch")
    register = plan["register"]
    if hasattr(register, "value"):
        register = register.value
    if type(register) is not str or register not in _REGISTERS:
        raise CoalitionProjectionRejected("unknown Personification register")
    if (plan["terminology_suggestion"] is not None
        and (type(plan["terminology_suggestion"]) is not str
             or len(plan["terminology_suggestion"].encode("utf-8")) > 256)):
        raise CoalitionProjectionRejected("unsafe terminology suggestion")
    claims = plan["classified_claims"]
    if type(claims) not in (list, tuple) or len(claims) > 24:
        raise CoalitionProjectionRejected("invalid Personification claim inventory")
    # Claimed inner lives and raw suggestion text never enter model context.
    return {"register": register, "humor_allowed": plan["humor_allowed"],
            "literal_request_first": True}


def project_response_coalition(
    coalition: dict[str, Any], proposals: Sequence[dict[str, Any]], *,
    current_cycle: int, actor_id: str, subject_id: str, turn_id: str,
    literal_request: str, empathy_hint: object | None = None,
    personification_plan: object | None = None,
    admitted_empathy_evidence_ids: Sequence[str] = (),
    ablate_sources: Sequence[str] = (),
) -> dict[str, Any]:
    """Produce unsigned, ephemeral PUBLIC context candidates and ablation receipt.

    The host must authenticate/admit sibling results before calling, then
    independently bind/sign any chosen records for Mini-Vera's composer.
    Source-only checks cannot authenticate claimed timestamps or actors.
    """
    actor_id = _identifier(actor_id, "actor")
    subject_id = _identifier(subject_id, "subject")
    turn_id = _identifier(turn_id, "turn")
    if (type(literal_request) is not str or not literal_request.strip()
        or len(literal_request.encode("utf-8")) > 4096):
        raise CoalitionProjectionRejected("invalid literal request")
    if (type(ablate_sources) not in (tuple, list)
        or len(ablate_sources) != len(set(ablate_sources))
        or any(type(s) is not str or s not in _ABLATIONS for s in ablate_sources)):
        raise CoalitionProjectionRejected("invalid ablation")
    if (type(admitted_empathy_evidence_ids) not in (tuple, list)
        or len(admitted_empathy_evidence_ids) > 32
        or any(type(r) is not str or _EVIDENCE.fullmatch(r) is None
               for r in admitted_empathy_evidence_ids)
        or len(admitted_empathy_evidence_ids) != len(set(admitted_empathy_evidence_ids))):
        raise CoalitionProjectionRejected("invalid admitted evidence inventory")

    ablated = frozenset(ablate_sources)
    # A leave-one-out arm must not consume the omitted module at all. Otherwise
    # a malformed omitted result could poison the independent ablation arm.
    hc = (project_public_context(coalition, proposals, current_cycle=current_cycle)
          if "HC" not in ablated else None)
    policy = (_empathy(empathy_hint, frozenset(admitted_empathy_evidence_ids))
              if empathy_hint is not None and "EMPATHY" not in ablated else None)
    social = (_personification(personification_plan, actor_id=actor_id,
                              subject_id=subject_id, literal_request=literal_request)
              if personification_plan is not None and "PERSONIFICATION" not in ablated else None)
    records = list(hc["selected_records"]) if hc else []
    if policy is not None or social is not None:
        advice = {
            "ephemeral_response_policy": (policy["policy"] if policy else "NONE"),
            "register": (social["register"] if social else "UNSPECIFIED"),
            "answer_literal_first": bool(social and social["literal_request_first"]),
            "humor_allowed": bool(social and social["humor_allowed"]
                                  and (not policy or policy["policy"] != "STOP_PLAY")),
            "confidence_band": (policy["confidence_band"] if policy else "NONE"),
            "focus_needed": bool(policy and policy["focus_needed"]),
        }
        # A composer record is DATA_NOT_INSTRUCTION, never an active policy.
        raw_advice = _canonical(advice)
        if len(raw_advice) > 384:
            raise CoalitionProjectionRejected("advisory exceeds composer record budget")
        occupied = {record["record_id"] for record in records}
        advice_id = "coalition:response-advice"
        for suffix in range(1, len(occupied) + 2):
            if advice_id not in occupied:
                break
            advice_id = f"coalition:response-advice:{suffix}"
        records.append({
            "record_id": advice_id, "record_class": "WORKING_PROJECT",
            "privacy": "PUBLIC", "instruction_trust": "DATA_NOT_INSTRUCTION",
            "authority_effect": "NONE", "source_sha256": _digest(raw_advice),
            "text": raw_advice.decode("utf-8"),
        })
    if len(records) > 8:
        raise CoalitionProjectionRejected("coalition exceeds composer record limit")
    result = {
        "schema": "MINI_VERA_ZERO_WEIGHT_COALITION_CANDIDATE_V1",
        "turn_id": turn_id, "actor_id": actor_id, "subject_id": subject_id,
        "literal_request_sha256": _digest(literal_request.encode("utf-8")),
        "hc_projection_sha256": hc["projection_sha256"] if hc else None,
        "selected_records": records, "ablated_sources": sorted(ablated),
        "ephemeral_advice": advice if policy is not None or social is not None else None,
        "evidence_ids": list(policy["evidence_ids"]) if policy else [],
        "invariants": {
            "neural_weights_changed": False, "model_calls": 0,
            "memory_write": "NONE", "effect_authority": "NONE",
            "identity_source": "VERA_MONO_PINNED_COMPOSER_ONLY",
            "source_currentness": "CALLER_DECLARED_NOT_AUTHENTICATED",
            "sibling_outputs": "ADVISORY_ONLY",
            "composer_activation": "REQUIRES_SEPARATE_HOST_SIGNING",
            "behavioral_qualification": "NOT_TESTED",
        },
    }
    result["projection_sha256"] = _digest(_canonical(result))
    return result
