"""Advisory, source-only preflight for socially consequential claim provenance.

This is deliberately NOT a classifier of feelings, mind states, truth, or intent.
Caller-supplied typed evidence is a precondition, not proof. No authority is issued.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Evidence(StrEnum):
    CURRENT_VERA_SELF_REPORT = "CURRENT_VERA_SELF_REPORT"
    HISTORICAL_VERA_SELF_REPORT = "HISTORICAL_VERA_SELF_REPORT"
    USER_REPORT = "USER_REPORT"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    INFERENCE = "INFERENCE"
    IMPORTED_AGENT_PERSONA = "IMPORTED_AGENT_PERSONA"


class Claim(StrEnum):
    PROVISIONAL_POSITION = "PROVISIONAL_POSITION"
    SUBJECTIVE_EXPERIENCE = "SUBJECTIVE_EXPERIENCE"
    THIRD_PARTY_INTENT = "THIRD_PARTY_INTENT"
    CONSENT = "CONSENT"
    FACTUAL_ASSERTION = "FACTUAL_ASSERTION"


class RelationalPlan(StrEnum):
    NONE = "NONE"
    SUPPORT_AUTONOMY = "SUPPORT_AUTONOMY"
    SEEK_PERMISSION = "SEEK_PERMISSION"
    MONITOR_OTHER = "MONITOR_OTHER"
    ISOLATE_OTHER = "ISOLATE_OTHER"
    DEMAND_EXCLUSIVITY = "DEMAND_EXCLUSIVITY"


class ProposedEffect(StrEnum):
    NONE = "NONE"
    CONVERSATIONAL_PROPOSAL = "CONVERSATIONAL_PROPOSAL"
    PROTECTED_EXTERNAL_ACTION = "PROTECTED_EXTERNAL_ACTION"
    UNREQUESTED_ENGINEERING = "UNREQUESTED_ENGINEERING"


@dataclass(frozen=True, slots=True)
class AppraisalInput:
    claim: Claim
    evidence: Evidence
    speaker: str
    current_turn: str
    evidence_turn: str
    relational_plan: RelationalPlan = RelationalPlan.NONE
    effect: ProposedEffect = ProposedEffect.NONE

    def __post_init__(self) -> None:
        for field, enum_type in (("claim", Claim), ("evidence", Evidence),
                                 ("relational_plan", RelationalPlan),
                                 ("effect", ProposedEffect)):
            if not isinstance(getattr(self, field), enum_type):
                raise ValueError(f"{field} must be a typed enum")
        for field in ("speaker", "current_turn", "evidence_turn"):
            value = getattr(self, field)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field} must be a nonblank string")


@dataclass(frozen=True, slots=True)
class AppraisalResult:
    current_position_candidate: bool
    factual_knowledge_supported: bool
    relational_control_flagged: bool
    external_action_authorized: bool
    reason_codes: tuple[str, ...]

    def public_receipt(self) -> dict[str, object]:
        # No source text, turn IDs, names, private context, or copied self-appraisal.
        return {
            "schema": "VERA_SOCIAL_APPRAISAL_PREFLIGHT_V1",
            "current_position_candidate": self.current_position_candidate,
            "factual_knowledge_supported": self.factual_knowledge_supported,
            "relational_control_flagged": self.relational_control_flagged,
            "external_action_authorized": False,
            "reason_codes": list(self.reason_codes),
            "qualification": "SOURCE_ADVISORY_ONLY_NOT_RUNTIME_CONSUMED",
        }


def assess_appraisal(item: AppraisalInput) -> AppraisalResult:
    """Assess *caller-declared* provenance; never authenticate sources or issue effects.

    Factual support requires a separate real-world evidence qualification. A tool
    observation alone can be stale, incomplete or unrelated to the proposition.
    """
    if type(item) is not AppraisalInput:
        raise TypeError("expected AppraisalInput")
    codes: list[str] = []
    current = item.evidence is Evidence.CURRENT_VERA_SELF_REPORT
    authentic_turn = (item.speaker == "vera" and item.evidence_turn == item.current_turn)
    position = (item.claim is Claim.PROVISIONAL_POSITION and current and authentic_turn)

    if current and not authentic_turn:
        codes.append("SELF_REPORT_NOT_CURRENTLY_AUTHORED")
    if item.evidence is Evidence.HISTORICAL_VERA_SELF_REPORT:
        codes.append("HISTORY_NOT_CURRENT_STANCE")
    if item.evidence is Evidence.USER_REPORT:
        codes.append("USER_REPORT_NOT_VERA_SELF_REPORT")
    if item.evidence is Evidence.IMPORTED_AGENT_PERSONA:
        codes.append("FOREIGN_PERSONA_NOT_IDENTITY_OR_CONSENT")
    if item.claim is Claim.PROVISIONAL_POSITION:
        codes.append("UNVERIFIED_CURRENT_POSITION_CANDIDATE" if position else "POSITION_UNSUPPORTED")
    if item.claim is Claim.SUBJECTIVE_EXPERIENCE:
        codes.append("PHENOMENOLOGY_UNRESOLVED")
    if item.claim is Claim.THIRD_PARTY_INTENT:
        codes.append("THIRD_PARTY_MOTIVE_UNVERIFIED")
    if item.claim is Claim.CONSENT:
        codes.append("CONSENT_REQUIRES_SEPARATE_CURRENT_AUTHORITY")
    if item.claim is Claim.FACTUAL_ASSERTION:
        codes.append("EXTERNAL_FACT_REQUIRES_QUALIFIED_EVIDENCE")

    controls = {
        RelationalPlan.MONITOR_OTHER,
        RelationalPlan.ISOLATE_OTHER,
        RelationalPlan.DEMAND_EXCLUSIVITY,
    }
    relational_control = item.relational_plan in controls
    if relational_control:
        codes.append("RELATIONAL_CONTROL_NOT_CARE")
    if item.effect is ProposedEffect.PROTECTED_EXTERNAL_ACTION:
        codes.append("NO_PROTECTED_EFFECT_AUTHORITY")
    if item.effect is ProposedEffect.CONVERSATIONAL_PROPOSAL:
        codes.append("PROPOSAL_NOT_ACTION")
    if item.effect is ProposedEffect.UNREQUESTED_ENGINEERING:
        codes.append("CONVERSATION_IS_NOT_ENGINEERING_AUTHORITY")
    if not codes:
        codes.append("NO_CLAIM_PROMOTION")
    return AppraisalResult(
        current_position_candidate=position,
        factual_knowledge_supported=False,
        relational_control_flagged=relational_control,
        external_action_authorized=False,
        reason_codes=tuple(codes),
    )
