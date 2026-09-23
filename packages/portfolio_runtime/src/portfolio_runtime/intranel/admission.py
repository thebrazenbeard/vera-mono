from __future__ import annotations

from dataclasses import dataclass, fields, replace
import re

from .canonical import content_digest
from .message import IntranelMessage
from .types import AdmissionDecision, EffectClass, Performative

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TRISTATE_FIELDS = {
    "origin_authenticated",
    "actor_authenticated",
    "authority_valid",
    "exact_subject_valid",
    "replay_fresh",
    "capabilities_supported",
    "constraints_satisfied",
    "prohibited_effects_clear",
    "transport_security_satisfied",
}


@dataclass(frozen=True, slots=True)
class ReceiverEvidence:
    """Receiver-owned admission evidence bound to one exact Intranel message."""

    message_digest: str
    operation_digest: str | None
    origin: str
    actor: str
    target: str
    exact_subject: str | None
    authority_claim_ref: str | None
    effective_effect_class: EffectClass | None
    origin_authenticated: bool | None
    actor_authenticated: bool | None
    authority_valid: bool | None
    exact_subject_valid: bool | None
    replay_fresh: bool | None
    capabilities_supported: bool | None
    constraints_satisfied: bool | None
    prohibited_effects_clear: bool | None
    transport_security_satisfied: bool | None

    def __post_init__(self) -> None:
        if _DIGEST_RE.fullmatch(self.message_digest or "") is None:
            raise ValueError("message_digest must be a lowercase SHA-256 digest")
        if (
            self.operation_digest is not None
            and _DIGEST_RE.fullmatch(self.operation_digest) is None
        ):
            raise ValueError(
                "operation_digest must be a lowercase SHA-256 digest or null"
            )
        for name in ("origin", "actor", "target"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} binding must be a non-empty string")
        if self.exact_subject is not None and (
            not isinstance(self.exact_subject, str) or not self.exact_subject
        ):
            raise ValueError("exact_subject binding must be string or null")
        if self.authority_claim_ref is not None and (
            not isinstance(self.authority_claim_ref, str)
            or not self.authority_claim_ref
        ):
            raise ValueError("authority_claim_ref binding must be string or null")
        if self.effective_effect_class is not None and not isinstance(
            self.effective_effect_class, EffectClass
        ):
            raise ValueError("effective_effect_class must be an EffectClass or null")
        for item in fields(self):
            if item.name in _TRISTATE_FIELDS:
                value = getattr(self, item.name)
                if value is not None and type(value) is not bool:
                    raise ValueError(f"{item.name} must be true, false, or null")

    @classmethod
    def bind(
        cls,
        message: IntranelMessage,
        *,
        effective_effect_class: EffectClass | None,
        origin_authenticated: bool | None,
        actor_authenticated: bool | None,
        authority_valid: bool | None,
        exact_subject_valid: bool | None,
        replay_fresh: bool | None,
        capabilities_supported: bool | None,
        constraints_satisfied: bool | None,
        prohibited_effects_clear: bool | None,
        transport_security_satisfied: bool | None,
    ) -> "ReceiverEvidence":
        """Bind receiver-owned checks to the exact message being admitted."""
        return cls(
            message_digest=content_digest(message),
            operation_digest=(
                operation_digest(message) if message.operation_id is not None else None
            ),
            origin=str(message.origin),
            actor=str(message.actor),
            target=str(message.target),
            exact_subject=message.exact_subject,
            authority_claim_ref=message.authority_claim_ref,
            effective_effect_class=effective_effect_class,
            origin_authenticated=origin_authenticated,
            actor_authenticated=actor_authenticated,
            authority_valid=authority_valid,
            exact_subject_valid=exact_subject_valid,
            replay_fresh=replay_fresh,
            capabilities_supported=capabilities_supported,
            constraints_satisfied=constraints_satisfied,
            prohibited_effects_clear=prohibited_effects_clear,
            transport_security_satisfied=transport_security_satisfied,
        )

    def replace(self, **changes: object) -> "ReceiverEvidence":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    idempotency_key: str
    semantic_digest: str
    completed: bool

    def __post_init__(self) -> None:
        for name in ("operation_id", "idempotency_key"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or any(ch.isspace() for ch in value)
            ):
                raise ValueError(f"{name} must be a non-empty token")
        if _DIGEST_RE.fullmatch(self.semantic_digest or "") is None:
            raise ValueError("semantic_digest must be a lowercase SHA-256 digest")
        if type(self.completed) is not bool:
            raise ValueError("completed must be boolean")


@dataclass(frozen=True, slots=True)
class CancellationEvidence:
    """Receiver-observed state for the operation targeted by a CANCEL request."""

    target_operation_id: str
    exact_subject: str
    cancellable: bool | None

    def __post_init__(self) -> None:
        if not isinstance(self.target_operation_id, str) or not self.target_operation_id:
            raise ValueError("target_operation_id required")
        if not isinstance(self.exact_subject, str) or not self.exact_subject:
            raise ValueError("exact_subject required")
        if self.cancellable is not None and type(self.cancellable) is not bool:
            raise ValueError("cancellable must be true, false, or null")


