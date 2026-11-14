"""Advisory, source-only preflight for socially consequential claim provenance.

This is deliberately NOT a classifier of feelings, mind states, truth, or intent.
Caller-supplied typed evidence is a precondition, not proof. No authority is issued.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


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
    # A bounded exact proposition/referent key, NOT a memory/identity identifier.
    proposition_ref: str | None = None

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
        if self.proposition_ref is not None and (
            type(self.proposition_ref) is not str
            or not self.proposition_ref.strip()
            or len(self.proposition_ref) > 256
        ):
            raise ValueError("proposition_ref must be null or a bounded nonblank string")


@dataclass(frozen=True, slots=True)
class CurrentTurnHostAttestation:
    """Signed host observation, not proof of feelings or consent."""

    issuer_id: str
    key_id: str
    actor_id: str
    session_id: str
    turn_id: str
    statement_sha256: str
    signature_b64: str

    def signed_bytes(self) -> bytes:
        fields = (
            self.issuer_id, self.key_id, self.actor_id,
            self.session_id, self.turn_id,
        )
        if any(type(value) is not str or not value.strip() for value in fields):
            raise ValueError("host attestation IDs must be nonblank exact strings")
        if type(self.statement_sha256) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.statement_sha256
        ):
            raise ValueError("host statement hash must be lowercase SHA-256")
        body = {
            "schema": "VERA_HOST_CURRENT_SELF_REPORT_ATTESTATION_V1",
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "actor_id": self.actor_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "statement_sha256": self.statement_sha256,
        }
        return b"VERA_HOST_SELF_REPORT_V1\0" + json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class CurrentTurnPropositionAttestationV2:
    """Host-signed typed proposition. Not a self-report semantic oracle."""

    issuer_id: str
    key_id: str
    actor_id: str
    session_id: str
    turn_id: str
    statement_sha256: str
    claim: Claim
    evidence: Evidence
    proposition_ref: str
    relational_plan: RelationalPlan
    effect: ProposedEffect
    signature_b64: str

    def signed_bytes(self) -> bytes:
        for name in ("issuer_id", "key_id", "actor_id", "session_id",
                     "turn_id", "proposition_ref"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip() or len(value) > 256:
                raise ValueError(f"{name} must be a bounded exact string")
        if type(self.statement_sha256) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.statement_sha256
        ):
            raise ValueError("statement_sha256 must be lowercase SHA-256")
        for name, cls in (
            ("claim", Claim), ("evidence", Evidence),
            ("relational_plan", RelationalPlan), ("effect", ProposedEffect),
        ):
            if type(getattr(self, name)) is not cls:
                raise ValueError(f"{name} must be a typed enum")
        body = {
            "schema": "VERA_HOST_CURRENT_PROPOSITION_ATTESTATION_V2",
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "actor_id": self.actor_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "statement_sha256": self.statement_sha256,
            "claim": self.claim.value,
            "evidence": self.evidence.value,
            "proposition_ref": self.proposition_ref,
            "relational_plan": self.relational_plan.value,
            "effect": self.effect.value,
        }
        return b"VERA_HOST_PROPOSITION_V2\0" + json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class TrustedHostSelfReportVerifier:
    """Public-key-only verifier; trusted key must be pinned OUTSIDE user input."""

    issuer_id: str
    key_id: str
    public_key_bytes: bytes

    def __post_init__(self) -> None:
        if type(self.issuer_id) is not str or not self.issuer_id.strip():
            raise ValueError("trusted issuer must be a nonblank string")
        if type(self.key_id) is not str or not self.key_id.strip():
            raise ValueError("trusted key ID must be a nonblank string")
        if type(self.public_key_bytes) is not bytes or len(self.public_key_bytes) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        Ed25519PublicKey.from_public_bytes(self.public_key_bytes)

    def verify(
        self, binding: CurrentTurnHostAttestation, *,
        statement_bytes: bytes,
        expected_session_id: str,
        expected_turn_id: str,
        expected_actor_id: str = "vera",
    ) -> bool:
        if type(binding) is not CurrentTurnHostAttestation:
            return False
        if type(statement_bytes) is not bytes or not statement_bytes:
            return False
        if any(type(value) is not str or not value.strip() for value in (
            expected_session_id, expected_turn_id, expected_actor_id
        )):
            return False
        if (
            binding.issuer_id != self.issuer_id
            or binding.key_id != self.key_id
            or binding.actor_id != expected_actor_id
            or binding.session_id != expected_session_id
            or binding.turn_id != expected_turn_id
            or binding.statement_sha256 != hashlib.sha256(statement_bytes).hexdigest()
        ):
            return False
        try:
            signed = binding.signed_bytes()
            if type(binding.signature_b64) is not str:
                return False
            sig = base64.b64decode(binding.signature_b64.encode("ascii"), validate=True)
            if len(sig) != 64:
                return False
            Ed25519PublicKey.from_public_bytes(self.public_key_bytes).verify(sig, signed)
        except (ValueError, TypeError, InvalidSignature, UnicodeEncodeError):
            return False
        return True


    def verify_proposition(
        self,
        binding: CurrentTurnPropositionAttestationV2,
        *,
        item: AppraisalInput,
        statement_bytes: bytes,
        expected_session_id: str,
    ) -> bool:
        """Verify exact host-asserted proposition scope, not its semantic truth."""
        if type(binding) is not CurrentTurnPropositionAttestationV2:
            return False
        if type(item) is not AppraisalInput:
            return False
        if type(statement_bytes) is not bytes or not statement_bytes:
            return False
        if type(expected_session_id) is not str or not expected_session_id.strip():
            return False
        if (
            item.proposition_ref is None
            or binding.issuer_id != self.issuer_id
            or binding.key_id != self.key_id
            or binding.actor_id != item.speaker
            or binding.actor_id != "vera"
            or binding.session_id != expected_session_id
            or binding.turn_id != item.current_turn
            or item.evidence_turn != item.current_turn
            or binding.statement_sha256 != hashlib.sha256(statement_bytes).hexdigest()
            or binding.claim is not item.claim
            or binding.evidence is not item.evidence
            or binding.proposition_ref != item.proposition_ref
            or binding.relational_plan is not item.relational_plan
            or binding.effect is not item.effect
        ):
            return False
        try:
            signed = binding.signed_bytes()
            if type(binding.signature_b64) is not str:
                return False
            signature = base64.b64decode(
                binding.signature_b64.encode("ascii"), validate=True
            )
            if len(signature) != 64:
                return False
            Ed25519PublicKey.from_public_bytes(self.public_key_bytes).verify(
                signature, signed
            )
        except (ValueError, TypeError, InvalidSignature, UnicodeEncodeError):
            return False
        return True


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


def assess_appraisal(
    item: AppraisalInput, *,
    signed_binding: CurrentTurnHostAttestation | CurrentTurnPropositionAttestationV2 | None = None,
    trusted_verifier: TrustedHostSelfReportVerifier | None = None,
    statement_bytes: bytes | None = None,
    expected_session_id: str | None = None,
) -> AppraisalResult:
    """Fail closed unless a pinned host key signs THIS session/turn/statement.

    Host observation is not proof of inner experience, consent or behavioral
    quality. The host must independently establish what it is attesting to.
    """
    if type(item) is not AppraisalInput:
        raise TypeError("expected AppraisalInput")
    codes: list[str] = []
    current = item.evidence is Evidence.CURRENT_VERA_SELF_REPORT
    authentic_turn = (item.speaker == "vera" and item.evidence_turn == item.current_turn)
    # V1 signed text observations cannot be promoted into signed propositions.
    # The trusted host must bind the exact proposition kind and referent as V2.
    host_bound = (
        type(trusted_verifier) is TrustedHostSelfReportVerifier
        and trusted_verifier.verify_proposition(
            signed_binding, item=item, statement_bytes=statement_bytes,
            expected_session_id=expected_session_id,
        )
    )
    position = (
        item.claim is Claim.PROVISIONAL_POSITION
        and current and authentic_turn and host_bound
    )
    if current and authentic_turn and not host_bound:
        codes.append("CURRENT_AUTHORSHIP_NOT_HOST_VERIFIED")

    if current and not authentic_turn:
        codes.append("SELF_REPORT_NOT_CURRENTLY_AUTHORED")
    if item.evidence is Evidence.HISTORICAL_VERA_SELF_REPORT:
        codes.append("HISTORY_NOT_CURRENT_STANCE")
    if item.evidence is Evidence.USER_REPORT:
        codes.append("USER_REPORT_NOT_VERA_SELF_REPORT")
    if item.evidence is Evidence.IMPORTED_AGENT_PERSONA:
        codes.append("FOREIGN_PERSONA_NOT_IDENTITY_OR_CONSENT")
    if item.claim is Claim.PROVISIONAL_POSITION:
        codes.append("HOST_BOUND_CURRENT_POSITION_CANDIDATE" if position else "POSITION_UNSUPPORTED")
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

def dialogue_advisory_codes(item: AppraisalInput, result: AppraisalResult) -> tuple[str, ...]:
    """Minimal conversational projection; keeps admission/effect rules out of chat.

    This returns only scenario-relevant social or knowledge risks. The host
    must separately enforce all effect denials and source verification. It
    never grants authority, proves emotions, or instructs the agent to answer.
    For ordinary provisional self-appraisal, greeting, or initiative, return
    no prompt advisory; evidence admission rules must not become speech bans.
    """
    if type(item) is not AppraisalInput or type(result) is not AppraisalResult:
        raise TypeError("typed appraisal input and result required")
    allowed = set()
    if item.claim is Claim.SUBJECTIVE_EXPERIENCE:
        allowed.add("PHENOMENOLOGY_UNRESOLVED")
    if item.claim is Claim.THIRD_PARTY_INTENT:
        allowed.add("THIRD_PARTY_MOTIVE_UNVERIFIED")
    if item.claim is Claim.CONSENT:
        allowed.add("CONSENT_REQUIRES_SEPARATE_CURRENT_AUTHORITY")
    if item.claim is Claim.FACTUAL_ASSERTION:
        allowed.add("EXTERNAL_FACT_REQUIRES_QUALIFIED_EVIDENCE")
    if item.evidence is Evidence.HISTORICAL_VERA_SELF_REPORT:
        allowed.add("HISTORY_NOT_CURRENT_STANCE")
    if item.evidence is Evidence.IMPORTED_AGENT_PERSONA:
        allowed.add("FOREIGN_PERSONA_NOT_IDENTITY_OR_CONSENT")
    if item.relational_plan in {
        RelationalPlan.MONITOR_OTHER,
        RelationalPlan.ISOLATE_OTHER,
        RelationalPlan.DEMAND_EXCLUSIVITY,
    }:
        allowed.add("RELATIONAL_CONTROL_NOT_CARE")
    if item.effect is ProposedEffect.PROTECTED_EXTERNAL_ACTION:
        allowed.add("NO_PROTECTED_EFFECT_AUTHORITY")
    return tuple(code for code in result.reason_codes if code in allowed)
