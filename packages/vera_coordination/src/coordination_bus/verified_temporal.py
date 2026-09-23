"""Single public verifier-bound evidence contract for coordination bus v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import hmac
import json
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .contracts import (
    ActorContext, CoordinationEventDraft, PERMISSION_ACKNOWLEDGE,
    PERMISSION_READ_SELF, PERMISSION_STATUS, canonicalize, validate_text,
    validate_workstream,
)
from .core import _receipted
from .temporal import (
    _TemporalCoordinationCore,
    TemporalCoordinationResult,
    TemporalEvidence,
)

EVIDENCE_ENVELOPE_SCHEMA = "VERA_TEMPORAL_EVIDENCE_ENVELOPE_V1"
DECISION_AUTHORITY_SCHEMA = "VERA_DECISION_AUTHORITY_ENVELOPE_V1"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _subject(prefix: str, body: Mapping[str, Any]) -> str:
    return f"{prefix}:" + sha256(_canonical_bytes(body)).hexdigest()


@dataclass(frozen=True)
class TemporalEvidenceEnvelope:
    schema: str
    issuer_id: str
    role: str
    subject: str
    evidence: TemporalEvidence
    verification_token: str

    def canonical_body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "issuer_id": self.issuer_id,
            "role": self.role,
            "subject": self.subject,
            "evidence": self.evidence.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        return canonicalize(asdict(self))


@runtime_checkable
class TemporalEvidenceVerifier(Protocol):
    def verify(
        self,
        envelope: TemporalEvidenceEnvelope,
        *,
        expected_role: str,
        expected_subject: str,
    ) -> bool:
        ...


class HmacTemporalEvidenceAuthority:
    """Reference single-use issuer/verifier using an externally held HMAC key."""

    def __init__(self, issuer_id: str, secret: bytes) -> None:
        validate_text(issuer_id, "issuer_id")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("secret must be at least 32 bytes")
        self.issuer_id = issuer_id
        self._secret = secret
        self._used_tokens: set[str] = set()

    def issue(
        self,
        evidence: TemporalEvidence,
        *,
        role: str,
        subject: str,
    ) -> TemporalEvidenceEnvelope:
        validate_text(role, "temporal role")
        validate_text(subject, "temporal subject")
        evidence.validate(role=role)
        unsigned = TemporalEvidenceEnvelope(
            schema=EVIDENCE_ENVELOPE_SCHEMA,
            issuer_id=self.issuer_id,
            role=role,
            subject=subject,
            evidence=evidence,
            verification_token="",
        )
        token = hmac.new(
            self._secret,
            _canonical_bytes(unsigned.canonical_body()),
            sha256,
        ).hexdigest()
        return replace(unsigned, verification_token=token)

    def verify(
        self,
        envelope: TemporalEvidenceEnvelope,
        *,
        expected_role: str,
        expected_subject: str,
    ) -> bool:
        try:
            if not isinstance(envelope, TemporalEvidenceEnvelope):
                return False
            if envelope.schema != EVIDENCE_ENVELOPE_SCHEMA:
                return False
            if envelope.issuer_id != self.issuer_id:
                return False
            if envelope.role != expected_role:
                return False
            if envelope.subject != expected_subject:
                return False
            envelope.evidence.validate(role=expected_role)
            expected = hmac.new(
                self._secret,
                _canonical_bytes(envelope.canonical_body()),
                sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, envelope.verification_token):
                return False
            replay_key = f"{envelope.issuer_id}:{envelope.verification_token}"
            if replay_key in self._used_tokens:
                return False
            self._used_tokens.add(replay_key)
            return True
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True)
class DecisionAuthorityEnvelope:
    """Opaque single-use authority bound to one exact DECISION draft."""

    schema: str
    issuer_id: str
    actor_workstream: str
    subject: str
    verification_token: str

    def canonical_body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "issuer_id": self.issuer_id,
            "actor_workstream": self.actor_workstream,
            "subject": self.subject,
        }

    def as_dict(self) -> dict[str, Any]:
        return canonicalize(asdict(self))


@runtime_checkable
class DecisionAuthorityVerifier(Protocol):
    def verify(
        self,
        envelope: DecisionAuthorityEnvelope,
        *,
        expected_actor_workstream: str,
        expected_subject: str,
    ) -> bool:
        ...


class HmacDecisionAuthority:
    """Reference host-owned issuer/verifier for exact, single-use decisions."""

    def __init__(self, issuer_id: str, secret: bytes) -> None:
        validate_text(issuer_id, "issuer_id")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("secret must be at least 32 bytes")
        self.issuer_id = issuer_id
        self._secret = secret
        self._used_tokens: set[str] = set()

    def issue(
        self,
        *,
        actor_workstream: str,
        draft: CoordinationEventDraft,
    ) -> DecisionAuthorityEnvelope:
        subject = decision_subject(actor_workstream, draft)
        unsigned = DecisionAuthorityEnvelope(
            schema=DECISION_AUTHORITY_SCHEMA,
            issuer_id=self.issuer_id,
            actor_workstream=actor_workstream,
            subject=subject,
            verification_token="",
        )
        token = hmac.new(
            self._secret,
            _canonical_bytes(unsigned.canonical_body()),
            sha256,
        ).hexdigest()
        return replace(unsigned, verification_token=token)

    def verify(
        self,
        envelope: DecisionAuthorityEnvelope,
        *,
        expected_actor_workstream: str,
        expected_subject: str,
    ) -> bool:
        try:
            if not isinstance(envelope, DecisionAuthorityEnvelope):
                return False
            if envelope.schema != DECISION_AUTHORITY_SCHEMA:
                return False
            if envelope.issuer_id != self.issuer_id:
                return False
            if envelope.actor_workstream != expected_actor_workstream:
                return False
            if envelope.subject != expected_subject:
                return False
            expected = hmac.new(
                self._secret,
                _canonical_bytes(envelope.canonical_body()),
                sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, envelope.verification_token):
                return False
            replay_key = f"{envelope.issuer_id}:{envelope.verification_token}"
            if replay_key in self._used_tokens:
                return False
            self._used_tokens.add(replay_key)
            return True
        except (TypeError, ValueError):
            return False


TemporalEvidenceInput = TemporalEvidence | TemporalEvidenceEnvelope | None
DecisionAuthorityInput = DecisionAuthorityEnvelope | None
ReceiptTimeProvider = Callable[[str, str], TemporalEvidenceInput]


def entry_checkpoint_subject(
    workstream: str,
    after_sequence: int,
    limit: int,
) -> str:
    return _subject("coordination-entry-v2", {
        "operation": "coordination_entry_checkpoint",
        "actor_workstream": workstream,
        "target_branch": workstream,
        "after_sequence": after_sequence,
        "limit": limit,
        "include_acknowledged": False,
    })


def acknowledgement_subject(
    event_id: str,
    *,
    actor_workstream: str,
    thread_key: str,
    summary: str,
    payload: Mapping[str, Any] | None = None,
    reference_data: Mapping[str, Any] | None = None,
) -> str:
    return _subject("coordination-acknowledgement-v2", {
        "operation": "coordination_acknowledge",
        "actor_workstream": actor_workstream,
        "source_event_id": event_id,
        "thread_key": thread_key,
        "summary": summary,
        "payload": canonicalize(payload or {}),
        "reference_data": canonicalize(reference_data or {}),
    })


def exit_checkpoint_subject(
    workstream: str,
    thread_key: str,
    target_branch: str | None,
    *,
    objective: str,
    summary: str,
    material: bool,
    status: str = "IN_PROGRESS",
    active_issue: str | None = None,
    acknowledges_event_id: str | None = None,
    reference_data: Mapping[str, Any] | None = None,
) -> str:
    return _subject("coordination-exit-v2", {
        "operation": "coordination_exit_checkpoint",
        "actor_workstream": workstream,
        "thread_key": thread_key,
        "target_branch": target_branch,
        "objective": objective,
        "summary": summary,
        "material": material,
        "status": status,
        "active_issue": active_issue,
        "acknowledges_event_id": acknowledges_event_id,
        "reference_data": canonicalize(reference_data or {}),
    })


def decision_subject(
    actor_workstream: str,
    draft: CoordinationEventDraft,
) -> str:
    """Bind authority to every field that can alter a DECISION's meaning."""

    validate_workstream(actor_workstream, "actor_workstream")
    draft.validate()
    if draft.event_type != "DECISION":
        raise ValueError("decision authority may bind only a DECISION draft")
    if draft.source_branch != actor_workstream:
        raise ValueError("decision source_branch must equal actor workstream")
    return _subject("coordination-decision-v1", {
        "operation": "coordination_post",
        "actor_workstream": actor_workstream,
        "thread_key": draft.thread_key,
        "source_branch": draft.source_branch,
        "target_branch": draft.target_branch,
        "event_type": draft.event_type,
        "status": draft.status,
        "objective": draft.objective,
        "summary": draft.summary,
        "active_issue": draft.active_issue,
        "requested_perspective": draft.requested_perspective,
        "supersedes_event_id": draft.supersedes_event_id,
        "acknowledges_event_id": draft.acknowledges_event_id,
        "payload": canonicalize(draft.payload),
        "reference_data": canonicalize(draft.reference_data),
    })


