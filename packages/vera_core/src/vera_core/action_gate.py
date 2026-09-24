from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import EffectFence, EffectFenceError, EffectReceipt, EffectState
from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope
from pc_connection.validation import utc_microseconds

from .coordination_command_journal import (
    CoordinationCommandJournal,
    CoordinationCommandJournalError,
    CoordinationCommandRecoveryAssessment,
)
from .lifecycle import (
    AcceptedLifecyclePermit,
    LifecycleActionDenied,
    NativeVeraLifecycle,
)
from .outbound_authority import (
    OutboundAuthorityError,
    PCJobAuthorityProof,
    PCJobAuthorityVerifier,
    ProviderAuthorityEnvelope,
    ProviderAuthorityVerifier,
    pc_authority_subject,
    provider_authority_subject,
    validate_pc_authorization_binding,
)
from .outbound_audit import OutboundExecutionAudit
from .outbound_trust import OutboundTrustRegistry


T = TypeVar("T")


class OutboundActionError(ValueError):
    pass


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise OutboundActionError("action mapping keys must be strings")
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_normalize(item) for item in value), key=repr)
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes_sha256": sha256_hex(value)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise OutboundActionError(
        f"unsupported action-bound value type: {type(value).__name__}"
    )


def _digest(value: Any) -> str:
    return sha256_hex(canonical_json_bytes(_normalize(value)))


@dataclass(frozen=True, slots=True)
class VerifiedAuthorityEvidence:
    evidence_digest: str
    details: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class OutboundEffectResult:
    effect_id: str
    effect_kind: str
    request_digest: str
    lifecycle_permit_digest: str
    result_digest: str
    fence_receipt: EffectReceipt
    value: Any


