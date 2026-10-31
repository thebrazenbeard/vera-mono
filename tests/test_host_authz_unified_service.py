"""Coherent H2 source tests; synthetic leader/provider are not production trust roots."""

from __future__ import annotations

import base64
from dataclasses import replace
from hashlib import sha256
import json
import os
import shutil
import threading
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from vera_core.host_authz.bindings import (
    HostBindingSnapshot, PrincipalBinding, ProviderBinding,
)
from vera_core.host_authz.grants import (
    ApprovedGrant, SignedGrantVerifier, SIGNATURE_CONTEXT as GRANT_CONTEXT,
    SIGNED_GRANT_SCHEMA,
)
from vera_core.host_authz.ipc import HostIPCError, QualifiedUnixAuthorityServer, _execute_request
from vera_core.host_authz.peer_isolation import HostPeerIsolationPlan, LinuxProcessPin
from vera_core.host_authz.provider_custody import (
    HostDispatchSigner, ProviderCustodyWorker,
)
from vera_core.host_authz.service import (
    AuthorizationDenied, AuthorizedEffectReceipt, EffectOutcomeUnknown,
    HostAuthorizationService,
)
from vera_core.host_authz.unified_authority import (
    RECEIPT_SCHEMA, SIGNATURE_CONTEXT, UnifiedAuthorityDenied,
    UnifiedHostAuthority,
)
from vera_core.host_authz.unified_service import UnifiedAuthorizationService


