"""Host-owned, one-use authorization and provider-dispatch composition.

This module must run in a privileged host process, with an authenticated IPC
transport supplying ``peer_key``.  Importing the class inside a model process
does not confer host authority: the signer, witness, consent oracle and provider
transports are deliberately not supplied by model-generated requests.

The database/witness, signed grant and provider transport are all necessary;
none independently proves real host custody or provider effect finality.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .bindings import HostBindingSnapshot, ProviderBinding
from .grants import ApprovedGrant, SignedGrantVerifier
from .ledger import ClaimLedger


class AuthorizationDenied(PermissionError):
    """Authorization failed before safe dispatch, or a replay was denied."""


class EffectOutcomeUnknown(RuntimeError):
    """A grant was consumed; provider execution needs external reconciliation."""


def _exact_id(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise AuthorizationDenied(f"invalid {label}")
    return value


def _digest(value: Any) -> str:
    try:
        return sha256(canonical_json_bytes(value)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise AuthorizationDenied("request payload is not canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class ProviderDispatch:
    """Exact, replay-identifiable host instruction delivered to the provider."""

    effect_id: str
    grant_id: str
    provider_id: str
    provider_instance_id: str
    operation: str
    request_digest: str
    claim_sequence: int
    participant_id: str
    purpose: str
    request_payload: Any


@dataclass(frozen=True, slots=True)
class ProviderAcknowledgement:
    """A provider's positive acknowledgement, not arbitrary return data."""

    effect_id: str
    provider_id: str
    provider_instance_id: str
    claim_sequence: int
    request_digest: str
    provider_receipt_digest: str
    receipt_signature: bytes

    def signed_body(self) -> dict[str, str | int]:
        return {
            "schema": "HOST_AUTHZ_PROVIDER_ACK_V1",
            "effect_id": self.effect_id,
            "provider_id": self.provider_id,
            "provider_instance_id": self.provider_instance_id,
            "claim_sequence": self.claim_sequence,
            "request_digest": self.request_digest,
            "provider_receipt_digest": self.provider_receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedEffectReceipt:
    grant_id: str
    effect_id: str
    provider_id: str
    provider_instance_id: str
    claim_sequence: int
    provider_receipt_digest: str
    state: str = "ACKNOWLEDGED"

    def public_body(self) -> dict[str, str | int]:
        """Return a bounded, credential-free IPC response."""
        return {
            "schema": "HOST_AUTHZ_EFFECT_RECEIPT_V1",
            "state": self.state,
            "grant_id": self.grant_id,
            "effect_id": self.effect_id,
            "provider_id": self.provider_id,
            "provider_instance_id": self.provider_instance_id,
            "claim_sequence": self.claim_sequence,
            "provider_receipt_digest": self.provider_receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class HostProviderHandle:
    """Privileged host captures the connector once, before IPC is enabled.

    Neither mutable provider registries nor model-request messages can replace
    this handle. The host still has to secure the callable's own code, closure,
    provider credentials and downstream authority in a separate OS process.
    """

    provider_id: str
    provider_instance_id: str
    receipt_public_key: bytes
    dispatch: Callable[[ProviderDispatch], ProviderAcknowledgement]

    def __post_init__(self) -> None:
        _exact_id(self.provider_id, "provider handle id")
        _exact_id(self.provider_instance_id, "provider instance id")
        if type(self.receipt_public_key) is not bytes or len(self.receipt_public_key) != 32:
            raise TypeError("host must pin exact 32-byte provider Ed25519 ACK key")
        Ed25519PublicKey.from_public_bytes(self.receipt_public_key)
        if not callable(self.dispatch):
            raise TypeError("provider dispatch must be host callable")


@dataclass(frozen=True, slots=True)
class _PinnedProvider:
    provider_id: str
    provider_instance_id: str
    handle: HostProviderHandle
    dispatch_method: Callable[[ProviderDispatch], ProviderAcknowledgement]
    ack_verifier: Ed25519PublicKey


@dataclass(frozen=True, slots=True, init=False)
class HostAuthorizationService:
    """One coherent, host-owned authorization service.

    Provider and consent callbacks must be acquired by the host service before
    untrusted models are connected. A mapping-copy stops ordinary provider-map
    rebinding; separate OS process identity/custody is still a deployment gate.
    """

    bindings: HostBindingSnapshot
    grant_verifier: SignedGrantVerifier
    ledger: ClaimLedger
    _providers: Mapping[str, _PinnedProvider]
    _trusted_clock: Callable[[], int]
    _consent_status: Callable[[ApprovedGrant, int], bool] | None
    _provider_status: Callable[[ProviderBinding, int], bool] | None

    def __init__(
        self,
        bindings: HostBindingSnapshot,
        grant_verifier: SignedGrantVerifier,
        ledger: ClaimLedger,
        providers: Mapping[str, HostProviderHandle],
        trusted_clock: Callable[[], int],
        *,
        consent_status: Callable[[ApprovedGrant, int], bool] | None = None,
        provider_status: Callable[[ProviderBinding, int], bool] | None = None,
    ) -> None:
        if type(bindings) is not HostBindingSnapshot:
            raise TypeError("host binding must be exact HostBindingSnapshot")
        if type(grant_verifier) is not SignedGrantVerifier:
            raise TypeError("grant verifier must be exact SignedGrantVerifier")
        if type(ledger) is not ClaimLedger:
            raise TypeError("ledger must be exact ClaimLedger")
        if not callable(trusted_clock):
            raise TypeError("trusted host clock is required")
        if type(providers) is not dict and not isinstance(providers, Mapping):
            raise TypeError("host provider registry must be a mapping")
        if consent_status is not None and not callable(consent_status):
            raise TypeError("consent status oracle must be callable")
        if provider_status is not None and not callable(provider_status):
            raise TypeError("provider status oracle must be callable")

        pinned: dict[str, _PinnedProvider] = {}
        for provider_id, handle in providers.items():
            if type(provider_id) is not str or not provider_id:
                raise ValueError("invalid host provider registry key")
            registered = bindings.providers.get(provider_id)
            if type(registered) is not ProviderBinding:
                raise ValueError("provider not present in frozen host registry")
            if type(handle) is not HostProviderHandle:
                raise TypeError("host provider must use exact immutable handle")
            if (
                handle.provider_id != provider_id
                or handle.provider_instance_id
                != registered.provider_instance_id
            ):
                raise ValueError("provider instance identity mismatch")
            pinned[provider_id] = _PinnedProvider(
                provider_id=provider_id,
                provider_instance_id=registered.provider_instance_id,
                handle=HostProviderHandle(
                    provider_id=handle.provider_id,
                    provider_instance_id=handle.provider_instance_id,
                    receipt_public_key=handle.receipt_public_key,
                    dispatch=handle.dispatch,
                ),
                dispatch_method=handle.dispatch,
                ack_verifier=Ed25519PublicKey.from_public_bytes(handle.receipt_public_key),
            )
        if set(pinned) != set(bindings.providers):
            raise ValueError("host provider set does not match bound provider set")

        if ledger.authority_id != bindings.host_id or ledger.epoch != bindings.epoch:
            raise ValueError("ledger authority host/epoch does not match binding")
        if (
            grant_verifier.issuer_id != bindings.issuer_id
            or grant_verifier.host_id != bindings.host_id
            or grant_verifier.epoch != bindings.epoch
        ):
            raise ValueError("grant verifier issuer/host/epoch mismatch")

        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "grant_verifier", grant_verifier)
        object.__setattr__(self, "ledger", ledger)
        object.__setattr__(self, "_providers", MappingProxyType(pinned))
        object.__setattr__(self, "_trusted_clock", trusted_clock)
        object.__setattr__(self, "_consent_status", consent_status)
        object.__setattr__(self, "_provider_status", provider_status)

    def _now(self) -> int:
        try:
            value = self._trusted_clock()
        except Exception as exc:
            raise AuthorizationDenied("trusted host clock unavailable") from exc
        if type(value) is not int or value < 0:
            raise AuthorizationDenied("trusted host clock is invalid")
        return value

    def _consent_ok(self, grant: ApprovedGrant, now: int) -> bool:
        try:
            return self._consent_status is not None and (
                self._consent_status(grant, now) is True
            )
        except Exception:
            return False

    def _provider_ok(self, binding: ProviderBinding, now: int) -> bool:
        try:
            return self._provider_status is not None and (
                self._provider_status(binding, now) is True
            )
        except Exception:
            return False

    def execute(
        self,
        *,
        peer_key: str,
        signed_grant: bytes,
        provider_id: str,
        operation: str,
        request_payload: Any,
    ) -> AuthorizedEffectReceipt:
        """Consume one signed grant and dispatch exactly once to a bound host provider.

        ``peer_key`` is privileged IPC metadata, not a field accepted from the
        wire request. The provider MUST independently fence ``effect_id`` and
        expose authoritative status for crash reconciliation; this method does
        not retry UNKNOWN/RESERVED grants.
        """
        _exact_id(peer_key, "authenticated peer")
        _exact_id(provider_id, "provider")
        _exact_id(operation, "operation")
        if type(signed_grant) is not bytes:
            raise AuthorizationDenied("signed grant must be exact bytes")

        try:
            principal = self.bindings.principal_for_peer(peer_key)
            provider = self.bindings.provider_for(
                principal, provider_id, operation
            )
        except (KeyError, PermissionError, ValueError, TypeError) as exc:
            raise AuthorizationDenied("principal/provider is not authorized") from exc

        try:
            grant = self.grant_verifier.verify(signed_grant)
        except Exception as exc:
            raise AuthorizationDenied("invalid signed host grant") from exc
        if type(grant) is not ApprovedGrant:
            raise AuthorizationDenied("verifier returned a noncanonical grant")

        request_digest = _digest(request_payload)
        # Pin exact canonical request bytes now; asynchronous caller mutations
        # cannot alter the object later handed to the provider.
        pinned_payload = json.loads(canonical_json_bytes(request_payload))
        expected = {
            "host_id": self.bindings.host_id,
            "issuer_id": self.bindings.issuer_id,
            "epoch": self.bindings.epoch,
            "peer_key": principal.peer_key,
            "model_id": principal.model_id,
            "adapter_id": principal.adapter_id,
            "runtime_id": principal.runtime_id,
            "subject_id": principal.subject_id,
            "provider_id": provider.provider_id,
            "provider_instance_id": provider.provider_instance_id,
            "operation": operation,
            "request_digest": request_digest,
        }
        if any(getattr(grant, field) != value for field, value in expected.items()):
            raise AuthorizationDenied("signed grant does not bind execution")
        if (
            type(grant.participant_id) is not str
            or not grant.participant_id.strip()
            or type(grant.purpose) is not str
            or not grant.purpose.strip()
        ):
            raise AuthorizationDenied("grant lacks participant/purpose consent scope")

        now = self._now()
        if now < grant.not_before or now >= grant.expires_at:
            raise AuthorizationDenied("grant outside trusted time window")
        if not self._consent_ok(grant, now):
            raise AuthorizationDenied("host consent status is not positive")
        if not self._provider_ok(provider, now):
            raise AuthorizationDenied("host provider status is not positive")
        pinned = self._providers.get(provider_id)
        if pinned is None or (
            pinned.provider_instance_id != provider.provider_instance_id
            or pinned.handle.provider_id != provider_id
            or pinned.handle.provider_instance_id != provider.provider_instance_id
        ):
            raise AuthorizationDenied("host provider binding was replaced")

        claim_digest = sha256(
            canonical_json_bytes(
                {
                    "schema": "HOST_AUTHZ_CLAIM_V1",
                    "grant": grant.canonical_body(),
                    "provider_instance_id": provider.provider_instance_id,
                    "request_digest": request_digest,
                }
            )
        ).hexdigest()
        try:
            claim = self.ledger.claim(
                grant.grant_id,
                claim_digest,
                datetime.fromtimestamp(now, tz=UTC),
            )
        except Exception as exc:
            raise AuthorizationDenied("grant not claimable by live host authority") from exc

        effect_id = sha256(
            canonical_json_bytes(
                {
                    "schema": "HOST_AUTHZ_EFFECT_ID_V1",
                    "host_id": self.bindings.host_id,
                    "epoch": self.bindings.epoch,
                    "claim_sequence": claim.sequence,
                    "claim_digest": claim_digest,
                    "grant_id": grant.grant_id,
                }
            )
        ).hexdigest()
        instruction = ProviderDispatch(
            effect_id=effect_id,
            grant_id=grant.grant_id,
            provider_id=provider_id,
            provider_instance_id=provider.provider_instance_id,
            operation=operation,
            request_digest=request_digest,
            claim_sequence=claim.sequence,
            participant_id=grant.participant_id,
            purpose=grant.purpose,
            request_payload=pinned_payload,
        )

        # Authority may have revoked consent after the first check. A later
        # revocation concurrent with physical dispatch needs provider fencing.
        later = self._now()
        if (
            later < grant.not_before
            or later >= grant.expires_at
            or not self._consent_ok(grant, later)
            or not self._provider_ok(provider, later)
        ):
            self.ledger.mark_ambiguous(grant.grant_id)
            raise AuthorizationDenied("authority status changed after grant claim")
        # Check revocation of the claimed grant as well as the independent
        # consent oracle. This is NOT a provider-enforced dispatch lease: a
        # revocation after this read can still race with physical dispatch.
        claimed_now = self.ledger.read(grant.grant_id)
        if (
            claimed_now is None
            or claimed_now.revoked
            or claimed_now.state != "RESERVED"
            or claimed_now.sequence != claim.sequence
        ):
            try:
                self.ledger.mark_ambiguous(grant.grant_id)
            except Exception:
                pass
            raise AuthorizationDenied("grant status changed before dispatch")

        try:
            response = pinned.dispatch_method(instruction)
            if (
                type(response) is not ProviderAcknowledgement
                or response.effect_id != effect_id
                or response.provider_id != provider_id
                or response.provider_instance_id != provider.provider_instance_id
                or response.claim_sequence != claim.sequence
                or response.request_digest != request_digest
                or type(response.provider_receipt_digest) is not str
                or len(response.provider_receipt_digest) != 64
                or any(ch not in "0123456789abcdef" for ch in response.provider_receipt_digest)
                or type(response.receipt_signature) is not bytes
                or len(response.receipt_signature) != 64
            ):
                raise EffectOutcomeUnknown("provider acknowledgement not verified")
            try:
                pinned.ack_verifier.verify(
                    response.receipt_signature,
                    b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\x00"
                    + canonical_json_bytes(response.signed_body()),
                )
            except InvalidSignature as exc:
                raise EffectOutcomeUnknown("provider acknowledgement signature invalid") from exc
            self.ledger.complete(grant.grant_id, response.provider_receipt_digest)
        except BaseException as exc:
            # Includes KeyboardInterrupt: the claim stays RESERVED/AMBIGUOUS,
            # never automatically re-dispatched. Crash during the ledger update
            # leaves RESERVED and requires external provider reconciliation.
            try:
                self.ledger.mark_ambiguous(grant.grant_id)
            except Exception:
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise EffectOutcomeUnknown("provider result is not safely final") from exc
        return AuthorizedEffectReceipt(
            grant_id=grant.grant_id,
            effect_id=effect_id,
            provider_id=provider_id,
            provider_instance_id=provider.provider_instance_id,
            claim_sequence=claim.sequence,
            provider_receipt_digest=response.provider_receipt_digest,
        )