class LifecycleEffectGateway:
    """Only qualified path for PC/provider effects from accepted lifecycle state."""

    def __init__(
        self,
        *,
        lifecycle: NativeVeraLifecycle,
        fence: EffectFence,
        pc_authority_verifier: PCJobAuthorityVerifier | None = None,
        provider_authority_verifiers: Mapping[
            str, ProviderAuthorityVerifier
        ] | None = None,
        outbound_trust_registry: OutboundTrustRegistry | None = None,
        audit: OutboundExecutionAudit | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.lifecycle = lifecycle
        self.fence = fence
        if (
            pc_authority_verifier is not None
            and not isinstance(pc_authority_verifier, PCJobAuthorityVerifier)
        ):
            raise TypeError(
                "pc_authority_verifier must satisfy PCJobAuthorityVerifier"
            )
        self._pc_authority_verifier = pc_authority_verifier
        self._outbound_trust_registry = outbound_trust_registry
        resolved_audit = (
            audit
            if audit is not None
            else getattr(lifecycle, "effect_audit", None)
        )
        if (
            resolved_audit is not None
            and type(resolved_audit) is not OutboundExecutionAudit
        ):
            raise TypeError("audit must be exact OutboundExecutionAudit")
        self.audit = resolved_audit
        registry = dict(provider_authority_verifiers or {})
        for provider_id, verifier in registry.items():
            if type(provider_id) is not str or not provider_id:
                raise ValueError(
                    "provider authority registry keys must be non-empty strings"
                )
            if not isinstance(verifier, ProviderAuthorityVerifier):
                raise TypeError(
                    f"provider verifier for {provider_id!r} does not satisfy protocol"
                )
            if verifier.provider_id != provider_id:
                raise TypeError(
                    f"provider verifier identity mismatch for {provider_id!r}"
                )
        self._provider_authority_verifiers = registry
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def effect_request_digest(
        *,
        permit: AcceptedLifecyclePermit,
        effect_id: str,
        effect_kind: str,
        request_payload: Any,
    ) -> str:
        return _digest(
            {
                "schema": "VERA_MONO_LIFECYCLE_BOUND_EFFECT_REQUEST_V1",
                "effect_id": effect_id,
                "effect_kind": effect_kind,
                "request_payload": _normalize(request_payload),
                "lifecycle_permit_digest": permit.permit_digest,
            }
        )

    @staticmethod
    def mechanical_permit_digest(
        *,
        permit: AcceptedLifecyclePermit,
        effect_id: str,
        request_digest: str,
    ) -> str:
        return _digest(
            {
                "schema": "VERA_MONO_EFFECT_MECHANICAL_PERMIT_V1",
                "effect_id": effect_id,
                "request_digest": request_digest,
                "lifecycle_permit_digest": permit.permit_digest,
            }
        )

    def _dispatch_verified(
        self,
        *,
        permit: AcceptedLifecyclePermit,
        effect_id: str,
        effect_kind: str,
        request_payload: Any,
        verify_authority: Callable[[], VerifiedAuthorityEvidence],
        execute: Callable[[], T],
    ) -> OutboundEffectResult:
        if type(effect_id) is not str or not effect_id:
            raise OutboundActionError("effect_id must be a non-empty exact string")
        if type(effect_kind) is not str or not effect_kind:
            raise OutboundActionError("effect_kind must be a non-empty exact string")
        request_digest = self.effect_request_digest(
            permit=permit,
            effect_id=effect_id,
            effect_kind=effect_kind,
            request_payload=request_payload,
        )
        mechanical_permit_digest = self.mechanical_permit_digest(
            permit=permit,
            effect_id=effect_id,
            request_digest=request_digest,
        )

        with self.lifecycle.action_lock():
            trust_guard = (
                nullcontext()
                if self._outbound_trust_registry is None
                else self._outbound_trust_registry.action_lock()
            )
            with trust_guard:
                self.fence.assert_clear()
                self.lifecycle.validate_action_permit(permit)
                authority_evidence = verify_authority()
                if type(authority_evidence) is not VerifiedAuthorityEvidence:
                    raise OutboundActionError(
                        "authority verifier must return VerifiedAuthorityEvidence"
                    )
                authority_evidence_digest = self._require_sha256(
                    authority_evidence.evidence_digest,
                    "authority_evidence_digest",
                )
                if self.audit is not None:
                    self.audit.append(
                        effect_id=effect_id,
                        effect_kind=effect_kind,
                        event_type="AUTHORITY_VERIFIED",
                        payload={
                            "request_digest": request_digest,
                            "mechanical_permit_digest": mechanical_permit_digest,
                            "lifecycle_permit": {
                                **permit.canonical_body(),
                                "permit_digest": permit.permit_digest,
                            },
                            "authority_evidence_digest": authority_evidence_digest,
                            "authority_details": _normalize(
                                authority_evidence.details
                            ),
                        },
                    )
                reserved = self.fence.reserve(
                    effect_id=effect_id,
                    request_digest=request_digest,
                    mechanical_permit_digest=mechanical_permit_digest,
                    authority_evidence_digest=authority_evidence_digest,
                    currentness_evidence_digest=permit.permit_digest,
                )
                if self.audit is not None:
                    self.audit.append(
                        effect_id=effect_id,
                        effect_kind=effect_kind,
                        event_type="RESERVED",
                        payload={
                            "request_digest": reserved.request_digest,
                            "mechanical_permit_digest": (
                                reserved.mechanical_permit_digest
                            ),
                            "authority_evidence_digest": (
                                reserved.authority_evidence_digest
                            ),
                            "currentness_evidence_digest": (
                                reserved.currentness_evidence_digest
                            ),
                        },
                    )
                # Re-check after durable reservation and before the single-use
                # dispatch claim. The shared lifecycle lock prevents a canonical
                # lifecycle transition from interleaving with execution.
                self.lifecycle.validate_action_permit(permit)
                executing = self.fence.claim_dispatch(
                    effect_id=effect_id,
                    request_digest=request_digest,
                    mechanical_permit_digest=mechanical_permit_digest,
                    authority_evidence_digest=authority_evidence_digest,
                    currentness_evidence_digest=permit.permit_digest,
                )
                if self.audit is not None:
                    self.audit.append(
                        effect_id=effect_id,
                        effect_kind=effect_kind,
                        event_type="EXECUTING",
                        payload={
                            "request_digest": executing.request_digest,
                            "mechanical_permit_digest": (
                                executing.mechanical_permit_digest
                            ),
                            "authority_evidence_digest": (
                                executing.authority_evidence_digest
                            ),
                            "currentness_evidence_digest": (
                                executing.currentness_evidence_digest
                            ),
                        },
                    )
                try:
                    value = execute()
                    result_digest = _digest(
                        {
                            "schema": "VERA_MONO_EFFECT_RESULT_V1",
                            "effect_id": effect_id,
                            "effect_kind": effect_kind,
                            "value": _normalize(value),
                        }
                    )
                except BaseException:
                    unknown = self.fence.settle(
                        effect_id,
                        result_digest=None,
                        completion_known=False,
                    )
                    if self.audit is not None:
                        self.audit.append(
                            effect_id=effect_id,
                            effect_kind=effect_kind,
                            event_type="ATTEMPTED_UNKNOWN",
                            payload={
                                "request_digest": unknown.request_digest,
                                "authority_evidence_digest": (
                                    unknown.authority_evidence_digest
                                ),
                                "currentness_evidence_digest": (
                                    unknown.currentness_evidence_digest
                                ),
                            },
                        )
                    raise

                committed = self.fence.settle(
                    effect_id,
                    result_digest=result_digest,
                    completion_known=True,
                )
                if self.audit is not None:
                    self.audit.append(
                        effect_id=effect_id,
                        effect_kind=effect_kind,
                        event_type="COMMITTED",
                        payload={
                            "request_digest": committed.request_digest,
                            "result_digest": committed.result_digest,
                            "authority_evidence_digest": (
                                committed.authority_evidence_digest
                            ),
                            "currentness_evidence_digest": (
                                committed.currentness_evidence_digest
                            ),
                        },
                    )
                return OutboundEffectResult(
                    effect_id=effect_id,
                    effect_kind=effect_kind,
                    request_digest=request_digest,
                    lifecycle_permit_digest=permit.permit_digest,
                    result_digest=result_digest,
                    fence_receipt=committed,
                    value=value,
                )

    def dispatch_pc_job(
        self,
        *,
        permit: AcceptedLifecyclePermit,
        job: JobEnvelope,
        authorization: AuthorizationEnvelope,
        authority_proof: PCJobAuthorityProof,
        execute: Callable[[], T],
    ) -> OutboundEffectResult:
        if type(job) is not JobEnvelope:
            raise OutboundActionError("PC effect requires an exact JobEnvelope")
        if type(authorization) is not AuthorizationEnvelope:
            raise OutboundActionError(
                "PC effect requires an exact AuthorizationEnvelope"
            )
        authority_verifier = self._pc_authority_verifier
        if authority_verifier is None:
            raise OutboundAuthorityError(
                "PC effect requires a trusted gateway-injected authority verifier"
            )
        job.validate()
        authorization.validate()
        if job.project_id != self.lifecycle.project_id:
            raise LifecycleActionDenied(
                "PC job project does not match accepted lifecycle project"
            )

        def verify_authority() -> VerifiedAuthorityEvidence:
            validate_pc_authorization_binding(job, authorization)
            trust = self._outbound_trust_registry
            if trust is None:
                raise OutboundAuthorityError(
                    "PC effect requires persistent outbound trust currentness"
                )
            if (
                authority_verifier.authority_id != authorization.issuer_id
                or authority_proof.issuer_id != authorization.issuer_id
            ):
                raise OutboundAuthorityError(
                    "PC verifier/proof issuer does not match authorization issuer"
                )
            trust_receipt = trust.assert_current(
                authority_id=authorization.issuer_id,
                role="PC",
                key_id=authority_verifier.key_id,
                key_digest=authority_verifier.key_digest,
            )
            if authorization.issuer_revocation_epoch != trust_receipt.revocation_epoch:
                raise OutboundAuthorityError(
                    "PC authorization issuer revocation epoch is stale"
                )
            now = self._clock()
            if (
                not isinstance(now, datetime)
                or now.tzinfo is None
                or now.utcoffset() is None
            ):
                raise OutboundAuthorityError(
                    "PC authority clock must return timezone-aware datetime"
                )
            now = now.astimezone(timezone.utc)
            job_not_before = utc_microseconds(job.not_before, "job.not_before")
            job_expires = utc_microseconds(job.expires_at, "job.expires_at")
            auth_not_before = utc_microseconds(
                authorization.not_before,
                "authorization.not_before",
            )
            auth_expires = utc_microseconds(
                authorization.expires_at,
                "authorization.expires_at",
            )
            if not job_not_before <= now < job_expires:
                raise OutboundAuthorityError(
                    "PC job is outside its execution window"
                )
            if not auth_not_before <= now < auth_expires:
                raise OutboundAuthorityError(
                    "PC authorization is outside its authority window"
                )
            subject = pc_authority_subject(
                job_digest=job.digest(),
                authorization_digest=authorization.digest(),
                lifecycle_permit_digest=permit.permit_digest,
            )
            if not authority_verifier.verify(
                authority_proof,
                expected_subject=subject,
            ):
                raise OutboundAuthorityError(
                    "PC authority proof verification failed for exact job, authorization, and lifecycle permit"
                )
            evidence_digest = _digest(
                {
                    "schema": "VERA_MONO_PC_VERIFIED_AUTHORITY_EVIDENCE_V1",
                    "job_digest": job.digest(),
                    "authorization_digest": authorization.digest(),
                    "authority_proof": authority_proof,
                    "authority_currentness": trust_receipt,
                    "lifecycle_permit_digest": permit.permit_digest,
                }
            )
            return VerifiedAuthorityEvidence(
                evidence_digest=evidence_digest,
                details={
                    "kind": "PC",
                    "authority_id": authority_verifier.authority_id,
                    "key_id": authority_verifier.key_id,
                    "key_digest": authority_verifier.key_digest,
                    "proof_issuer_id": authority_proof.issuer_id,
                    "authority_subject": authority_proof.subject,
                    "job_digest": job.digest(),
                    "authorization_digest": authorization.digest(),
                    "authority_currentness": trust_receipt,
                },
            )

        return self._dispatch_verified(
            permit=permit,
            effect_id=f"pc:{job.envelope_id}",
            effect_kind=f"PC/{job.operation_id}",
            request_payload={
                "job_digest": job.digest(),
                "authorization_digest": authorization.digest(),
                "job": job,
                "authorization": authorization,
                "authority_subject": authority_proof.subject,
            },
            verify_authority=verify_authority,
            execute=execute,
        )

    @staticmethod
    def provider_request_digest(
        *,
        provider_id: str,
        operation: str,
        request_payload: Any,
    ) -> str:
        if type(provider_id) is not str or not provider_id:
            raise OutboundActionError(
                "provider_id must be a non-empty exact string"
            )
        if type(operation) is not str or not operation:
            raise OutboundActionError(
                "operation must be a non-empty exact string"
            )
        return _digest(
            {
                "schema": "VERA_MONO_PROVIDER_REQUEST_V1",
                "provider_id": provider_id,
                "operation": operation,
                "request_payload": request_payload,
            }
        )

    def dispatch_provider_effect(
        self,
        *,
        permit: AcceptedLifecyclePermit,
        effect_id: str,
        provider_id: str,
        operation: str,
        request_payload: Any,
        authority: ProviderAuthorityEnvelope,
        execute: Callable[[], T],
    ) -> OutboundEffectResult:
        if type(provider_id) is not str or not provider_id:
            raise OutboundActionError("provider_id must be a non-empty exact string")
        if type(operation) is not str or not operation:
            raise OutboundActionError("operation must be a non-empty exact string")
        if type(authority) is not ProviderAuthorityEnvelope:
            raise OutboundAuthorityError(
                "provider effect requires exact ProviderAuthorityEnvelope"
            )
        authority_verifier = self._provider_authority_verifiers.get(provider_id)
        if authority_verifier is None:
            raise OutboundAuthorityError(
                f"no trusted authority verifier registered for provider {provider_id!r}"
            )
        provider_request_digest = self.provider_request_digest(
            provider_id=provider_id,
            operation=operation,
            request_payload=request_payload,
        )

        def verify_authority() -> VerifiedAuthorityEvidence:
            trust = self._outbound_trust_registry
            if trust is None:
                raise OutboundAuthorityError(
                    "provider effect requires persistent outbound trust currentness"
                )
            if (
                authority_verifier.authority_id != authority.issuer_id
                or authority_verifier.provider_id != provider_id
            ):
                raise OutboundAuthorityError(
                    "provider verifier identity does not match authority envelope"
                )
            trust_receipt = trust.assert_current(
                authority_id=authority.issuer_id,
                role="PROVIDER",
                provider_id=provider_id,
                key_id=authority_verifier.key_id,
                key_digest=authority_verifier.key_digest,
            )
            subject = provider_authority_subject(
                effect_id=effect_id,
                provider_id=provider_id,
                operation=operation,
                request_digest=provider_request_digest,
                lifecycle_permit_digest=permit.permit_digest,
            )
            if not authority_verifier.verify(
                authority,
                expected_provider_id=provider_id,
                expected_operation=operation,
                expected_subject=subject,
            ):
                raise OutboundAuthorityError(
                    "provider authority verification failed for exact request and lifecycle permit"
                )
            evidence_digest = _digest(
                {
                    "schema": "VERA_MONO_PROVIDER_VERIFIED_AUTHORITY_EVIDENCE_V1",
                    "provider_request_digest": provider_request_digest,
                    "authority": authority,
                    "authority_currentness": trust_receipt,
                    "lifecycle_permit_digest": permit.permit_digest,
                }
            )
            return VerifiedAuthorityEvidence(
                evidence_digest=evidence_digest,
                details={
                    "kind": "PROVIDER",
                    "provider_id": provider_id,
                    "operation": operation,
                    "authority_id": authority_verifier.authority_id,
                    "key_id": authority_verifier.key_id,
                    "key_digest": authority_verifier.key_digest,
                    "authority_issuer_id": authority.issuer_id,
                    "authority_subject": authority.subject,
                    "provider_request_digest": provider_request_digest,
                    "authority_currentness": trust_receipt,
                },
            )

        return self._dispatch_verified(
            permit=permit,
            effect_id=f"provider:{provider_id}:{effect_id}",
            effect_kind=f"PROVIDER/{provider_id}/{operation}",
            request_payload={
                "provider_request_digest": provider_request_digest,
                "request_payload": request_payload,
                "authority_subject": authority.subject,
            },
            verify_authority=verify_authority,
            execute=execute,
        )

    @staticmethod
    def _require_sha256(value: str, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise OutboundActionError(f"{label} must be an exact SHA-256 digest")
        try:
            int(value, 16)
        except ValueError as exc:
            raise OutboundActionError(f"{label} must be hexadecimal") from exc
        return value.lower()


class LifecycleBoundCoordinationBus:
    """Lifecycle-gated facade over every public coordination command.

    Reads require an exact accepted permit. Commands capable of writing are also
    single-use fenced by command_id, so a stale/interrupted candidate cannot
    produce an outbound coordination event through this qualified path.
    """

    READ_COMMANDS = frozenset(
        {
            "coordination_read_inbox",
            "entry_checkpoint",
        }
    )
    WRITE_COMMANDS = frozenset(
        {
            "coordination_post",
            "coordination_acknowledge",
            "coordination_publish_status",
            "coordination_request_review",
            "coordination_resolve_thread",
            "exit_checkpoint",
        }
    )
    COMMANDS = READ_COMMANDS | WRITE_COMMANDS

    def __init__(
        self,
        *,
        lifecycle: NativeVeraLifecycle,
        bus: Any,
        fence: EffectFence,
        audit: OutboundExecutionAudit | None = None,
        command_journal: CoordinationCommandJournal | None = None,
    ):
        self.lifecycle = lifecycle
        self.bus = bus
        if (
            command_journal is not None
            and type(command_journal) is not CoordinationCommandJournal
        ):
            raise TypeError(
                "command_journal must be exact CoordinationCommandJournal"
            )
        self.command_journal = command_journal
        self.effects = LifecycleEffectGateway(
            lifecycle=lifecycle,
            fence=fence,
            audit=audit,
        )

    def invoke(
        self,
        command: str,
        *,
        permit: AcceptedLifecyclePermit,
        actor: Any,
        command_id: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        if command not in self.COMMANDS:
            raise OutboundActionError(
                f"unsupported lifecycle-bound coordination command: {command}"
            )
        call_kwargs = dict(kwargs or {})
        method = getattr(self.bus, command, None)
        if method is None or not callable(method):
            raise OutboundActionError(
                f"coordination bus does not implement command: {command}"
            )

        if command in self.READ_COMMANDS:
            with self.lifecycle.action_lock():
                self.lifecycle.validate_action_permit(permit)
                return method(actor, *args, **call_kwargs)

        if type(command_id) is not str or not command_id:
            raise OutboundActionError(
                "write-capable coordination commands require command_id"
            )
        actor_binding = {
            "workstream": getattr(actor, "workstream", None),
            "permissions": sorted(getattr(actor, "permissions", ())),
        }
        authority_binding_digest = _digest(
            {
                "schema": "VERA_MONO_COORDINATION_AUTHORITY_BINDING_V1",
                "actor": actor_binding,
                "command": command,
            }
        )
        effect_id = f"coordination:{command_id}"
        effect_kind = f"COORDINATION/{command}"
        request_payload = {
            "command": command,
            "actor": actor_binding,
            "args": args,
            "kwargs": call_kwargs,
        }
        request_digest = self.effects.effect_request_digest(
            permit=permit,
            effect_id=effect_id,
            effect_kind=effect_kind,
            request_payload=request_payload,
        )
        invocation_digest = _digest(
            {
                "schema": "VERA_MONO_COORDINATION_INVOCATION_V1",
                "command": command,
                "actor": actor_binding,
                "args": args,
                "kwargs": call_kwargs,
            }
        )
        if self.command_journal is not None:
            self.command_journal.bind(
                command_id=command_id,
                effect_id=effect_id,
                command=command,
                actor_workstream=str(actor_binding["workstream"]),
                lifecycle_permit_digest=permit.permit_digest,
                invocation_digest=invocation_digest,
                request_digest=request_digest,
            )

        result = self.effects._dispatch_verified(
            permit=permit,
            effect_id=effect_id,
            effect_kind=effect_kind,
            request_payload=request_payload,
            verify_authority=lambda: VerifiedAuthorityEvidence(
                evidence_digest=authority_binding_digest,
                details={
                    "kind": "COORDINATION",
                    "command": command,
                    "actor": actor_binding,
                },
            ),
            execute=lambda: method(actor, *args, **call_kwargs),
        )
        if result.request_digest != request_digest:
            raise CoordinationCommandJournalError(
                "coordination effect request digest diverged from prepared binding"
            )
        if self.command_journal is not None:
            receipt = getattr(result.value, "receipt", None)
            if receipt is None:
                raise CoordinationCommandJournalError(
                    "coordination command returned no receipted result"
                )
            self.command_journal.record_result(
                command_id,
                result_digest=result.result_digest,
                result_class=str(receipt.result_class),
                database_write_confirmed=bool(
                    receipt.database_write_confirmed
                ),
                event_id=receipt.event_id,
                event_sequence=receipt.event_sequence,
            )
        return result

    def assess_command(
        self,
        command_id: str,
    ) -> CoordinationCommandRecoveryAssessment:
        if self.command_journal is None:
            raise ValueError(
                "coordination recovery requires a CoordinationCommandJournal"
            )
        self.command_journal.verify_integrity()
        binding = self.command_journal.read_binding(command_id)
        result = self.command_journal.read_result(command_id)
        if self.effects.audit is not None:
            self.effects.audit.verify_fence_consistency(self.effects.fence)
        try:
            fence = self.effects.fence.read(binding.effect_id)
        except KeyError:
            fence = None

        lifecycle_current: bool | None
        try:
            current = self.lifecycle.accepted_action_permit()
            lifecycle_current = (
                current.permit_digest == binding.lifecycle_permit_digest
            )
        except (LifecycleActionDenied, EffectFenceError):
            lifecycle_current = None

        fence_state = None if fence is None else fence.state.value
        if result is not None:
            if (
                fence is not None
                and fence.state in {
                    EffectState.COMMITTED,
                    EffectState.RECONCILED_COMMITTED,
                }
                and fence.result_digest == result.result_digest
            ):
                return CoordinationCommandRecoveryAssessment(
                    command_id=binding.command_id,
                    effect_id=binding.effect_id,
                    command=binding.command,
                    actor_workstream=binding.actor_workstream,
                    request_digest=binding.request_digest,
                    result_recorded=True,
                    fence_state=fence_state,
                    lifecycle_permit_current=lifecycle_current,
                    retry_candidate_allowed=False,
                    pre_dispatch_cancel_allowed=False,
                    recovery_required=False,
                    terminal=True,
                    reason=(
                        "coordination result journal and terminal effect fence agree"
                    ),
                )
            return CoordinationCommandRecoveryAssessment(
                command_id=binding.command_id,
                effect_id=binding.effect_id,
                command=binding.command,
                actor_workstream=binding.actor_workstream,
                request_digest=binding.request_digest,
                result_recorded=True,
                fence_state=fence_state,
                lifecycle_permit_current=lifecycle_current,
                retry_candidate_allowed=False,
                pre_dispatch_cancel_allowed=False,
                recovery_required=True,
                terminal=False,
                reason=(
                    "coordination result evidence does not match terminal "
                    "mechanical effect state"
                ),
            )

        if fence is None:
            return CoordinationCommandRecoveryAssessment(
                command_id=binding.command_id,
                effect_id=binding.effect_id,
                command=binding.command,
                actor_workstream=binding.actor_workstream,
                request_digest=binding.request_digest,
                result_recorded=False,
                fence_state=None,
                lifecycle_permit_current=lifecycle_current,
                retry_candidate_allowed=(lifecycle_current is True),
                pre_dispatch_cancel_allowed=False,
                recovery_required=False,
                terminal=False,
                reason=(
                    "coordination command is bound but no mechanical effect "
                    "exists"
                    if lifecycle_current is True
                    else "coordination command binding is not current for retry"
                ),
            )

        if fence.state is EffectState.RESERVED:
            return CoordinationCommandRecoveryAssessment(
                command_id=binding.command_id,
                effect_id=binding.effect_id,
                command=binding.command,
                actor_workstream=binding.actor_workstream,
                request_digest=binding.request_digest,
                result_recorded=False,
                fence_state=fence_state,
                lifecycle_permit_current=lifecycle_current,
                retry_candidate_allowed=False,
                pre_dispatch_cancel_allowed=True,
                recovery_required=False,
                terminal=False,
                reason=(
                    "coordination effect is durably reserved pre-dispatch; "
                    "cancel it rather than reusing the effect identity"
                ),
            )

        if fence.state in {
            EffectState.EXECUTING,
            EffectState.ATTEMPTED_UNKNOWN,
            EffectState.COMMITTED,
            EffectState.RECONCILED_COMMITTED,
        }:
            return CoordinationCommandRecoveryAssessment(
                command_id=binding.command_id,
                effect_id=binding.effect_id,
                command=binding.command,
                actor_workstream=binding.actor_workstream,
                request_digest=binding.request_digest,
                result_recorded=False,
                fence_state=fence_state,
                lifecycle_permit_current=lifecycle_current,
                retry_candidate_allowed=False,
                pre_dispatch_cancel_allowed=False,
                recovery_required=True,
                terminal=False,
                reason=(
                    "coordination effect may have executed but durable command "
                    "result evidence is missing; do not replay"
                ),
            )

        return CoordinationCommandRecoveryAssessment(
            command_id=binding.command_id,
            effect_id=binding.effect_id,
            command=binding.command,
            actor_workstream=binding.actor_workstream,
            request_digest=binding.request_digest,
            result_recorded=False,
            fence_state=fence_state,
            lifecycle_permit_current=lifecycle_current,
            retry_candidate_allowed=False,
            pre_dispatch_cancel_allowed=False,
            recovery_required=False,
            terminal=True,
            reason=(
                "coordination effect reached a terminal no-replay mechanical state"
            ),
        )

    def recover_commands(
        self,
    ) -> tuple[CoordinationCommandRecoveryAssessment, ...]:
        if self.command_journal is None:
            return ()
        return tuple(
            self.assess_command(binding.command_id)
            for binding in self.command_journal.bindings()
        )

    def cancel_reserved_command(
        self,
        command_id: str,
    ) -> CoordinationCommandRecoveryAssessment:
        assessment = self.assess_command(command_id)
        if not assessment.pre_dispatch_cancel_allowed:
            raise EffectFenceError(
                "coordination command has no proven pre-dispatch reservation"
            )
        with self.lifecycle.action_lock():
            cancelled = self.effects.fence.cancel_before_dispatch(
                assessment.effect_id
            )
            previous = (
                None
                if self.effects.audit is None
                else self.effects.audit.latest(assessment.effect_id)
            )
            if self.effects.audit is not None:
                if previous is None:
                    raise CoordinationCommandJournalError(
                        "qualified coordination reservation is missing audit evidence"
                    )
                self.effects.audit.append(
                    effect_id=assessment.effect_id,
                    effect_kind=previous.effect_kind,
                    event_type="CANCELLED_PRE_DISPATCH",
                    payload={
                        "request_digest": cancelled.request_digest,
                        "mechanical_permit_digest": (
                            cancelled.mechanical_permit_digest
                        ),
                        "authority_evidence_digest": (
                            cancelled.authority_evidence_digest
                        ),
                        "currentness_evidence_digest": (
                            cancelled.currentness_evidence_digest
                        ),
                    },
                )
        return self.assess_command(command_id)
