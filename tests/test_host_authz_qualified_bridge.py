"""Synthetic-host bridge gate tests; not installed provider qualification."""

from __future__ import annotations

from hashlib import sha256
import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core import (
    HmacProviderAuthority, LifecycleActionDenied, OutboundTrustError,
    QualifiedVeraRuntime,
)
from vera_core.host_authz.bindings import (
    HostBindingSnapshot, PrincipalBinding, ProviderBinding,
)
from vera_core.host_authz.grants import (
    ApprovedGrant, SIGNATURE_CONTEXT, SIGNED_GRANT_SCHEMA, SignedGrantVerifier,
)
from vera_core.host_authz.ledger import ClaimLedger
from vera_core.host_authz.qualified_bridge import (
    QualifiedBridgeDenied,
    qualified_provider_handle,
)
from vera_core.host_authz.service import (
    AuthorizationDenied, HostAuthorizationService, ProviderDispatch,
)
from vera_memory import AdmissionRequest, MemoryClass
from test_qualified_runtime import StubProviderTransport, accepted_state


PROVIDER = "example-provider"
INSTANCE = "pinned-provider-instance"


def _runtime(tmp_path, *, trusted=True):
    state = accepted_state(tmp_path)
    authority = HmacProviderAuthority("host-provider-issuer", PROVIDER, b"p" * 32)
    if trusted:
        trust = state.outbound_trust_registry()
        trust.register(
            authority_id=authority.authority_id,
            role="PROVIDER",
            provider_id=PROVIDER,
            key_id=authority.key_id,
            key_digest=authority.key_digest,
            expected_registry_generation=trust.generation,
        )
    transport = StubProviderTransport(PROVIDER)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: authority},
        provider_execution_transports={PROVIDER: transport},
    )
    signer = Ed25519PrivateKey.generate()
    return runtime, authority, transport, signer


def _instruction(*, effect_id="bridge-test", provider_id=PROVIDER,
                 provider_instance_id=INSTANCE, payload=None):
    request = {"record": "synthetic"} if payload is None else payload
    return ProviderDispatch(
        effect_id=effect_id,
        grant_id="grant-bridge",
        provider_id=provider_id,
        provider_instance_id=provider_instance_id,
        operation="inspect",
        request_digest=sha256(canonical_json_bytes(request)).hexdigest(),
        claim_sequence=1,
        participant_id="participant-synthetic",
        purpose="inspection",
        request_payload=request,
    )


def _handle(runtime, authority, signer):
    return qualified_provider_handle(
        runtime=runtime,
        authority=authority,
        provider_id=PROVIDER,
        provider_instance_id=INSTANCE,
        receipt_signer=signer,
    )


