from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import EffectFence, EffectReceipt
from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope
from pc_connection.validation import utc_microseconds

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
        self._provider_authority_verifiers = registry
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _dispatch_verified(
        self,
        *,
        permit: AcceptedLifecyclePermit,
        effect_id: str,
        effect_kind: str,
        request_payload: Any,
        verify_authority: Callable[[], str],
        execute: Callable[[], T],
    ) -> OutboundEffectResult:
        if type(effect_id) is not str or not effect_id:
            raise OutboundActionError("effect_id must be a non-empty exact string")
        if type(effect_kind) is not str or not effect_kind:
            raise OutboundActionError("effect_kind must be a non-empty exact string")
        normalized_request = {
            "schema": "VERA_MONO_LIFECYCLE_BOUND_EFFECT_REQUEST_V1",
            "effect_id": effect_id,
            "effect_kind": effect_kind,
            "request_payload": _normalize(request_payload),
            "lifecycle_permit_digest": permit.permit_digest,
        }
        request_digest = _digest(normalized_request)
        mechanical_permit_digest = _digest(
            {
                "schema": "VERA_MONO_EFFECT_MECHANICAL_PERMIT_V1",
                "effect_id": effect_id,
                "request_digest": request_digest,
                "lifecycle_permit_digest": permit.permit_digest,
            }
        )

        with self.lifecycle.action_lock():
            self.fence.assert_clear()
            self.lifecycle.validate_action_permit(permit)
            authority_evidence_digest = verify_authority()
            self._require_sha256(
                authority_evidence_digest,
                "authority_evidence_digest",
            )
            self.fence.reserve(
                effect_id=effect_id,
                request_digest=request_digest,
                mechanical_permit_digest=mechanical_permit_digest,
                authority_evidence_digest=authority_evidence_digest,
                currentness_evidence_digest=permit.permit_digest,
            )
            # Re-check after durable reservation and before the single-use
            # dispatch claim. The shared lifecycle lock prevents a canonical
            # lifecycle transition from interleaving with execution.
            self.lifecycle.validate_action_permit(permit)
            self.fence.claim_dispatch(
                effect_id=effect_id,
                request_digest=request_digest,
                mechanical_permit_digest=mechanical_permit_digest,
                authority_evidence_digest=authority_evidence_digest,
                currentness_evidence_digest=permit.permit_digest,
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
                self.fence.settle(
                    effect_id,
                    result_digest=None,
                    completion_known=False,
                )
                raise

            committed = self.fence.settle(
                effect_id,
                result_digest=result_digest,
                completion_known=True,
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

        def verify_authority() -> str:
            validate_pc_authorization_binding(job, authorization)
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
            return _digest(
                {
                    "schema": "VERA_MONO_PC_VERIFIED_AUTHORITY_EVIDENCE_V1",
                    "job_digest": job.digest(),
                    "authorization_digest": authorization.digest(),
                    "authority_proof": authority_proof,
                    "lifecycle_permit_digest": permit.permit_digest,
                }
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

        def verify_authority() -> str:
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
            return _digest(
                {
                    "schema": "VERA_MONO_PROVIDER_VERIFIED_AUTHORITY_EVIDENCE_V1",
                    "provider_request_digest": provider_request_digest,
                    "authority": authority,
                    "lifecycle_permit_digest": permit.permit_digest,
                }
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
    ):
        self.lifecycle = lifecycle
        self.bus = bus
        self.effects = LifecycleEffectGateway(
            lifecycle=lifecycle,
            fence=fence,
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
        return self.effects._dispatch_verified(
            permit=permit,
            effect_id=f"coordination:{command_id}",
            effect_kind=f"COORDINATION/{command}",
            request_payload={
                "command": command,
                "actor": actor_binding,
                "args": args,
                "kwargs": call_kwargs,
            },
            verify_authority=lambda: authority_binding_digest,
            execute=lambda: method(actor, *args, **call_kwargs),
        )
