"""Synthetic end-to-end Linux IPC acceptance; NOT production authority proof.

This test exercises the actual Unix peer-credential path and the coherent
service, rather than directly calling `execute` with a caller-chosen peer.
It cannot establish separate host UIDs or real issuer/provider key custody.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.grants import ApprovedGrant, SIGNATURE_CONTEXT, SIGNED_GRANT_SCHEMA, SignedGrantVerifier
from vera_core.host_authz.ipc import UnixAuthorityServer
from vera_core.host_authz.ledger import ClaimLedger
from vera_core.host_authz.service import HostAuthorizationService, HostProviderHandle, ProviderAcknowledgement


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="requires Linux SO_PEERCRED")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class SyntheticWitness:
    """A synthetic fixture, not an external monotonic authority."""

    def __init__(self):
        self.last_sequence = 0
        self.lock = threading.Lock()

    def _advance(self, sequence):
        with self.lock:
            if sequence != self.last_sequence + 1:
                return False
            self.last_sequence = sequence
            return True

    def attest_claim(self, *, authority_id, epoch, sequence, grant_id, claim_digest):
        return self._advance(sequence)

    def attest_revocation(self, *, authority_id, epoch, sequence, grant_id):
        return self._advance(sequence)


def make_host(tmp_path: Path, *, consent=True, provider_live=True):
    issuer_signing = Ed25519PrivateKey.generate()
    provider_signing = Ed25519PrivateKey.generate()
    clock = lambda: 2000
    a_uid = os.getuid()
    b_uid = a_uid + 10001
    a = PrincipalBinding(f"uid:{a_uid}", "model-a", "adapter-a", "runtime-a", "subject-a", frozenset({"test-provider"}))
    b = PrincipalBinding(f"uid:{b_uid}", "model-b", "adapter-b", "runtime-b", "subject-b", frozenset({"test-provider"}))
    provider = ProviderBinding("test-provider", "instance-a", frozenset({"inspect"}))
    bindings = HostBindingSnapshot("test-host", "test-issuer", 5, {a.peer_key: a, b.peer_key: b}, {provider.provider_id: provider})
    issuer_public = issuer_signing.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    provider_public = provider_signing.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    verifier = SignedGrantVerifier(issuer_public, issuer_id="test-issuer", host_id="test-host", epoch=5, trusted_clock=clock)
    witness = SyntheticWitness()
    ledger_path = tmp_path / "claims.sqlite"
    calls = []

    def acknowledged(instruction):
        calls.append(instruction)
        unsigned = ProviderAcknowledgement(
            effect_id=instruction.effect_id,
            provider_id=instruction.provider_id,
            provider_instance_id=instruction.provider_instance_id,
            claim_sequence=instruction.claim_sequence,
            request_digest=instruction.request_digest,
            provider_receipt_digest="d" * 64,
            receipt_signature=b"",
        )
        return replace(unsigned, receipt_signature=provider_signing.sign(
            b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\x00" + canonical_json_bytes(unsigned.signed_body())
        ))

    providers = {"test-provider": HostProviderHandle("test-provider", "instance-a", provider_public, acknowledged)}

    def build_service():
        ledger = ClaimLedger(ledger_path, "test-host", 5, witness)
        return HostAuthorizationService(
            bindings, verifier, ledger, providers, clock,
            consent_status=(lambda _grant, _now: consent) if consent is not None else None,
            provider_status=(lambda _binding, _now: provider_live) if provider_live is not None else None,
        ), ledger

    return locals()


def sign(ctx, *, model="a", grant_id="grant-1", payload=None):
    payload = {"record": "synthetic"} if payload is None else payload
    principal = ctx[model]
    grant = ApprovedGrant(
        grant_id=grant_id,
        issuer_id="test-issuer", host_id="test-host", epoch=5,
        peer_key=principal.peer_key,
        model_id=principal.model_id, adapter_id=principal.adapter_id,
        runtime_id=principal.runtime_id, subject_id=principal.subject_id,
        participant_id="participant-synthetic", purpose="synthetic authorized inspection",
        provider_id="test-provider", provider_instance_id="instance-a", operation="inspect",
        request_digest=sha256(canonical_json_bytes(payload)).hexdigest(),
        not_before=1900, expires_at=2100,
    )
    signed = ctx["issuer_signing"].sign(SIGNATURE_CONTEXT + canonical(grant.canonical_body()))
    return canonical({
        "schema": SIGNED_GRANT_SCHEMA, "grant": grant.canonical_body(),
        "signature": base64.urlsafe_b64encode(signed).rstrip(b"=").decode(),
    })


def exchange(tmp_path, service, signed_grant, *, payload=None):
    payload = {"record": "synthetic"} if payload is None else payload
    tmp_path.chmod(0o700)
    endpoint = tmp_path / "authz.sock"
    server = UnixAuthorityServer(endpoint, service)
    ready = threading.Event()
    worker = threading.Thread(target=server.serve_once, kwargs={"ready": ready})
    worker.start()
    try:
        assert ready.wait(timeout=3), "authority socket did not start"
        wire = canonical({
            "signed_grant_b64": base64.b64encode(signed_grant).decode(),
            "provider_id": "test-provider", "operation": "inspect", "request_payload": payload,
        }) + b"\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(endpoint))
            connection.sendall(wire)
            with connection.makefile("rb") as response:
                body = json.loads(response.readline())
        return body
    finally:
        worker.join(timeout=4)
        assert not worker.is_alive(), "authority server thread leaked"


def test_actual_unix_peer_signed_grant_dispatch_ack_then_replay_and_restart(tmp_path):
    ctx = make_host(tmp_path)
    service, ledger = ctx["build_service"]()
    ticket = sign(ctx)

    first = exchange(tmp_path, service, ticket)
    assert first["ok"] is True
    assert first["receipt"]["state"] == "ACKNOWLEDGED"
    assert first["receipt"]["claim_sequence"] == 1
    assert len(ctx["calls"]) == 1
    assert ledger.read("grant-1").state == "COMPLETED"

    assert exchange(tmp_path, service, ticket) == {"ok": False, "error": "denied"}
    restarted, restarted_ledger = ctx["build_service"]()
    assert exchange(tmp_path, restarted, ticket) == {"ok": False, "error": "denied"}
    assert restarted_ledger.read("grant-1").state == "COMPLETED"
    assert len(ctx["calls"]) == 1


def test_other_model_valid_signed_grant_cannot_override_kernel_peer(tmp_path):
    ctx = make_host(tmp_path)
    service, ledger = ctx["build_service"]()
    other_ticket = sign(ctx, model="b", grant_id="model-b-grant")
    assert exchange(tmp_path, service, other_ticket) == {"ok": False, "error": "denied"}
    assert ledger.read("model-b-grant") is None
    assert not ctx["calls"]


@pytest.mark.parametrize("flags", [(None, True), (False, True), (True, None), (True, False)])
def test_missing_or_negative_host_consent_or_provider_status_denies(tmp_path, flags):
    consent, provider_live = flags
    ctx = make_host(tmp_path, consent=consent, provider_live=provider_live)
    service, ledger = ctx["build_service"]()
    assert exchange(tmp_path, service, sign(ctx)) == {"ok": False, "error": "denied"}
    assert ledger.read("grant-1") is None
    assert not ctx["calls"]
