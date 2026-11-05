"""Coherent host-only signed-grant -> START lease -> provider custody service.

The caller has no route for supplying a principal, provider callback, dispatch
signing key, receipt signing key or witness. ``peer_key`` MUST be determined by
the kernel-authenticated ``QualifiedUnixAuthorityServer``, not a request field.

This is an integration seam, NOT a claim of qualified physical isolation:
production must run the provider worker behind a separately privileged OS
process boundary, bind its physical execution to QualifiedVeraRuntime's
governed gateway, and provision a genuinely external exclusive witness.
"""

from __future__ import annotations

from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .provider_custody import HostDispatchSigner, ProviderCustodyWorker
from .provider_rpc import ProviderCustodyRPCClient
from .service import (
    AuthorizationDenied,
    AuthorizedEffectReceipt,
    EffectOutcomeUnknown,
    ProviderDispatch,
)
from .unified_authority import UnifiedHostAuthority


class UnifiedAuthorizationService:
    """Immutable host-provisioned integration; no model-supplied execution route.

    A successful receipt means both the provider's pinned-key ACK and the
    authority's independently witnessed COMPLETE event were accepted. Anything
    ambiguous after START fails without replay or redispatch.
    """

    __slots__ = ("_authority", "_signer", "_workers", "_clients",
                 "_unqualified_in_process_fixture")

    def __init__(
        self,
        *,
        authority: UnifiedHostAuthority,
        host_command_signer: HostDispatchSigner,
        provider_clients: Mapping[str, ProviderCustodyRPCClient] | None = None,
        provider_workers: Mapping[str, ProviderCustodyWorker] | None = None,
        unqualified_in_process_fixture: bool = False,
    ) -> None:
        if type(authority) is not UnifiedHostAuthority:
            raise TypeError("requires exact host-owned unified authority")
        if type(host_command_signer) is not HostDispatchSigner:
            raise TypeError("requires exact host-owned command signer")
        if type(unqualified_in_process_fixture) is not bool:
            raise TypeError("fixture mode must be an exact host-owned bool")
        if unqualified_in_process_fixture:
            if provider_clients is not None or type(provider_workers) not in (dict, MappingProxyType):
                raise TypeError("fixture requires only an in-process provider worker mapping")
            registry = provider_workers
        else:
            if provider_workers is not None or type(provider_clients) not in (dict, MappingProxyType):
                raise TypeError("qualified service requires separately provisioned provider RPC clients")
            registry = provider_clients
            # Model accounts, the host service, and every provider custody
            # principal MUST be different OS owners. Otherwise a model could
            # alter the provider's 0700 socket/state/key directory directly.
            model_uids: set[int] = set()
            for peer in authority.bindings.principals:
                if not peer.startswith("uid:") or not peer[4:].isdecimal() or str(int(peer[4:])) != peer[4:]:
                    raise AuthorizationDenied("qualified Linux authority needs canonical model UID bindings")
                model_uids.add(int(peer[4:]))
            provider_uids = [client._provider_uid for client in registry.values()
                             if type(client) is ProviderCustodyRPCClient]
            if any(uid in model_uids for uid in provider_uids):
                raise AuthorizationDenied("provider OS UID overlaps an admitted model OS UID")
            if len(provider_uids) != len(set(provider_uids)):
                raise AuthorizationDenied("distinct provider instances need isolated OS UIDs")
        if (host_command_signer.host_id != authority.bindings.host_id
                or host_command_signer.epoch != authority.bindings.epoch):
            raise AuthorizationDenied("command signer host/epoch is not pinned authority")
        if set(registry) != set(authority.bindings.providers):
            raise AuthorizationDenied("provider worker registry does not match pinned bindings")
        copied: dict[str, ProviderCustodyWorker] = {}
        clients: dict[str, ProviderCustodyRPCClient] = {}
        for provider_id, worker in registry.items():
            bound = authority.bindings.providers[provider_id]
            if unqualified_in_process_fixture and type(worker) is not ProviderCustodyWorker:
                raise TypeError("fixture requires an exact provider worker")
            if not unqualified_in_process_fixture and type(worker) is not ProviderCustodyRPCClient:
                raise TypeError("qualified service requires exact isolated provider RPC client")
            if ((worker.provider_id, worker.provider_instance_id,
                 worker.host_id, worker.epoch)
                    != (bound.provider_id, bound.provider_instance_id,
                        authority.bindings.host_id, authority.bindings.epoch)):
                raise AuthorizationDenied("provider custody identity differs from immutable host binding")
            pinned_command_key = (worker._host_key.public_bytes_raw() if unqualified_in_process_fixture
                                  else worker.host_command_public_key_bytes)
            if pinned_command_key != host_command_signer.public_key_bytes:
                raise AuthorizationDenied("provider command trust root is not host command signer")
            if worker.receipt_public_key_bytes != authority._provider_keys[provider_id]:
                raise AuthorizationDenied("provider ACK key is not authority's pinned provider root")
            # A mutable same-process object still does not prove OS isolation.
            # Require the witness key to be pinned identically at each end.
            pinned_witness_key = (worker._witness_start_public_key if unqualified_in_process_fixture
                                  else worker.witness_start_public_key)
            if pinned_witness_key != authority._witness_key:
                raise AuthorizationDenied("provider START witness trust root is not authority's root")
            pinned_leader_epoch = (worker._witness_leader_epoch if unqualified_in_process_fixture
                                   else worker.witness_leader_epoch)
            if pinned_leader_epoch != authority._leader_epoch:
                raise AuthorizationDenied("provider witness leader epoch is not authority's epoch")
            if unqualified_in_process_fixture:
                copied[provider_id] = worker
            else:
                clients[provider_id] = worker
        self._authority = authority
        self._signer = host_command_signer
        self._workers = MappingProxyType(copied)
        self._clients = MappingProxyType(clients)
        self._unqualified_in_process_fixture = unqualified_in_process_fixture

    def execute(
        self, *, peer_key: str, signed_grant: bytes,
        provider_id: str, operation: str, request_payload: Any,
    ) -> AuthorizedEffectReceipt:
        """One effect attempt. Never retry after START or expose provider data.

        ``peer_key`` is a trusted service-entry argument derived from an OS
        credential, NEVER a user/model field. Exact snapshot/grant matching
        precedes the exclusive claim transaction, and START is the one global
        revocation-versus-effect ordering boundary.
        """
        if type(peer_key) is not str or type(provider_id) is not str or type(operation) is not str:
            raise AuthorizationDenied("invalid authenticated request")
        if type(signed_grant) is not bytes:
            raise AuthorizationDenied("requires exact signed grant bytes")
        try:
            grant = self._authority.grant_verifier.verify(signed_grant)
            principal = self._authority.bindings.principal_for_peer(peer_key)
            provider = self._authority.bindings.provider_for(principal, provider_id, operation)
            if (grant.peer_key != peer_key or grant.provider_id != provider_id
                    or grant.operation != operation
                    or grant.provider_instance_id != provider.provider_instance_id):
                raise AuthorizationDenied("signed provider/operation or peer retargeted")
            # Canonical round-trip detaches request data from mutable caller aliases.
            encoded = canonical_json_bytes(request_payload)
            payload = json.loads(encoded)
            if sha256(encoded).hexdigest() != grant.request_digest:
                raise AuthorizationDenied("request payload is not grant-bound")
            worker = (self._workers if self._unqualified_in_process_fixture else self._clients)[provider_id]
        except (KeyError, ValueError, TypeError, PermissionError) as exc:
            raise AuthorizationDenied("signed request not admitted") from exc

        claim = self._authority.claim(signed_grant, peer_key, payload)
        # The claim can survive process death. It cannot be claimed again.
        # If revocation occurs now, authority.start() fails before any effect.
        lease = self._authority.start(claim.grant_id)

        command = ProviderDispatch(
            effect_id=claim.effect_id,
            grant_id=claim.grant_id,
            provider_id=provider_id,
            provider_instance_id=provider.provider_instance_id,
            operation=operation,
            request_digest=claim.request_digest,
            claim_sequence=claim.claim_sequence,
            participant_id=grant.participant_id,
            purpose=grant.purpose,
            request_payload=payload,
        )
        try:
            signed_command = self._signer.sign(command)
            # Provider independently verifies *both* authority signatures and
            # spends the physical, durable one-use fence BEFORE external effect.
            # Invoke the *exact trusted implementation*, not a writable
            # instance-method alias that could be replaced after provisioning.
            if self._unqualified_in_process_fixture:
                acknowledgement = ProviderCustodyWorker.dispatch(
                    worker, signed_command, start_lease=lease,
                )
            else:
                acknowledgement = ProviderCustodyRPCClient.dispatch(
                    worker, signed_command, start_lease=lease,
                )
            completed = self._authority.complete(claim.grant_id, acknowledgement)
            if completed.state != "COMPLETED" or not completed.provider_receipt_digest:
                raise RuntimeError("no durable completed state")
        except BaseException as exc:
            # START was already durably allocated. Even if the provider call
            # threw before transport, never infer zero physical effects or retry.
            try:
                self._authority.mark_unknown(claim.grant_id)
            except Exception:
                # The original STARTED ledger row remains non-replayable.
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise EffectOutcomeUnknown(
                "provider outcome unconfirmed after START; reconcile without replay"
            ) from exc
        return AuthorizedEffectReceipt(
            grant_id=claim.grant_id,
            effect_id=claim.effect_id,
            provider_id=provider_id,
            provider_instance_id=provider.provider_instance_id,
            claim_sequence=claim.claim_sequence,
            provider_receipt_digest=completed.provider_receipt_digest,
        )
