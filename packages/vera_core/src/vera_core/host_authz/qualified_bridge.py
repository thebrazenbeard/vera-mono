"""Opt-in bridge from host grants into Vera's existing governed provider gate.

An authorization-service claim is NOT by itself a substitute for the accepted
lifecycle permit, outbound trust registry, mechanical fence and audit in
``QualifiedVeraRuntime``. This module preserves that canonical second gate.

Only a dedicated, separately privileged host process may construct this
bridge. A model must not receive the runtime, issuer, provider transport,
Ed25519 signing key or resulting Python callable. This module does not prove
provider-side fencing, consent-revocation linearization or host key custody.
"""

from __future__ import annotations

from hashlib import sha256
import hmac

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_assurance import EffectState

from ..outbound_authority import HmacProviderAuthority
from ..qualified_runtime import QualifiedVeraRuntime
from .service import (
    HostProviderHandle,
    ProviderAcknowledgement,
    ProviderDispatch,
)


class QualifiedBridgeDenied(PermissionError):
    """Host provider binding is stale or canonical gateway denied effect."""


def qualified_provider_handle(
    *,
    runtime: QualifiedVeraRuntime,
    authority: HmacProviderAuthority,
    provider_id: str,
    provider_instance_id: str,
    receipt_signer: Ed25519PrivateKey,
) -> HostProviderHandle:
    """Capture a host-only governed provider handle once before serving IPC.

    No arbitrary provider ``execute`` callback is accepted here. It is sourced
    exclusively from the runtime's already-registered host-injected transport.
    The existing gateway remains responsible for authority verification,
    lifecycle, trust currentness, effect fencing and durable audit.
    """
    if type(runtime) is not QualifiedVeraRuntime:
        raise TypeError("runtime must be exact QualifiedVeraRuntime")
    if type(authority) is not HmacProviderAuthority:
        raise TypeError("authority must be exact HmacProviderAuthority")
    # cryptography exposes an abstract interface; generated keys are backend
    # implementations, so exact ABC type comparison would reject genuine keys.
    if not isinstance(receipt_signer, Ed25519PrivateKey):
        raise TypeError("receipt_signer must implement Ed25519PrivateKey")
    if type(provider_id) is not str or not provider_id:
        raise ValueError("provider_id must be an exact nonempty string")
    if type(provider_instance_id) is not str or not provider_instance_id:
        raise ValueError("provider_instance_id must be an exact nonempty string")
    if provider_id.startswith("source:"):
        raise QualifiedBridgeDenied("source mutation cannot use provider bridge")
    if authority.provider_id != provider_id:
        raise QualifiedBridgeDenied("authority provider identity differs")

    transport = runtime.provider_execution_transports.get(provider_id)
    registered_verifier = runtime.effects._provider_authority_verifiers.get(provider_id)
    if transport is None or getattr(transport, "provider_id", None) != provider_id:
        raise QualifiedBridgeDenied("missing bound runtime provider transport")
    if registered_verifier is not authority:
        raise QualifiedBridgeDenied("runtime verifier is not the host authority")

    public_key = receipt_signer.public_key().public_bytes_raw()

    def dispatch(instruction: ProviderDispatch) -> ProviderAcknowledgement:
        if type(instruction) is not ProviderDispatch:
            raise QualifiedBridgeDenied("noncanonical provider instruction")
        if (
            instruction.provider_id != provider_id
            or instruction.provider_instance_id != provider_instance_id
        ):
            raise QualifiedBridgeDenied("provider instance binding mismatch")
        if (
            runtime.provider_execution_transports.get(provider_id) is not transport
            or runtime.effects._provider_authority_verifiers.get(provider_id)
            is not authority
        ):
            raise QualifiedBridgeDenied("runtime provider/issuer changed after capture")
        if type(instruction.request_digest) is not str or not hmac.compare_digest(
            instruction.request_digest,
            sha256(canonical_json_bytes(instruction.request_payload)).hexdigest(),
        ):
            raise QualifiedBridgeDenied("provider request payload changed")

        prepared = runtime.prepare_provider_effect(
            effect_id=instruction.effect_id,
            provider_id=provider_id,
            operation=instruction.operation,
            request_payload=instruction.request_payload,
        )
        proof = authority.issue(
            effect_id=prepared.effect_id,
            operation=prepared.operation,
            request_digest=prepared.request_digest,
            lifecycle_permit_digest=prepared.permit.permit_digest,
        )
        outcome = runtime.execute_provider_effect(prepared, authority=proof)
        if (
            outcome.fence_receipt.state is not EffectState.COMMITTED
            or outcome.effect_id != f"provider:{provider_id}:{instruction.effect_id}"
            # The gateway's mechanical request_digest covers the full
            # provider+authority envelope, unlike prepared.request_digest.
            or outcome.request_digest != outcome.fence_receipt.request_digest
        ):
            raise QualifiedBridgeDenied("canonical provider execution not committed")
        # Signed only AFTER actual canonical gateway success and durable fence.
        unsigned = ProviderAcknowledgement(
            effect_id=instruction.effect_id,
            provider_id=provider_id,
            provider_instance_id=provider_instance_id,
            claim_sequence=instruction.claim_sequence,
            request_digest=instruction.request_digest,
            provider_receipt_digest=outcome.result_digest,
            receipt_signature=b"",
        )
        signature = receipt_signer.sign(
            b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\x00"
            + canonical_json_bytes(unsigned.signed_body())
        )
        return ProviderAcknowledgement(
            effect_id=unsigned.effect_id,
            provider_id=unsigned.provider_id,
            provider_instance_id=unsigned.provider_instance_id,
            claim_sequence=unsigned.claim_sequence,
            request_digest=unsigned.request_digest,
            provider_receipt_digest=unsigned.provider_receipt_digest,
            receipt_signature=signature,
        )

    return HostProviderHandle(
        provider_id=provider_id,
        provider_instance_id=provider_instance_id,
        receipt_public_key=public_key,
        dispatch=dispatch,
    )
