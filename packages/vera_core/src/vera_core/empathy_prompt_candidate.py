"""Opt-in source-only bridge from an *actually invoked* Empathy donor to prompt data.

The caller supplies a verified local Empathy evaluator and a host-admitted
Assessment. Neither identity, currentness, callback purity nor source custody
can be authenticated by this source-only module; no model is invoked here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Callable


_OPAQUE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
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
            or self.repository != "thebrazenbeard/empathy"
            or type(self.commit_sha) is not str
            or _OPAQUE_COMMIT.fullmatch(self.commit_sha) is None
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
    result = empathy_evaluator(host_admitted_assessment)
    # Output shape cannot prove the evaluator is genuine; it does enforce the
    # only permitted authority/data contract and narrows prompt contents.
    policy = getattr(result, "policy", None)
    reason = getattr(result, "reason_code", None)
    if (
        type(policy) is not str or policy not in _POLICIES
        or type(reason) is not str or _REASON.fullmatch(reason) is None
        or getattr(result, "authority", None) != "NONE"
        or getattr(result, "memory_admission", None) != "NONE"
        or getattr(result, "effect_authority", None) is not False
        or getattr(result, "model_identity", None) != "UNQUALIFIED"
        or getattr(result, "source_proof", None) != "SOURCE_ONLY_NOT_HOST_ATTESTED"
    ):
        raise EmpathyPromptBoundaryError("donor output is not an effectless source-only hint")
    payload = {
        "schema": "VERA_UNTRUSTED_EMPATHY_PROMPT_CANDIDATE_V1",
        "provenance": "CALLER_REPORTED_UNVERIFIED",
        "authority": "NONE",
        "advisory_policy": policy,
        "advisory_reason": reason,
        "user_task": task,
    }
    return EmpathyPromptCandidate(
        status="CANDIDATE_PROMPT_DATA_NOT_EXECUTED",
        input_sha256=sha256(task.encode("utf-8")).hexdigest(),
        prompt_data=json.dumps(payload, sort_keys=True, ensure_ascii=True),
        source=host_reported_source,
    )