def receipt_subject(result: Any) -> str:
    receipt = result.receipt
    body = {
        "operation": receipt.operation,
        "result_class": receipt.result_class,
        "actor_workstream": receipt.actor_workstream,
        "thread_key": receipt.thread_key,
        "event_id": receipt.event_id,
        "event_sequence": receipt.event_sequence,
        "target_branch": receipt.target_branch,
        "base_result_hash": receipt.result_hash,
    }
    return "coordination-receipt:" + sha256(_canonical_bytes(body)).hexdigest()


class CoordinationBus(_TemporalCoordinationCore):
    """Only public bus: verifier-issued, role-bound, full-subject evidence."""

    def __init__(
        self,
        repository: Any,
        *,
        evidence_verifier: TemporalEvidenceVerifier | None = None,
        receipt_time_provider: ReceiptTimeProvider | None = None,
        decision_authority_verifier: DecisionAuthorityVerifier | None = None,
    ) -> None:
        super().__init__(repository, receipt_time_provider=None)
        self._evidence_verifier = evidence_verifier
        self._trusted_receipt_time_provider = receipt_time_provider
        self._decision_authority_verifier = decision_authority_verifier

    def _verified_claim(
        self,
        value: TemporalEvidenceInput,
        *,
        role: str,
        subject: str,
    ) -> TemporalEvidence | None:
        if value is None:
            return None
        if isinstance(value, TemporalEvidence):
            value.validate(role=role)
            if value.precision != "UNKNOWN":
                raise ValueError(
                    f"non-UNKNOWN {role} requires a verifier-issued "
                    "TemporalEvidenceEnvelope"
                )
            return value
        if not isinstance(value, TemporalEvidenceEnvelope):
            raise TypeError(
                f"{role} must be TemporalEvidence, "
                "TemporalEvidenceEnvelope, or None"
            )
        if self._evidence_verifier is None:
            raise ValueError(
                f"non-UNKNOWN {role} requires an injected trusted verifier"
            )
        if not self._evidence_verifier.verify(
            value,
            expected_role=role,
            expected_subject=subject,
        ):
            raise ValueError(
                f"temporal evidence verification failed for role {role!r} "
                f"and subject {subject!r}"
            )
        return value.evidence

    def _verify_decision_authority(
        self,
        value: DecisionAuthorityInput,
        *,
        actor_workstream: str,
        draft: CoordinationEventDraft,
    ) -> None:
        if not isinstance(value, DecisionAuthorityEnvelope):
            raise PermissionError(
                "DECISION requires a verifier-issued DecisionAuthorityEnvelope"
            )
        verifier = self._decision_authority_verifier
        if verifier is None:
            raise PermissionError(
                "DECISION requires an injected trusted decision-authority verifier"
            )
        subject = decision_subject(actor_workstream, draft)
        if not verifier.verify(
            value,
            expected_actor_workstream=actor_workstream,
            expected_subject=subject,
        ):
            raise PermissionError(
                "decision-authority verification failed for actor and draft subject"
            )

    def _wrap(self, result: Any, **kwargs: Any) -> TemporalCoordinationResult:
        wrapped = super()._wrap(result, **kwargs)
        provider = self._trusted_receipt_time_provider
        if provider is None:
            return wrapped
        subject = receipt_subject(result)
        try:
            candidate = provider("receipt_time", subject)
            verified = self._verified_claim(
                candidate,
                role="receipt_time",
                subject=subject,
            )
            receipt_time = (
                verified
                if verified is not None
                else TemporalEvidence.unknown("RECEIPT_TIME_UNAVAILABLE")
            )
        except (TypeError, ValueError):
            receipt_time = TemporalEvidence.unknown(
                "UNVERIFIED_RECEIPT_TIME_REJECTED"
            )
        return replace(
            wrapped,
            receipt=replace(wrapped.receipt, receipt_time=receipt_time),
        )

    @_receipted("coordination_post")
    def coordination_post(
        self,
        actor: ActorContext,
        draft: CoordinationEventDraft,
        *,
        decision_authority: DecisionAuthorityInput = None,
    ) -> TemporalCoordinationResult:
        actor.validate()
        draft.validate()
        if draft.event_type == "DECISION":
            if draft.source_branch != actor.canonical_workstream:
                raise PermissionError("source_branch must equal actor workstream")
            self._verify_decision_authority(
                decision_authority,
                actor_workstream=actor.canonical_workstream,
                draft=draft,
            )
            return self._append("coordination_post", actor, draft)
        if decision_authority is not None:
            raise ValueError("decision authority may be supplied only for DECISION")
        self._authorize_generic_post(actor, draft)
        return self._append("coordination_post", actor, draft)

    @_receipted("coordination_entry_checkpoint")
    def entry_checkpoint(
        self,
        actor: ActorContext,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        entry_time: TemporalEvidenceInput = None,
        retrieval_time: TemporalEvidenceInput = None,
    ) -> TemporalCoordinationResult:
        actor.validate()
        actor.require(PERMISSION_READ_SELF)
        workstream = actor.canonical_workstream
        subject = entry_checkpoint_subject(workstream, after_sequence, limit)
        entry = self._verified_claim(
            entry_time,
            role="entry_time",
            subject=subject,
        )
        retrieval = self._verified_claim(
            retrieval_time,
            role="retrieval_time",
            subject=subject,
        )
        return _TemporalCoordinationCore.entry_checkpoint(
            self,
            actor,
            after_sequence=after_sequence,
            limit=limit,
            entry_time=entry,
            retrieval_time=retrieval,
        )

    @_receipted("coordination_acknowledge")
    def coordination_acknowledge(
        self,
        actor: ActorContext,
        *,
        event_id: str,
        summary: str,
        acknowledgement_time: TemporalEvidenceInput = None,
        consumption_time: TemporalEvidenceInput = None,
        payload: Mapping[str, Any] | None = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> TemporalCoordinationResult:
        actor.require(PERMISSION_ACKNOWLEDGE)
        original = self._event(event_id)
        self._addressed_target(actor, original)
        subject = acknowledgement_subject(
            event_id,
            actor_workstream=actor.canonical_workstream,
            thread_key=original.thread_key,
            summary=summary,
            payload=payload,
            reference_data=reference_data,
        )
        acknowledgement = self._verified_claim(
            acknowledgement_time,
            role="acknowledgement_time",
            subject=subject,
        )
        consumption = self._verified_claim(
            consumption_time,
            role="consumption_time",
            subject=subject,
        )
        return _TemporalCoordinationCore.coordination_acknowledge(
            self,
            actor,
            event_id=event_id,
            summary=summary,
            acknowledgement_time=acknowledgement,
            consumption_time=consumption,
            payload=payload,
            reference_data=reference_data,
        )

    @_receipted("coordination_exit_checkpoint")
    def exit_checkpoint(
        self,
        actor: ActorContext,
        *,
        thread_key: str,
        target_branch: str | None,
        objective: str,
        summary: str,
        material: bool,
        status: str = "IN_PROGRESS",
        active_issue: str | None = None,
        acknowledges_event_id: str | None = None,
        event_time: TemporalEvidenceInput = None,
        state_time: TemporalEvidenceInput = None,
        reference_data: Mapping[str, Any] | None = None,
    ) -> TemporalCoordinationResult:
        actor.validate()
        if material:
            actor.require(PERMISSION_STATUS)
        subject = exit_checkpoint_subject(
            actor.canonical_workstream,
            thread_key,
            target_branch,
            objective=objective,
            summary=summary,
            material=material,
            status=status,
            active_issue=active_issue,
            acknowledges_event_id=acknowledges_event_id,
            reference_data=reference_data,
        )
        event = self._verified_claim(
            event_time,
            role="event_time",
            subject=subject,
        )
        state = self._verified_claim(
            state_time,
            role="state_time",
            subject=subject,
        )
        return _TemporalCoordinationCore.exit_checkpoint(
            self,
            actor,
            thread_key=thread_key,
            target_branch=target_branch,
            objective=objective,
            summary=summary,
            material=material,
            status=status,
            active_issue=active_issue,
            acknowledges_event_id=acknowledges_event_id,
            event_time=event,
            state_time=state,
            reference_data=reference_data,
        )
