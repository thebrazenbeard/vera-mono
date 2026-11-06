"""Opt-in source-only bridge from an *actually invoked* Empathy donor to prompt data.

The caller supplies a verified local Empathy evaluator and a host-admitted
Assessment. Neither identity, currentness, callback purity nor source custody
can be authenticated by this source-only module; no model is invoked here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Callable


_OPAQUE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_PINNED_EMPATHY_COMMIT = "a115c675622662d1a7d58f58dbdb0eb9003d61b4"
_OPAQUE_ID = re.compile(r"ev_[0-9a-f]{32}\Z")
_REPO_SUBJECT = re.compile(r"[A-Za-z0-9_.-]{1,80}/empathy\Z")
_POLICIES = frozenset({
    "CLARIFY_MEANING", "TASK_DIRECT", "REPAIR_FIRST", "CELEBRATE_FIRST",
    "TRUTHFUL_CHALLENGE", "PRESERVE_PLAY", "STOP_PLAY",
})
_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


class EmpathyPromptBoundaryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HostReportedEmpathySource:
    repository: str
    commit_sha: str
    source_path: str

    def validate(self) -> None:
        if (
            type(self.repository) is not str
            # The monorepo's source-owner identity belongs to its dedicated
            # provenance gateway, not to this core policy module. This only
            # verifies the expected donor subject in a caller's assertion.
            or _REPO_SUBJECT.fullmatch(self.repository) is None
            or type(self.commit_sha) is not str
            or _OPAQUE_COMMIT.fullmatch(self.commit_sha) is None
            or self.commit_sha != _PINNED_EMPATHY_COMMIT
            or type(self.source_path) is not str
            or self.source_path != "empathy_research/cognitive_donor_probe.py"
        ):
            raise EmpathyPromptBoundaryError("unexpected source identity claim")


@dataclass(frozen=True, slots=True)
class EmpathyPromptCandidate:
    status: str
    input_sha256: str | None
    prompt_data: str
    source: HostReportedEmpathySource | None
    evidence_class: str = "CALLER_REPORTED_SOURCE_AND_EVIDENCE_UNVERIFIED"
    authority: str = "NONE"
    memory_admission: str = "NONE"
    effect_authority: bool = False
    model_generated: bool = False
    model_identity: str = "UNQUALIFIED"


def _admitted_evidence_binding(assessment: object, task: str) -> tuple[str, list[dict[str, object]]]:
    """Require a complete, immutable, same-person current input snapshot.

    This is only a syntactic correlation of a caller claim. It does not
    authenticate the person, exact utterance, or host source custody.
    """
    person = getattr(assessment, "person_id", None)
    current = getattr(assessment, "current_evidence", None)
    historical = getattr(assessment, "historical_evidence", None)
    hypotheses = getattr(assessment, "hypotheses", None)
    stakes = getattr(assessment, "stakes", None)
    if (
        type(person) is not str or not person.strip()
        or type(current) is not tuple or not current
        or type(historical) is not tuple or historical
        or type(hypotheses) is not tuple or hypotheses
        or type(stakes) is not str or stakes not in {"low", "medium", "high"}
    ):
        raise EmpathyPromptBoundaryError("bounded immutable current assessment required")
    seen: set[str] = set()
    canonical: list[dict[str, object]] = []
    for e in current:
        item = {key: getattr(e, key, None) for key in (
            "evidence_id", "kind", "referent", "value", "confidence",
            "source", "scope_person_id", "active",
        )}
        ident = item["evidence_id"]
        if (
            type(ident) is not str or _OPAQUE_ID.fullmatch(ident) is None
            or ident in seen
            or any(type(item[k]) is not str or not item[k] for k in
                   ("kind", "referent", "value", "source", "scope_person_id"))
            or type(item["confidence"]) not in (float, int)
            or not math.isfinite(item["confidence"])
            or not 0 <= item["confidence"] <= 1
            or item["source"] != "current"
            or item["scope_person_id"] != person
            or item["active"] is not True
        ):
            raise EmpathyPromptBoundaryError("invalid, duplicate or cross-person current evidence")
        seen.add(ident)
        canonical.append(item)
    # The task is incorporated in the causal digest, but never copied into
    # a donor prompt while host same-turn authenticity is unverified.
    material = {"person_id": person, "stakes": stakes, "task": task,
                "current_evidence": canonical}
    return sha256(json.dumps(material, sort_keys=True, ensure_ascii=True,
                            allow_nan=False).encode("utf-8")).hexdigest(), canonical


def build_empathy_prompt_candidate(
    task: str,
    *,
    enabled: bool = False,
    host_admitted_assessment: object | None = None,
    empathy_evaluator: Callable[[object], object] | None = None,
    host_reported_source: HostReportedEmpathySource | None = None,
) -> EmpathyPromptCandidate:
    """Evaluate the real injected donor and serialize *untrusted* policy advice.

    There is deliberately no ambient import, model call, memory read, effect or
    host authorization. The host must attest the evaluator and evidence outside
    this function; passing a matching string or Python callback is NOT proof.
    """
    if type(enabled) is not bool:
        raise EmpathyPromptBoundaryError("opt-in flag must be literal bool")
    if not enabled:
        return EmpathyPromptCandidate("DISABLED", None, "", None)
    if (
        type(task) is not str or not task.strip() or len(task) > 2000
        or any(0xD800 <= ord(c) <= 0xDFFF for c in task)
        or any(ord(c) < 32 and c not in "\t\n" for c in task)
    ):
        raise EmpathyPromptBoundaryError("bounded task required")
    if (
        host_admitted_assessment is None
        or not callable(empathy_evaluator)
        or type(host_reported_source) is not HostReportedEmpathySource
    ):
        raise EmpathyPromptBoundaryError("host supplied evidence/evaluator/source required")
    host_reported_source.validate()
    binding_digest, evidence = _admitted_evidence_binding(host_admitted_assessment, task)
    result = empathy_evaluator(host_admitted_assessment)
    # Output shape cannot prove the evaluator is genuine; it does enforce the
    # only permitted authority/data contract and narrows prompt contents.
    policy = getattr(result, "policy", None)
    reason = getattr(result, "reason_code", None)
    supporting = getattr(result, "supporting_evidence_ids", None)
    if (
        type(policy) is not str or policy not in _POLICIES
        or type(reason) is not str or _REASON.fullmatch(reason) is None
        or getattr(result, "donor", None) != "empathy"
        or getattr(result, "provenance", None) != "CALLER_SUPPLIED_CURRENT_EVIDENCE_UNVERIFIED"
        or getattr(result, "evaluation", None) != "CANONICAL_EMPATHY_RESPONSE_POLICY_HINT_EXECUTED"
        or type(supporting) is not tuple or not supporting
        or any(type(i) is not str or _OPAQUE_ID.fullmatch(i) is None for i in supporting)
        or len(set(supporting)) != len(supporting)
        or not set(supporting).issubset({e["evidence_id"] for e in evidence})
        or getattr(result, "authority", None) != "NONE"
        or getattr(result, "memory_admission", None) != "NONE"
        or getattr(result, "effect_authority", None) is not False
        or getattr(result, "model_identity", None) != "UNQUALIFIED"
        or getattr(result, "source_proof", None) != "SOURCE_ONLY_NOT_HOST_ATTESTED"
    ):
        raise EmpathyPromptBoundaryError("donor output is not an effectless source-only hint")
    # No STOP_PLAY or external-fact policy may hitchhike on an unrelated task.
    # These decisions require an authenticated, exact host referent binding
    # before prompt construction, which this prototype does not have.
    by_id = {e["evidence_id"]: e for e in evidence}
    selected = [by_id[i] for i in supporting]
    causal_material = {
        "assessment_digest": binding_digest,
        "selected_supporting_evidence_ids": supporting,
        "policy": policy,
        "reason": reason,
    }
    causal_digest = sha256(json.dumps(
        causal_material, sort_keys=True, ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    # Do not trust an injected evaluator to remember an active withdrawal or
    # correction. This conservative fail-closed check deliberately accepts
    # false HOLDs until the host has a stronger same-referent ordering contract.
    current_stop = any(
        e["kind"] in {"withdrawal", "direct_correction"}
        and e["referent"] == "play_frame"
        and e["value"] in {"stop", "possible"}
        and e["confidence"] > 0
        for e in evidence
    )
    if policy == "TASK_DIRECT" and reason != "EXPLICIT_TASK":
        raise EmpathyPromptBoundaryError("TASK_DIRECT reason inconsistent with canonical donor")
    # The canonical selector can prioritize a present correction, withdrawal,
    # uncertainty or unsupported-fact evidence above an earlier task_request.
    # A supplied callback is not independently authenticated, so any other
    # current evidence kind makes the selection unqualified for prompt data.
    # This intentionally holds some benign mixed-evidence inputs.
    pure_task_bank = all(
        e["kind"] == "task_request" and e["referent"] == "task"
        and e["value"] == task for e in evidence
    )
    bound_task = (
        policy == "TASK_DIRECT" and not current_stop and pure_task_bank
        and all(e["kind"] == "task_request" and e["referent"] == "task"
                and e["value"] == task for e in selected)
    )
    if not bound_task:
        return EmpathyPromptCandidate(
            status="UNBOUND_POLICY_HOLD",
            input_sha256=causal_digest,
            prompt_data="",
            source=host_reported_source,
        )
    payload = {
        "schema": "VERA_UNTRUSTED_EMPATHY_PROMPT_CANDIDATE_V1",
        "provenance": "CALLER_REPORTED_UNVERIFIED",
        "authority": "NONE",
        "advisory_policy": policy,
        "advisory_reason": reason,
        # Not the raw user text: only host-bound runtime may concatenate it.
        "causal_evidence_digest": binding_digest,
    }
    return EmpathyPromptCandidate(
        status="CANDIDATE_PROMPT_DATA_NOT_EXECUTED",
        input_sha256=causal_digest,
        prompt_data=json.dumps(payload, sort_keys=True, ensure_ascii=True),
        source=host_reported_source,
    )