def test_bridge_dispatches_through_canonical_lifecycle_fence_audit(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    request = _instruction()
    acknowledgement = handle.dispatch(request)
    assert transport.calls == [(request.operation, request.request_payload)]
    effect_id = f"provider:{PROVIDER}:{request.effect_id}"
    assert runtime.audit.latest(effect_id).event_type == "COMMITTED"
    assert runtime.fence.read(effect_id).state.value == "COMMITTED"
    assert acknowledgement.effect_id == request.effect_id
    assert acknowledgement.provider_instance_id == INSTANCE
    assert acknowledgement.request_digest == request.request_digest
    Ed25519PublicKey.from_public_bytes(handle.receipt_public_key).verify(
        acknowledgement.receipt_signature,
        b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\x00"
        + canonical_json_bytes(acknowledgement.signed_body()),
    )
    assert acknowledgement.provider_receipt_digest == runtime.fence.read(effect_id).result_digest


def test_replay_cannot_dispatch_canonical_provider_twice(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    instruction = _instruction()
    handle.dispatch(instruction)
    with pytest.raises(Exception):
        handle.dispatch(instruction)
    assert len(transport.calls) == 1


def test_runtime_transport_rebinding_denied_before_effect(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    runtime.provider_execution_transports[PROVIDER] = StubProviderTransport(PROVIDER)
    with pytest.raises(QualifiedBridgeDenied, match="changed"):
        handle.dispatch(_instruction())
    assert not transport.calls


def test_runtime_issuer_rebinding_denied_before_effect(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    runtime.effects._provider_authority_verifiers[PROVIDER] = HmacProviderAuthority(
        "other-issuer", PROVIDER, b"q" * 32
    )
    with pytest.raises(QualifiedBridgeDenied, match="changed"):
        handle.dispatch(_instruction())
    assert not transport.calls


def test_wrong_provider_instance_denied_before_effect(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    with pytest.raises(QualifiedBridgeDenied, match="instance"):
        handle.dispatch(_instruction(provider_instance_id="swapped-instance"))
    assert not transport.calls


def test_request_payload_digest_denied_before_effect(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    instruction = _instruction(payload={"value": 1})
    instruction.request_payload["value"] = 2
    with pytest.raises(QualifiedBridgeDenied, match="changed"):
        handle.dispatch(instruction)
    assert not transport.calls


def test_stale_lifecycle_head_blocks_bridge_before_provider_effect(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    handle = _handle(runtime, authority, signer)
    runtime.lifecycle.memory.admit(
        AdmissionRequest(
            record_id="new-uncheckpointed-memory",
            text="invalidate prior accepted lifecycle state",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op-uncheckpointed",
            project_id="vera-mono",
            governed_identity_id="vera",
        ),
        expected_head=runtime.lifecycle.memory.current_head,
    )
    with pytest.raises(LifecycleActionDenied):
        handle.dispatch(_instruction(effect_id="stale-lifecycle"))
    assert not transport.calls


def test_untrusted_provider_source_cannot_enter_gateway(tmp_path):
    # The canonical runtime refuses to compose an unregistered verifier;
    # therefore the bridge is never constructible in this condition.
    with pytest.raises(OutboundTrustError, match="not registered"):
        _runtime(tmp_path, trusted=False)


def test_bridge_rejects_authority_from_other_provider(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    foreign = HmacProviderAuthority("host-provider-issuer", "other-provider", b"p" * 32)
    with pytest.raises(QualifiedBridgeDenied, match="provider identity"):
        _handle(runtime, foreign, signer)


def test_bridge_rejects_source_mutation_route(tmp_path):
    runtime, authority, transport, signer = _runtime(tmp_path)
    with pytest.raises(QualifiedBridgeDenied, match="source mutation"):
        qualified_provider_handle(
            runtime=runtime, authority=authority, provider_id="source:repo",
            provider_instance_id=INSTANCE, receipt_signer=signer,
        )


def test_coherent_signed_grant_to_host_claim_to_canonical_effect(tmp_path):
    """Actual two-gate source composition, with synthetic witness and keys.

    The host-authorization service must not become a separate ungated provider
    dispatch path. Only the qualified runtime's accepted lifecycle, trust,
    fence, and audit may finally execute this synthetic provider effect.
    """
    runtime, authority, transport, provider_signer = _runtime(tmp_path)
    provider_handle = _handle(runtime, authority, provider_signer)
    issuer_signer = Ed25519PrivateKey.generate()
    now = lambda: 2000
    principal = PrincipalBinding(
        "uid:1001", "model-a", "adapter-a", "runtime-a", "subject-a",
        frozenset({PROVIDER}),
    )
    provider_binding = ProviderBinding(
        PROVIDER, INSTANCE, frozenset({"inspect"}),
    )
    bindings = HostBindingSnapshot(
        "host-a", "issuer-a", 7,
        {principal.peer_key: principal}, {PROVIDER: provider_binding},
    )

    class SyntheticWitness:
        # A synthetic fixture is neither external nor rollback proof.
        def attest_claim(self, *, authority_id, epoch, sequence, grant_id, claim_digest):
            return True

        def attest_revocation(self, *, authority_id, epoch, sequence, grant_id):
            return True

    ledger = ClaimLedger(tmp_path / "authz-claims.sqlite", "host-a", 7, SyntheticWitness())
    verifier = SignedGrantVerifier(
        issuer_signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        ),
        issuer_id="issuer-a", host_id="host-a", epoch=7, trusted_clock=now,
    )
    service = HostAuthorizationService(
        bindings, verifier, ledger, {PROVIDER: provider_handle}, now,
        consent_status=lambda _grant, _now: True,
        provider_status=lambda _provider, _now: True,
    )
    payload = {"record": "synthetic"}
    grant = ApprovedGrant(
        grant_id="grant-canonical", issuer_id="issuer-a", host_id="host-a",
        epoch=7, peer_key="uid:1001", model_id="model-a",
        adapter_id="adapter-a", runtime_id="runtime-a", subject_id="subject-a",
        participant_id="participant-test", purpose="synthetic inspection",
        provider_id=PROVIDER, provider_instance_id=INSTANCE, operation="inspect",
        request_digest=sha256(canonical_json_bytes(payload)).hexdigest(),
        not_before=1900, expires_at=2100,
    )
    canonical = lambda value: json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    signed = canonical({
        "schema": SIGNED_GRANT_SCHEMA,
        "grant": grant.canonical_body(),
        "signature": base64.urlsafe_b64encode(
            issuer_signer.sign(SIGNATURE_CONTEXT + canonical(grant.canonical_body()))
        ).rstrip(b"=").decode("ascii"),
    })
    submit = lambda: service.execute(
        peer_key="uid:1001", signed_grant=signed, provider_id=PROVIDER,
        operation="inspect", request_payload=payload,
    )
    receipt = submit()
    mechanical_effect_id = f"provider:{PROVIDER}:{receipt.effect_id}"
    assert receipt.state == "ACKNOWLEDGED"
    assert ledger.read("grant-canonical").state == "COMPLETED"
    assert len(transport.calls) == 1
    assert runtime.fence.read(mechanical_effect_id).state.value == "COMMITTED"
    assert runtime.audit.latest(mechanical_effect_id).event_type == "COMMITTED"
    with pytest.raises(AuthorizationDenied):
        submit()
    assert len(transport.calls) == 1
