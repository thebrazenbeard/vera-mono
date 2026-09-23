from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .jsonvalue import freeze_json, thaw_json
from .types import Address, EffectClass, Performative, SecurityProfile

PROTOCOL = "INTRANEL/1"
MAX_TOKEN_LENGTH = 256
MAX_SCALAR_STRING_BYTES = 4_096
MAX_LIST_ITEMS = 64
MAX_MESSAGE_BYTES = 65_536

_FIELDS = {
    "protocol",
    "origin",
    "actor",
    "target",
    "reply_to",
    "message_id",
    "operation_id",
    "target_operation_id",
    "parent_message_id",
    "conversation_id",
    "performative",
    "subject",
    "exact_subject",
    "payload",
    "authority_claim_ref",
    "constraints",
    "prohibited_effects",
    "expected_response",
    "ack_required",
    "observed_at",
    "expires_at",
    "idempotency_key",
    "priority",
    "effect_class",
    "status",
    "error",
    "receipt",
    "security_profile",
    "capabilities",
    "provenance",
}
_REQUIRED = {
    "protocol",
    "origin",
    "actor",
    "target",
    "reply_to",
    "message_id",
    "conversation_id",
    "performative",
    "effect_class",
    "security_profile",
}


def _require_token(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_TOKEN_LENGTH
        or any(ch.isspace() for ch in value)
    ):
        raise ValueError(
            f"{field_name} must be a non-empty bounded token without whitespace"
        )
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string or null")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} contains invalid Unicode") from exc
    if len(encoded) > MAX_SCALAR_STRING_BYTES:
        raise ValueError(f"{field_name} exceeds size limit")
    return value


def _tuple_of_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array of strings")
    if len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} exceeds collection limit")
    return tuple(_optional_string(item, field_name) or "" for item in value)


def _parse_timestamp(
    value: Any, field_name: str
) -> tuple[str | None, datetime | None]:
    raw = _optional_string(value, field_name)
    if raw is None:
        return None, None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an offset-aware ISO 8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return raw, parsed