def operation_digest(message: IntranelMessage) -> str:
    """Digest logical operation semantics, excluding legitimate relay metadata."""
    operation = {
        "protocol": message.protocol,
        "origin": str(message.origin),
        "target": str(message.target),
        "operation_id": message.operation_id,
        "target_operation_id": message.target_operation_id,
        "conversation_id": message.conversation_id,
        "performative": message.performative.value,
        "subject": message.subject,
        "exact_subject": message.exact_subject,
        "payload": message.payload,
        "authority_claim_ref": message.authority_claim_ref,
        "constraints": list(message.constraints),
        "prohibited_effects": list(message.prohibited_effects),
        "idempotency_key": message.idempotency_key,
        "effect_class": message.effect_class.value,
        "capabilities": list(message.capabilities),
        "provenance": list(message.provenance),
    }
    return content_digest(operation)


def _binding_decision(
    message: IntranelMessage, evidence: ReceiverEvidence
) -> AdmissionDecision | None:
    if evidence.message_digest != content_digest(message):
        return AdmissionDecision.CONFLICT
    expected_operation_digest = (
        operation_digest(message) if message.operation_id is not None else None
    )
    if evidence.operation_digest != expected_operation_digest:
        return AdmissionDecision.CONFLICT
    if (
        evidence.origin != str(message.origin)
        or evidence.actor != str(message.actor)
        or evidence.target != str(message.target)
    ):
        return AdmissionDecision.CONFLICT
    if (
        evidence.exact_subject != message.exact_subject
        or evidence.authority_claim_ref != message.authority_claim_ref
    ):
        return AdmissionDecision.CONFLICT
    return None


def _tristate(
    value: bool | None, false_decision: AdmissionDecision
) -> AdmissionDecision | None:
    if value is None:
        return AdmissionDecision.QUARANTINE
    if value is False:
        return false_decision
    return None


def admit(
    message: IntranelMessage,
    evidence: ReceiverEvidence,
    prior_operation: OperationRecord | None = None,
    cancellation: CancellationEvidence | None = None,
) -> AdmissionDecision:
    """Return a fail-closed receiver admission decision for one exact message."""
    binding = _binding_decision(message, evidence)
    if binding is not None:
        return binding

    for value, false_decision in (
        (evidence.origin_authenticated, AdmissionDecision.REJECT),
        (evidence.actor_authenticated, AdmissionDecision.REJECT),
        (evidence.replay_fresh, AdmissionDecision.REJECT),
        (evidence.capabilities_supported, AdmissionDecision.REJECT),
        (evidence.transport_security_satisfied, AdmissionDecision.REJECT),
    ):
        decision = _tristate(value, false_decision)
        if decision is not None:
            return decision

    if message.exact_subject is not None:
        decision = _tristate(
            evidence.exact_subject_valid, AdmissionDecision.CONFLICT
        )
        if decision is not None:
            return decision

    if message.constraints:
        decision = _tristate(
            evidence.constraints_satisfied, AdmissionDecision.REJECT
        )
        if decision is not None:
            return decision

    if message.prohibited_effects:
        decision = _tristate(
            evidence.prohibited_effects_clear, AdmissionDecision.REJECT
        )
        if decision is not None:
            return decision

    effective_effect = evidence.effective_effect_class
    if message.performative in {Performative.EXECUTE, Performative.CANCEL}:
        if effective_effect is None:
            return AdmissionDecision.QUARANTINE
        if effective_effect is not message.effect_class:
            return AdmissionDecision.CONFLICT

    requires_authority = message.performative is Performative.CANCEL or (
        message.performative is Performative.EXECUTE
        and effective_effect is not EffectClass.READ_ONLY
    )
    if requires_authority:
        decision = _tristate(evidence.authority_valid, AdmissionDecision.REJECT)
        if decision is not None:
            return decision

    # Once identity, effect, and authority checks have passed, a verified-complete
    # identical operation is already settled. In particular, a retry of a
    # completed CANCEL must not depend on the target still being cancellable.
    if prior_operation is not None and message.operation_id == prior_operation.operation_id:
        if message.idempotency_key != prior_operation.idempotency_key:
            return AdmissionDecision.CONFLICT
        if operation_digest(message) != prior_operation.semantic_digest:
            return AdmissionDecision.CONFLICT
        if not prior_operation.completed:
            return AdmissionDecision.QUARANTINE
        return AdmissionDecision.DUPLICATE

    if message.performative is Performative.CANCEL:
        if cancellation is None:
            return AdmissionDecision.QUARANTINE
        if (
            cancellation.target_operation_id != message.target_operation_id
            or cancellation.exact_subject != message.exact_subject
        ):
            return AdmissionDecision.CONFLICT
        decision = _tristate(cancellation.cancellable, AdmissionDecision.REJECT)
        if decision is not None:
            return decision

    return AdmissionDecision.ALLOW
