"""Provider-owned adapter to Vera's canonical outbound effect gateway.

This module is intended to be constructed *inside* the separately privileged
provider process, not passed to a model or used as a host-side callback.  It
does not invent an alternate provider execution route: every physical effect
must pass the accepted lifecycle permit, registered outbound authority,
durable mechanical fence and audit of ``QualifiedVeraRuntime``.

The adapter/factory are SOURCE candidates.  They cannot attest that a deployed
provider daemon actually uses this factory; launch/readback qualification is
required.  An untrusted process sharing provider memory defeats Python-level
frozen bindings, regardless of how many wrappers are added.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_assurance import EffectState

from ..outbound_authority import HmacProviderAuthority
from ..qualified_runtime import QualifiedVeraRuntime
from .provider_custody import EffectWitness, ProviderCustodyWorker
from .service import ProviderDispatch


class GovernedProviderDenied(PermissionError):
    """The dedicated provider's canonical Vera gateway rejected an effect."""


@dataclass(frozen=True, slots=True, init=False)
class GovernedProviderExecutor:
    """A provider-process callable with an exact canonical runtime binding.

    The private transport is registered on ``QualifiedVeraRuntime`` itself;
    callers cannot inject an ``execute`` argument to this adapter.  The
    provider's separate OS principal must own the runtime, authority, and
    provider credential material.
    """

    _runtime: QualifiedVeraRuntime
    _authority: HmacProviderAuthority
    _provider_id: str
    _instance_id: str
    _transport: Any

    def __init__(self, *, runtime: QualifiedVeraRuntime,
                 authority: HmacProviderAuthority, provider_id: str,
                 provider_instance_id: str) -> None:
        if type(runtime) is not QualifiedVeraRuntime:
            raise TypeError("requires exact governed runtime")
        if type(authority) is not HmacProviderAuthority:
            raise TypeError("requires exact runtime-registered provider authority")
        if (type(provider_id) is not str or not provider_id
                or provider_id.startswith("source:")
                or type(provider_instance_id) is not str or not provider_instance_id):
            raise GovernedProviderDenied("provider identity not allowed")
        transport = runtime.provider_execution_transports.get(provider_id)
        verifier = runtime.effects._provider_authority_verifiers.get(provider_id)
        if transport is None or getattr(transport, "provider_id", None) != provider_id:
            raise GovernedProviderDenied("canonical provider transport is unbound")
        if verifier is not authority or authority.provider_id != provider_id:
            raise GovernedProviderDenied("canonical provider authority is unbound")
        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_authority", authority)
        object.__setattr__(self, "_provider_id", provider_id)
        object.__setattr__(self, "_instance_id", provider_instance_id)
        object.__setattr__(self, "_transport", transport)

    def __call__(self, command: ProviderDispatch) -> dict[str, str]:
        if type(command) is not ProviderDispatch:
            raise GovernedProviderDenied("provider command is not canonical")
        if (command.provider_id != self._provider_id
                or command.provider_instance_id != self._instance_id):
            raise GovernedProviderDenied("provider command targets a different instance")
        try:
            digest = sha256(canonical_json_bytes(command.request_payload)).hexdigest()
        except (TypeError, ValueError, OverflowError) as exc:
            raise GovernedProviderDenied("request is not canonical JSON") from exc
        if type(command.request_digest) is not str or not hmac.compare_digest(
                command.request_digest, digest):
            raise GovernedProviderDenied("signed request payload digest changed")
        runtime, authority = self._runtime, self._authority
        if (runtime.provider_execution_transports.get(self._provider_id) is not self._transport
                or runtime.effects._provider_authority_verifiers.get(self._provider_id) is not authority):
            raise GovernedProviderDenied("canonical provider transport or verifier changed")

        # Any failure after this point may have consumed an effect.  The
        # surrounding ProviderCustodyWorker owns no-retry/UNKNOWN semantics.
        prepared = runtime.prepare_provider_effect(
            effect_id=command.effect_id,
            provider_id=self._provider_id,
            operation=command.operation,
            request_payload=command.request_payload,
        )
        proof = authority.issue(
            effect_id=prepared.effect_id,
            operation=prepared.operation,
            request_digest=prepared.request_digest,
            lifecycle_permit_digest=prepared.permit.permit_digest,
        )
        result = runtime.execute_provider_effect(prepared, authority=proof)
        mechanical_id = f"provider:{self._provider_id}:{command.effect_id}"
        if (result.effect_id != mechanical_id
                or result.fence_receipt.state is not EffectState.COMMITTED
                or result.request_digest != result.fence_receipt.request_digest):
            raise GovernedProviderDenied("canonical effect was not durably committed")
        audit_record = runtime.audit.latest(mechanical_id)
        if audit_record.event_type != "COMMITTED":
            raise GovernedProviderDenied("canonical effect lacks committed audit")
        runtime.audit.verify_fence_consistency(runtime.fence)
        return {
            "schema": "HOST_AUTHZ_GOVERNED_PROVIDER_OUTCOME_V1",
            "effect_id": command.effect_id,
            "mechanical_effect_id": mechanical_id,
            "provider_id": self._provider_id,
            "provider_instance_id": self._instance_id,
            "result_digest": result.result_digest,
            "fence_state": result.fence_receipt.state.value,
        }


def build_governed_provider_worker(
    *, state_path: str | Path, runtime: QualifiedVeraRuntime,
    provider_authority: HmacProviderAuthority, provider_id: str,
    provider_instance_id: str, host_id: str, epoch: int,
    host_command_public_key: bytes, receipt_signer: Ed25519PrivateKey,
    witness_start_public_key: bytes, witness_leader_epoch: int,
    effect_witness: EffectWitness,
    trusted_clock: Callable[[], int],
) -> ProviderCustodyWorker:
    """Construct one *exact* ProviderCustodyWorker with no arbitrary effect callback.

    The host RPC must reach a dedicated provider process using this factory.
    The factory intentionally has no ``execute`` parameter; the only physical
    execution path is the captured ``QualifiedVeraRuntime`` transport.
    """
    governed = GovernedProviderExecutor(
        runtime=runtime, authority=provider_authority,
        provider_id=provider_id, provider_instance_id=provider_instance_id,
    )
    return ProviderCustodyWorker(
        state_path=state_path, provider_id=provider_id,
        provider_instance_id=provider_instance_id, host_id=host_id,
        epoch=epoch, host_command_public_key=host_command_public_key,
        receipt_signer=receipt_signer,
        witness_start_public_key=witness_start_public_key,
        witness_leader_epoch=witness_leader_epoch,
        effect_witness=effect_witness, execute=governed,
        trusted_clock=trusted_clock,
    )
