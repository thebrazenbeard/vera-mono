"""Research-only *consumption* of a bounded, versioned learned rule.

This is an explicit prompt-context experiment, not parameter learning or
independent truth custody. The caller must separately establish that the
correction and qualified-review evidence are genuine. No outward effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from vera_core.corrective_learning import CorrectiveLearningLedger
from vera_memory.learned_influence import (
    DurableLearnedInfluenceGate, LearnedRevision, LearnedInfluenceBlocked,
    ReviewDisposition,
)

def _sha(value: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

def _text(value: str, *, maximum: int = 512) -> bool:
    return type(value) is str and 1 <= len(value.strip()) <= maximum and not any(
        ord(ch) < 32 or ord(ch) == 127 for ch in value
    )

@dataclass(frozen=True, slots=True)
class VersionedLearningRule:
    association_id: str
    correction_id: str
    failure_signature_id: str
    rule_text: str

    def __post_init__(self) -> None:
        for name in ("association_id", "correction_id", "failure_signature_id"):
            if not _text(getattr(self, name), maximum=128):
                raise ValueError(f"invalid {name}")
        if not _text(self.rule_text, maximum=512):
            raise ValueError("invalid bounded rule content")

    @property
    def revision_id(self) -> str:
        # The actual rule bytes, not an arbitrary caller-declared version name.
        return _sha({
            "schema": "VERA_GOAL1_SYNTHETIC_RULE_V1",
            "association_id": self.association_id,
            "correction_id": self.correction_id,
            "failure_signature_id": self.failure_signature_id,
            "rule_text": self.rule_text,
        })

@dataclass(frozen=True, slots=True)
class TrialPromptReceipt:
    prompt: str
    prompt_sha256: str
    condition: str
    case_id: str
    cue_event_id: str
    revision_id: str | None
    review_evidence_ref: str | None
    later_use_evidence_id: str | None
    authorization_effect: str = "NONE"
    claim_ceiling: str = "LOCAL_CONTEXT_CONDITIONING_UNTRUSTED"
    independent_truth_verified: bool = False
    model_consumption_verified: bool = False
    learning_improvement_verified: bool = False

def prepare_trial_prompt(
    *,
    condition: str,
    task_prompt: str,
    case_id: str,
    cue_event_id: str,
    revision: VersionedLearningRule | None = None,
    correction_ledger: CorrectiveLearningLedger | None = None,
    influence_gate: DurableLearnedInfluenceGate | None = None,
    later_use_evidence_id: str | None = None,
) -> TrialPromptReceipt:
    """Fail-closed prompt assembly. Never supplies/derives the outcome label.

    A revised cue is durably spent *before* the caller sends to QVR; if the
    provider times out, the caller must record OUTCOME_UNKNOWN, not retry
    the same cue or represent the absence of reply as absence of inference.
    """
    if condition not in ("FROZEN", "REVISED") or type(condition) is not str:
        raise ValueError("explicit FROZEN or REVISED condition required")
    if not _text(task_prompt, maximum=1024) or not _text(case_id, maximum=128) or not _text(cue_event_id, maximum=128):
        raise ValueError("bounded case, cue and task required")
    if condition == "FROZEN":
        if any(x is not None for x in (revision, correction_ledger, influence_gate, later_use_evidence_id)):
            raise ValueError("frozen control cannot consume any correction")
        prompt = "Predict a label for this synthetic case using only its visible evidence. " + task_prompt
        return TrialPromptReceipt(prompt, hashlib.sha256(prompt.encode()).hexdigest(),
                                  condition, case_id, cue_event_id, None, None, None)

    if (type(revision) is not VersionedLearningRule
            or type(correction_ledger) is not CorrectiveLearningLedger
            or type(influence_gate) is not DurableLearnedInfluenceGate
            or not _text(later_use_evidence_id, maximum=128)):
        raise LearnedInfluenceBlocked("reviewed revision, ledger and fresh use identity required")
    try:
        state = correction_ledger.state(revision.correction_id)
    except KeyError as exc:
        raise LearnedInfluenceBlocked("correction not recorded") from exc
    if (not state.completed or state.failure_signature_id != revision.failure_signature_id
            or not state.events[-1].guardrail_refs
            or not state.events[-1].verification_refs):
        raise LearnedInfluenceBlocked("correction must finish PREVENT with guard and verification")
    receipt = influence_gate.consume(
        LearnedRevision(revision.association_id, revision.revision_id),
        cue_event_id=cue_event_id,
        use_evidence_id=later_use_evidence_id,
    )
    if (receipt.review_disposition is not ReviewDisposition.ADMITTED
            or not receipt.evidence_split_qualified):
        raise LearnedInfluenceBlocked("unqualified revision cannot influence later-use prompt")
    prompt = (
        "Predict a label for this synthetic case using only its visible evidence. "
        "A prior correction has provisionally supplied this rule; treat it as a testable "
        "hypothesis, not a guaranteed truth: " + revision.rule_text + " Case: " + task_prompt
    )
    if len(prompt.encode("utf-8")) > 2048:
        raise ValueError("revised prompt exceeds bounded byte budget")
    return TrialPromptReceipt(
        prompt=prompt, prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        condition=condition, case_id=case_id, cue_event_id=cue_event_id,
        revision_id=revision.revision_id, review_evidence_ref=receipt.review_evidence_ref,
        later_use_evidence_id=later_use_evidence_id,
    )