@dataclass(frozen=True, slots=True)
class IntranelMessage:
    protocol: str
    origin: Address
    actor: Address
    target: Address
    reply_to: Address
    message_id: str
    operation_id: str | None
    parent_message_id: str | None
    conversation_id: str
    performative: Performative
    subject: str | None
    exact_subject: str | None
    payload: Any
    authority_claim_ref: str | None
    constraints: tuple[str, ...] = field(default_factory=tuple)
    prohibited_effects: tuple[str, ...] = field(default_factory=tuple)
    expected_response: Performative | None = None
    ack_required: bool = False
    observed_at: str | None = None
    expires_at: str | None = None
    idempotency_key: str | None = None
    target_operation_id: str | None = None
    priority: int = 3
    effect_class: EffectClass = EffectClass.READ_ONLY
    status: str | None = None
    error: str | None = None
    receipt: Mapping[str, Any] | None = None
    security_profile: SecurityProfile = SecurityProfile.OPEN
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    provenance: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.protocol != PROTOCOL:
            raise ValueError(f"unsupported protocol: {self.protocol!r}")

        for name in ("origin", "actor", "target", "reply_to"):
            if not isinstance(getattr(self, name), Address):
                raise ValueError(f"{name} must be an Address")
        if not isinstance(self.performative, Performative):
            raise ValueError("performative must be a Performative")
        if not isinstance(self.effect_class, EffectClass):
            raise ValueError("effect_class must be an EffectClass")
        if not isinstance(self.security_profile, SecurityProfile):
            raise ValueError("security_profile must be a SecurityProfile")
        if self.expected_response is not None and not isinstance(
            self.expected_response, Performative
        ):
            raise ValueError("expected_response must be a Performative or null")
        if type(self.ack_required) is not bool:
            raise ValueError("ack_required must be boolean")

        _require_token(self.message_id, "message_id")
        _require_token(self.conversation_id, "conversation_id")
        for name in (
            "operation_id",
            "target_operation_id",
            "parent_message_id",
            "idempotency_key",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_token(value, name)

        for name in ("subject", "exact_subject", "authority_claim_ref", "status", "error"):
            _optional_string(getattr(self, name), name)
        for name in ("constraints", "prohibited_effects", "capabilities", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise ValueError(f"{name} must be an immutable tuple of strings")
            _tuple_of_strings(value, name)

        # Freeze semantic JSON immediately so external references cannot alter a
        # validated message or its content/operation digest later.
        object.__setattr__(self, "payload", freeze_json(self.payload, "payload"))
        if self.receipt is not None:
            frozen_receipt = freeze_json(self.receipt, "receipt")
            if not isinstance(frozen_receipt, Mapping):
                raise ValueError("receipt must be an object or null")
            object.__setattr__(self, "receipt", frozen_receipt)

        _, observed = _parse_timestamp(self.observed_at, "observed_at")
        _, expires = _parse_timestamp(self.expires_at, "expires_at")
        if observed is not None and expires is not None and expires <= observed:
            raise ValueError("expires_at must be later than observed_at")

        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or not 0 <= self.priority <= 4
        ):
            raise ValueError("priority must be an integer from 0 through 4")

        if self.performative is Performative.REVIEW and not self.exact_subject:
            raise ValueError("REVIEW requires exact_subject")

        mutating_execute = (
            self.performative is Performative.EXECUTE
            and self.effect_class is not EffectClass.READ_ONLY
        )
        if mutating_execute:
            for name in (
                "operation_id",
                "idempotency_key",
                "authority_claim_ref",
                "exact_subject",
            ):
                if not getattr(self, name):
                    raise ValueError(f"mutating EXECUTE requires {name}")

        if self.performative is Performative.CANCEL:
            if self.effect_class is EffectClass.READ_ONLY:
                raise ValueError("CANCEL must declare a mutation effect_class")
            for name in (
                "operation_id",
                "target_operation_id",
                "idempotency_key",
                "authority_claim_ref",
                "subject",
                "exact_subject",
            ):
                if not getattr(self, name):
                    raise ValueError(f"CANCEL requires {name}")

        # A RECEIPT message is a bound receipt *claim*. Admission/readback must
        # independently verify its contents before treating it as effect truth.
        if self.performative is Performative.RECEIPT:
            if not self.operation_id:
                raise ValueError("RECEIPT requires operation_id")
            if not self.exact_subject:
                raise ValueError("RECEIPT requires exact_subject")
            if self.receipt is None:
                raise ValueError("RECEIPT requires receipt")

        # Enforce a whole-message bound after normalization, before untrusted
        # semantic state can be admitted farther into the system.
        from .canonical import canonical_json_bytes

        if len(canonical_json_bytes(self)) > MAX_MESSAGE_BYTES:
            raise ValueError("message exceeds canonical size limit")

    def to_mapping(self) -> dict[str, Any]:
        """Return a fresh mutable wire mapping; internal semantic state stays frozen."""
        return {
            "protocol": self.protocol,
            "origin": str(self.origin),
            "actor": str(self.actor),
            "target": str(self.target),
            "reply_to": str(self.reply_to),
            "message_id": self.message_id,
            "operation_id": self.operation_id,
            "target_operation_id": self.target_operation_id,
            "parent_message_id": self.parent_message_id,
            "conversation_id": self.conversation_id,
            "performative": self.performative.value,
            "subject": self.subject,
            "exact_subject": self.exact_subject,
            "payload": thaw_json(self.payload),
            "authority_claim_ref": self.authority_claim_ref,
            "constraints": list(self.constraints),
            "prohibited_effects": list(self.prohibited_effects),
            "expected_response": (
                self.expected_response.value
                if self.expected_response is not None
                else None
            ),
            "ack_required": self.ack_required,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "idempotency_key": self.idempotency_key,
            "priority": self.priority,
            "effect_class": self.effect_class.value,
            "status": self.status,
            "error": self.error,
            "receipt": thaw_json(self.receipt) if self.receipt is not None else None,
            "security_profile": self.security_profile.value,
            "capabilities": list(self.capabilities),
            "provenance": list(self.provenance),
        }


def parse_message(mapping: Mapping[str, Any]) -> IntranelMessage:
    if not isinstance(mapping, Mapping):
        raise ValueError("Intranel message must be a mapping")

    keys = set(mapping)
    unknown = sorted(keys - _FIELDS)
    if unknown:
        raise ValueError("unknown field(s): " + ", ".join(unknown))
    missing = sorted(_REQUIRED - keys)
    if missing:
        raise ValueError("missing required field(s): " + ", ".join(missing))
    if mapping["protocol"] != PROTOCOL:
        raise ValueError(f"unsupported protocol: {mapping['protocol']!r}")

    try:
        performative = Performative(mapping["performative"])
        effect_class = EffectClass(mapping["effect_class"])
        security_profile = SecurityProfile(mapping["security_profile"])
        expected_raw = mapping.get("expected_response")
        expected_response = (
            Performative(expected_raw) if expected_raw is not None else None
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc

    ack_required = mapping.get("ack_required", False)
    if type(ack_required) is not bool:
        raise ValueError("ack_required must be boolean")

    observed_at, observed = _parse_timestamp(mapping.get("observed_at"), "observed_at")
    expires_at, expires = _parse_timestamp(mapping.get("expires_at"), "expires_at")
    if observed is not None and expires is not None and expires <= observed:
        raise ValueError("expires_at must be later than observed_at")

    receipt = mapping.get("receipt")
    if receipt is not None and not isinstance(receipt, Mapping):
        raise ValueError("receipt must be an object or null")

    return IntranelMessage(
        protocol=PROTOCOL,
        origin=Address.parse(mapping["origin"]),
        actor=Address.parse(mapping["actor"]),
        target=Address.parse(mapping["target"]),
        reply_to=Address.parse(mapping["reply_to"]),
        message_id=mapping["message_id"],
        operation_id=mapping.get("operation_id"),
        target_operation_id=mapping.get("target_operation_id"),
        parent_message_id=mapping.get("parent_message_id"),
        conversation_id=mapping["conversation_id"],
        performative=performative,
        subject=_optional_string(mapping.get("subject"), "subject"),
        exact_subject=_optional_string(mapping.get("exact_subject"), "exact_subject"),
        payload=mapping.get("payload"),
        authority_claim_ref=_optional_string(
            mapping.get("authority_claim_ref"), "authority_claim_ref"
        ),
        constraints=_tuple_of_strings(mapping.get("constraints"), "constraints"),
        prohibited_effects=_tuple_of_strings(
            mapping.get("prohibited_effects"), "prohibited_effects"
        ),
        expected_response=expected_response,
        ack_required=ack_required,
        observed_at=observed_at,
        expires_at=expires_at,
        idempotency_key=mapping.get("idempotency_key"),
        priority=mapping.get("priority", 3),
        effect_class=effect_class,
        status=_optional_string(mapping.get("status"), "status"),
        error=_optional_string(mapping.get("error"), "error"),
        receipt=receipt,
        security_profile=security_profile,
        capabilities=_tuple_of_strings(mapping.get("capabilities"), "capabilities"),
        provenance=_tuple_of_strings(mapping.get("provenance"), "provenance"),
    )
