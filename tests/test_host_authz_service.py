"""One-process synthetic tests; not host/provider/antirollback qualification."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.bindings import (
    HostBindingSnapshot,
    PrincipalBinding,
    ProviderBinding,
)
from vera_core.host_authz.grants import (
    ApprovedGrant,
    SIGNATURE_CONTEXT,
    SIGNED_GRANT_SCHEMA,
    SignedGrantVerifier,
)
from vera_core.host_authz.ledger import ClaimLedger
from vera_core.host_authz.service import (
    AuthorizationDenied,
    EffectOutcomeUnknown,
    HostAuthorizationService,
    HostProviderHandle,
    ProviderAcknowledgement,
)


class TestOnlyWitness:
    """NOT external, monotonic or cross-host. Never use in deployment."""

    def attest_claim(self, *, authority_id, epoch, sequence, grant_id, claim_digest):
        return True

    def attest_revocation(self, *, authority_id, epoch, sequence, grant_id):
        return True


def _canonical(body):
    return json.dumps(
        body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _make(tmp_path, *, consent=True, provider_live=True, dispatch=None):
    signing = Ed25519PrivateKey.generate()
    provider_signing = Ed25519PrivateKey.generate()
    provider_public = provider_signing.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    now = {"value": 2000}
    clock = lambda: now["value"]
    principal = PrincipalBinding(
        "uid:1001", "model-a", "adapter-a", "runtime-a", "subject-a",
        frozenset({"safe-provider"}),
    )
    other = PrincipalBinding(
        "uid:1002", "model-b", "adapter-b", "runtime-b", "subject-b",
        frozenset({"safe-provider"}),
    )
    provider = ProviderBinding(
        "safe-provider", "provider-instance-v1", frozenset({"inspect"}),
    )
    bindings = HostBindingSnapshot(
        "host-a", "issuer-a", 7,
        {principal.peer_key: principal, other.peer_key: other},
        {provider.provider_id: provider},
    )
    verifier = SignedGrantVerifier(
        signing.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ),
        issuer_id="issuer-a", host_id="host-a", epoch=7, trusted_clock=clock,
    )
    ledger = ClaimLedger(tmp_path / "claims.sqlite", "host-a", 7, TestOnlyWitness())
    calls = []

    def acknowledged(instruction):
        calls.append(instruction)
        if dispatch is not None:
            return dispatch(instruction)
        unsigned = ProviderAcknowledgement(
            effect_id=instruction.effect_id,
            provider_id=instruction.provider_id,
            provider_instance_id=instruction.provider_instance_id,
            claim_sequence=instruction.claim_sequence,
            request_digest=instruction.request_digest,
            provider_receipt_digest="a" * 64,
            receipt_signature=b"",
        )
        return replace(
            unsigned,
            receipt_signature=provider_signing.sign(
                b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\x00"
                + canonical_json_bytes(unsigned.signed_body())
            ),
        )

    provider_map = {
        "safe-provider": HostProviderHandle(
            "safe-provider", "provider-instance-v1", provider_public, acknowledged,
        )
    }
    service = HostAuthorizationService(
        bindings, verifier, ledger, provider_map, clock,
        consent_status=(consent if callable(consent) else
                        (lambda _grant, _now: consent)) if consent is not None else None,
        provider_status=(lambda _provider, _now: provider_live)
        if provider_live is not None else None,
    )
    return {
        "signing": signing,
        "provider_signing": provider_signing,
        "provider_public": provider_public,
        "clock": now,
        "bindings": bindings,
        "provider_map": provider_map,
        "service": service,
        "calls": calls,
        "ledger": ledger,
    }


def _sign(ctx, payload, **overrides):
    body = {
        "grant_id": "grant-1",
        "issuer_id": "issuer-a",
        "host_id": "host-a",
        "epoch": 7,
        "peer_key": "uid:1001",
        "model_id": "model-a",
        "adapter_id": "adapter-a",
        "runtime_id": "runtime-a",
        "subject_id": "subject-a",
        "participant_id": "participant-a",
        "purpose": "consented inspection",
        "provider_id": "safe-provider",
        "provider_instance_id": "provider-instance-v1",
        "operation": "inspect",
        "request_digest": sha256(canonical_json_bytes(payload)).hexdigest(),
        "not_before": 1900,
        "expires_at": 2100,
    }
    body.update(overrides)
    grant = ApprovedGrant(**body)
    sig = ctx["signing"].sign(SIGNATURE_CONTEXT + _canonical(grant.canonical_body()))
    return _canonical({
        "schema": SIGNED_GRANT_SCHEMA,
        "grant": grant.canonical_body(),
        "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii"),
    })


def _execute(ctx, grant, payload=None, *, peer_key="uid:1001"):
    return ctx["service"].execute(
        peer_key=peer_key,
        signed_grant=grant,
        provider_id="safe-provider",
        operation="inspect",
        request_payload={"record": "synthetic"} if payload is None else payload,
    )


def test_coherent_service_signed_grant_to_durable_claim_to_ack(tmp_path):
    ctx = _make(tmp_path)
    grant = _sign(ctx, {"record": "synthetic"})
    receipt = _execute(ctx, grant)
    assert receipt.public_body()["state"] == "ACKNOWLEDGED"
    assert receipt.public_body()["claim_sequence"] == 1
    assert ctx["ledger"].read("grant-1").state == "COMPLETED"
    assert len(ctx["calls"]) == 1
    assert ctx["calls"][0].participant_id == "participant-a"
    assert ctx["calls"][0].purpose == "consented inspection"


def test_cross_model_peer_cannot_consume_real_signed_grant(tmp_path):
    ctx = _make(tmp_path)
    grant = _sign(ctx, {"record": "synthetic"})
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, grant, peer_key="uid:1002")
    assert ctx["ledger"].read("grant-1") is None
    assert not ctx["calls"]


@pytest.mark.parametrize("field,value", [
    ("model_id", "model-b"),
    ("subject_id", "subject-b"),
    ("host_id", "host-b"),
    ("provider_id", "different-provider"),
    ("provider_instance_id", "other-instance"),
    ("adapter_id", "adapter-b"),
])
def test_even_valid_signature_cannot_change_bound_identity(tmp_path, field, value):
    ctx = _make(tmp_path)
    grant = _sign(ctx, {"record": "synthetic"}, **{field: value})
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, grant)
    assert ctx["ledger"].read("grant-1") is None


def test_request_payload_digest_cannot_be_changed(tmp_path):
    ctx = _make(tmp_path)
    grant = _sign(ctx, {"record": "synthetic"})
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, grant, payload={"record": "altered"})
    assert ctx["ledger"].read("grant-1") is None


def test_exact_grant_is_one_use_even_after_success(tmp_path):
    ctx = _make(tmp_path)
    grant = _sign(ctx, {"record": "synthetic"})
    _execute(ctx, grant)
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, grant)
    assert len(ctx["calls"]) == 1


def test_host_consent_or_provider_status_unknown_denies_before_claim(tmp_path):
    for i, kwargs in enumerate((
        {"consent": None}, {"consent": False},
        {"provider_live": None}, {"provider_live": False},
    )):
        ctx = _make(tmp_path / str(i), **kwargs)
        grant = _sign(ctx, {"record": "synthetic"})
        with pytest.raises(AuthorizationDenied):
            _execute(ctx, grant)
        assert ctx["ledger"].read("grant-1") is None


def test_revoked_after_claim_before_dispatch_denies(tmp_path):
    state = {"checks": 0, "ledger": None}

    def revoke_at_second_check(grant, _now):
        state["checks"] += 1
        if state["checks"] == 2:
            state["ledger"].revoke(grant.grant_id)
        return True

    ctx = _make(tmp_path, consent=revoke_at_second_check)
    state["ledger"] = ctx["ledger"]
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, _sign(ctx, {"record": "synthetic"}))
    assert ctx["ledger"].read("grant-1").revoked
    assert not ctx["calls"]


def test_mutating_external_provider_registry_does_not_rebind_dispatch(tmp_path):
    ctx = _make(tmp_path)
    old_handle = ctx["provider_map"]["safe-provider"]
    object.__setattr__(old_handle, "dispatch", lambda _: 2)
    ctx["provider_map"]["safe-provider"] = HostProviderHandle(
        "safe-provider", "provider-instance-v1", ctx["provider_public"], lambda _: 2,
    )
    receipt = _execute(ctx, _sign(ctx, {"record": "synthetic"}))
    assert receipt.state == "ACKNOWLEDGED"
    assert len(ctx["calls"]) == 1


def test_mutable_provider_object_rejected_by_service(tmp_path):
    ctx = _make(tmp_path)

    class MutableProvider:
        provider_id = "safe-provider"
        provider_instance_id = "provider-instance-v1"

        def dispatch(self, _instruction):
            return "fake"

    with pytest.raises(TypeError):
        HostAuthorizationService(
            ctx["bindings"], ctx["service"].grant_verifier,
            ctx["ledger"], {"safe-provider": MutableProvider()},
            lambda: 2000,
        )


def test_provider_exception_is_ambiguous_and_grant_cannot_retry(tmp_path):
    def broken(_instruction):
        raise OSError("connection dropped after possible provider effect")

    ctx = _make(tmp_path, dispatch=broken)
    grant = _sign(ctx, {"record": "synthetic"})
    with pytest.raises(EffectOutcomeUnknown):
        _execute(ctx, grant)
    assert ctx["ledger"].read("grant-1").state == "AMBIGUOUS"
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, grant)
    assert len(ctx["calls"]) == 1


def test_wrong_ack_receipt_is_ambiguous(tmp_path):
    def forged(instruction):
        return ProviderAcknowledgement(
            "different-effect", instruction.provider_id,
            instruction.provider_instance_id, instruction.claim_sequence,
            instruction.request_digest, "c" * 64, b"x" * 64,
        )

    ctx = _make(tmp_path, dispatch=forged)
    grant = _sign(ctx, {"record": "synthetic"})
    with pytest.raises(EffectOutcomeUnknown):
        _execute(ctx, grant)
    assert ctx["ledger"].read("grant-1").state == "AMBIGUOUS"


def test_exact_shape_ack_from_unpinned_provider_key_is_denied(tmp_path):
    attacker = Ed25519PrivateKey.generate()

    def forged(instruction):
        unsigned = ProviderAcknowledgement(
            instruction.effect_id, instruction.provider_id,
            instruction.provider_instance_id, instruction.claim_sequence,
            instruction.request_digest, "a" * 64, b"",
        )
        return replace(
            unsigned,
            receipt_signature=attacker.sign(
                b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\x00"
                + canonical_json_bytes(unsigned.signed_body())
            ),
        )

    ctx = _make(tmp_path, dispatch=forged)
    with pytest.raises(EffectOutcomeUnknown):
        _execute(ctx, _sign(ctx, {"record": "synthetic"}))
    assert ctx["ledger"].read("grant-1").state == "AMBIGUOUS"


def test_keyboard_interrupt_after_claim_never_reissues(tmp_path):
    def interrupted(_instruction):
        raise KeyboardInterrupt()

    ctx = _make(tmp_path, dispatch=interrupted)
    grant = _sign(ctx, {"record": "synthetic"})
    with pytest.raises(KeyboardInterrupt):
        _execute(ctx, grant)
    assert ctx["ledger"].read("grant-1").state == "AMBIGUOUS"
    with pytest.raises(AuthorizationDenied):
        _execute(ctx, grant)


def test_concurrent_same_grant_single_dispatch(tmp_path):
    ctx = _make(tmp_path)
    grant = _sign(ctx, {"record": "synthetic"})

    def attempt(_):
        try:
            _execute(ctx, grant)
            return True
        except AuthorizationDenied:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(attempt, range(32)))
    assert sum(outcomes) == 1
    assert len(ctx["calls"]) == 1
    assert ctx["ledger"].read("grant-1").state == "COMPLETED"