NOW = 2000
PAYLOAD = {"item": "synthetic"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


class Leader:
    """Sole leader in memory for tests; does not prove external antirollback."""

    def __init__(self, key):
        self.key = key
        self.sequence = 0
        self.events = []
        self.lock = threading.Lock()

    def allocate_event(self, request):
        raw = json.loads(request)
        with self.lock:
            self.sequence += 1
            body = {field: raw[field] for field in (
                "host_id", "issuer_id", "epoch", "challenge", "kind", "event_digest"
            )}
            body.update({"leader_epoch": 11, "sequence": self.sequence, "approved": True})
            self.events.append((body, raw["event"]))
            signature = self.key.sign(SIGNATURE_CONTEXT + canonical(body))
            return canonical({"schema": RECEIPT_SCHEMA, "body": body,
                              "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode()})


class SyntheticEffectFence:
    """Synthetic external one-use admission. Not production independence."""

    def __init__(self):
        self.seen = set()

    def reserve_provider_effect(self, **kwargs):
        scope = (kwargs["host_id"], kwargs["epoch"], kwargs["effect_id"])
        if scope in self.seen:
            return False
        self.seen.add(scope)
        return True


def fixture(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    issuer_key = Ed25519PrivateKey.generate()
    provider_key = Ed25519PrivateKey.generate()
    witness_key = Ed25519PrivateKey.generate()
    command_key = Ed25519PrivateKey.generate()
    principal = PrincipalBinding("uid:1001", "model-A", "adapter-A", "runtime-A",
                                 "subject-A", frozenset({"provider-A"}))
    provider_binding = ProviderBinding("provider-A", "instance-A", frozenset({"observe"}))
    bindings = HostBindingSnapshot("host-A", "issuer-A", 7,
                                   {principal.peer_key: principal},
                                   {provider_binding.provider_id: provider_binding})
    verifier = SignedGrantVerifier(issuer_key.public_key().public_bytes_raw(),
                                   issuer_id="issuer-A", host_id="host-A", epoch=7,
                                   trusted_clock=lambda: NOW)
    witness = Leader(witness_key)
    authority = UnifiedHostAuthority(
        tmp_path / "authority.sqlite", bindings=bindings,
        grant_verifier=verifier, witness=witness,
        witness_public_key=witness_key.public_key().public_bytes_raw(),
        provider_public_keys={"provider-A": provider_key.public_key().public_bytes_raw()},
        trusted_clock=lambda: NOW, consent_status=lambda grant, now: True,
        leader_epoch=11,
    )
    signer = HostDispatchSigner(command_key, host_id="host-A", epoch=7,
                                trusted_clock=lambda: NOW)
    effects = []
    effect_fence = SyntheticEffectFence()
    worker = ProviderCustodyWorker(
        state_path=tmp_path / "effects.sqlite", provider_id="provider-A",
        provider_instance_id="instance-A", host_id="host-A", epoch=7,
        host_command_public_key=signer.public_key_bytes,
        receipt_signer=provider_key,
        effect_witness=effect_fence,
        execute=lambda command: effects.append(command) or {"ok": True},
        trusted_clock=lambda: NOW,
        witness_start_public_key=witness_key.public_key().public_bytes_raw(),
        witness_leader_epoch=11,
    )
    service = UnifiedAuthorizationService(
        authority=authority, host_command_signer=signer,
        provider_workers={"provider-A": worker},
        unqualified_in_process_fixture=True)
    grant = ApprovedGrant(
        grant_id="grant-A", issuer_id="issuer-A", host_id="host-A", epoch=7,
        peer_key="uid:1001", model_id="model-A", adapter_id="adapter-A",
        runtime_id="runtime-A", subject_id="subject-A",
        participant_id="participant-A", purpose="approved observation",
        provider_id="provider-A", provider_instance_id="instance-A",
        operation="observe", request_digest=sha256(canonical(PAYLOAD)).hexdigest(),
        not_before=1900, expires_at=2100,
    )
    signed = canonical({"schema": SIGNED_GRANT_SCHEMA, "grant": grant.canonical_body(),
                        "signature": base64.urlsafe_b64encode(issuer_key.sign(
                            GRANT_CONTEXT + canonical(grant.canonical_body()))).rstrip(b"=").decode()})
    return locals()


def execute(ctx, **changes):
    data = {"peer_key": "uid:1001", "signed_grant": ctx["signed"],
            "provider_id": "provider-A", "operation": "observe",
            "request_payload": PAYLOAD}
    data.update(changes)
    return ctx["service"].execute(**data)


def test_one_end_to_end_admitted_effect_uses_single_witness_order(tmp_path):
    ctx = fixture(tmp_path)
    receipt = execute(ctx)
    assert type(receipt) is AuthorizedEffectReceipt
    assert receipt.public_body()["state"] == "ACKNOWLEDGED"
    assert set(receipt.public_body()) == {
        "schema", "state", "grant_id", "effect_id", "provider_id",
        "provider_instance_id", "claim_sequence", "provider_receipt_digest",
    }
    assert len(ctx["effects"]) == 1
    assert ctx["authority"].read(ctx["grant"].grant_id).state == "COMPLETED"
    assert [body["kind"] for body, _ in ctx["witness"].events] == [
        "CLAIM", "START", "COMPLETE"]


def test_before_start_revocation_wins_without_provider_effect(tmp_path):
    ctx = fixture(tmp_path)
    original_start = ctx["authority"].start

    def revoke_first(grant_id):
        ctx["authority"].revoke_scope(ctx["grant"])
        return original_start(grant_id)

    with patch.object(ctx["authority"], "start", side_effect=revoke_first):
        with pytest.raises(UnifiedAuthorityDenied, match="revoked"):
            execute(ctx)
    assert len(ctx["effects"]) == 0
    assert ctx["authority"].read("grant-A").state == "CLAIMED"


def test_after_start_revocation_does_not_undo_one_effect(tmp_path):
    ctx = fixture(tmp_path)
    original = ProviderCustodyWorker.dispatch

    def revoke_then_dispatch(worker, *args, **kwargs):
        ctx["authority"].revoke_scope(ctx["grant"])
        return original(worker, *args, **kwargs)

    with patch.object(ProviderCustodyWorker, "dispatch", side_effect=revoke_then_dispatch):
        assert execute(ctx).public_body()["state"] == "ACKNOWLEDGED"
    assert len(ctx["effects"]) == 1
    assert [body["kind"] for body, _ in ctx["witness"].events] == [
        "CLAIM", "START", "REVOKE_SCOPE", "COMPLETE"]


def test_replay_grant_is_rejected_before_second_effect(tmp_path):
    ctx = fixture(tmp_path)
    execute(ctx)
    with pytest.raises(UnifiedAuthorityDenied, match="already claimed"):
        execute(ctx)
    assert len(ctx["effects"]) == 1


@pytest.mark.parametrize("changes", [
    {"peer_key": "uid:1002"}, {"provider_id": "provider-B"},
    {"operation": "erase"}, {"request_payload": {"item": "wrong"}},
])
def test_caller_cannot_retarget_principal_provider_operation_or_payload(tmp_path, changes):
    ctx = fixture(tmp_path)
    with pytest.raises((AuthorizationDenied, UnifiedAuthorityDenied)):
        execute(ctx, **changes)
    assert len(ctx["effects"]) == 0
    assert ctx["witness"].events == []


def test_missing_or_tampered_lease_never_calls_physical_transport(tmp_path):
    ctx = fixture(tmp_path)
    original_start = ctx["authority"].start

    def tamper_start(grant_id):
        lease = original_start(grant_id)
        return type(lease)(b"corrupt", lease.body, lease.event)

    with patch.object(ctx["authority"], "start", side_effect=tamper_start):
        with pytest.raises(EffectOutcomeUnknown):
            execute(ctx)
    assert ctx["authority"].read("grant-A").state == "UNKNOWN"
    assert not ctx["effects"]
    with pytest.raises(UnifiedAuthorityDenied, match="already claimed"):
        execute(ctx)


def test_missing_provider_ack_is_nonretryable_unknown(tmp_path):
    ctx = fixture(tmp_path)
    with patch.object(ProviderCustodyWorker, "dispatch", side_effect=OSError("ACK lost")):
        with pytest.raises(EffectOutcomeUnknown):
            execute(ctx)
    assert ctx["authority"].read("grant-A").state == "UNKNOWN"
    assert len(ctx["effects"]) == 0
    with pytest.raises(UnifiedAuthorityDenied, match="already claimed"):
        execute(ctx)


@pytest.mark.parametrize("attack", ["swapped-signer", "replay-different-effect"])
def test_provider_ack_swap_and_replay_cannot_claim_completion(tmp_path, attack):
    ctx = fixture(tmp_path)
    genuine_dispatch = ProviderCustodyWorker.dispatch

    def corrupted_ack(worker, *args, **kwargs):
        ack = genuine_dispatch(worker, *args, **kwargs)
        if attack == "swapped-signer":
            forged = replace(ack, receipt_signature=Ed25519PrivateKey.generate().sign(
                b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0" + canonical(ack.signed_body())))
        else:
            forged = replace(ack, effect_id="some-other-effect")
        return forged

    with patch.object(ProviderCustodyWorker, "dispatch", side_effect=corrupted_ack):
        with pytest.raises(EffectOutcomeUnknown):
            execute(ctx)
    assert len(ctx["effects"]) == 1
    assert ctx["authority"].read("grant-A").state == "UNKNOWN"
    with pytest.raises(UnifiedAuthorityDenied, match="already claimed"):
        execute(ctx)


def test_cloned_authority_store_without_original_exclusive_witness_position_fails(tmp_path):
    ctx = fixture(tmp_path)
    clone = tmp_path / "snapshot-before-effect.sqlite"
    shutil.copyfile(ctx["authority"].path, clone)
    clone.chmod(0o600)
    execute(ctx)
    cloned = UnifiedHostAuthority(
        clone, bindings=ctx["bindings"], grant_verifier=ctx["verifier"],
        witness=ctx["witness"], witness_public_key=ctx["witness_key"].public_key().public_bytes_raw(),
        provider_public_keys={"provider-A": ctx["provider_key"].public_key().public_bytes_raw()},
        trusted_clock=lambda: NOW, consent_status=lambda grant, now: True,
        leader_epoch=11,
    )
    with pytest.raises(UnifiedAuthorityDenied):
        cloned.claim(ctx["signed"], "uid:1001", PAYLOAD)
    assert len(ctx["effects"]) == 1


def test_receipt_signer_and_worker_registry_cannot_be_swapped(tmp_path):
    ctx = fixture(tmp_path)
    with pytest.raises(AuthorizationDenied, match="ACK key"):
        other = ProviderCustodyWorker(
            state_path=tmp_path / "other-effects.sqlite", provider_id="provider-A",
            provider_instance_id="instance-A", host_id="host-A", epoch=7,
            host_command_public_key=ctx["signer"].public_key_bytes,
            receipt_signer=Ed25519PrivateKey.generate(), effect_witness=ctx["effect_fence"],
            execute=lambda _: pytest.fail("effect transport must not run"),
            trusted_clock=lambda: NOW,
            witness_start_public_key=ctx["witness_key"].public_key().public_bytes_raw(),
            witness_leader_epoch=11,
        )
        UnifiedAuthorizationService(authority=ctx["authority"],
                                    host_command_signer=ctx["signer"],
                                    provider_workers={"provider-A": other},
                                    unqualified_in_process_fixture=True)


def test_no_generic_model_callback_or_legacy_service_route(tmp_path):
    ctx = fixture(tmp_path)
    assert not isinstance(ctx["service"], HostAuthorizationService)
    with pytest.raises(TypeError):
        UnifiedAuthorizationService(authority=ctx["authority"],
                                    host_command_signer=ctx["signer"],
                                    provider_workers={"provider-A": lambda _: "effect"},
                                    unqualified_in_process_fixture=True)


def test_mutated_worker_instance_method_is_not_an_alternative_effect_path(tmp_path):
    ctx = fixture(tmp_path)
    called = []
    ctx["worker"].dispatch = lambda *_a, **_kw: called.append("bypass")
    assert execute(ctx).public_body()["state"] == "ACKNOWLEDGED"
    assert called == []
    assert len(ctx["effects"]) == 1


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "getuid"),
                    reason="qualified Linux peer endpoint only")
def test_qualified_unix_endpoint_rejects_in_process_fixture_even_when_composed(tmp_path):
    ctx = fixture(tmp_path)
    if os.getuid() == 1001:
        pytest.skip("model UID cannot be the authorization service UID")
    plan = HostPeerIsolationPlan(
        f"uid:{os.getuid()}", ctx["bindings"],
        {"uid:1001": LinuxProcessPin(123456, 1001, 1)},
    )
    with pytest.raises(HostIPCError, match="isolated provider RPC"):
        QualifiedUnixAuthorityServer(tmp_path / "authority.sock", ctx["service"], plan=plan)
    frame = canonical({
        "signed_grant_b64": base64.b64encode(ctx["signed"]).decode(),
        "provider_id": "provider-A", "operation": "observe",
        "request_payload": PAYLOAD,
    })
    # The unqualified fixture retains a source-only frame exercise, but it
    # cannot be installed behind the privileged qualified Unix endpoint.
    response = json.loads(_execute_request(ctx["service"], "uid:1001", frame))
    assert response["ok"] is True
    assert response["receipt"]["state"] == "ACKNOWLEDGED"
    assert len(ctx["effects"]) == 1
