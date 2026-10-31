"""Real localhost mTLS and SQLite tests, NOT physical production qualification."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.grants import ApprovedGrant, SIGNATURE_CONTEXT, SIGNED_GRANT_SCHEMA, SignedGrantVerifier
from vera_core.host_authz.unified_authority import (
    ACK_CONTEXT, REQUEST_SCHEMA, UnifiedHostAuthority, UnifiedAuthorityDenied,
)
from vera_core.host_authz.provider_custody import HostDispatchSigner, ProviderCustodyWorker
from vera_core.host_authz.service import ProviderAcknowledgement
from vera_core.host_authz.unified_service import UnifiedAuthorizationService
from vera_core.host_authz.unified_witness_server import (
    FENCE_ACK_CONTEXT, FENCE_RESPONSE_SCHEMA,
    UnifiedWitnessHTTPServer, UnifiedWitnessLeader, UnifiedWitnessMTLSClient,
    WitnessLeaderConfig, WitnessLeaderDenied,
)


def _pem_key(key):
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())


def _cert(issuer_key, issuer_name, subject_key, subject_name, *, ca=False):
    now = datetime.now(tz=UTC)
    builder = (x509.CertificateBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_name)]))
               .issuer_name(issuer_name)
               .public_key(subject_key.public_key())
               .serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(days=1))
               .not_valid_after(now + timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if not ca:
        builder = builder.add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost")
        ]), critical=False)
    return builder.sign(issuer_key, hashes.SHA256())


def _tls_credentials(tmp_path):
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Only Witness CA")])
    ca = _cert(ca_key, ca_name, ca_key, "Test Only Witness CA", ca=True)
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    leaves = {}
    for name in ("server", "host", "provider", "rogue"):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = _cert(ca_key, ca_name, key, "localhost" if name == "server" else name)
        cert_path = tmp_path / (name + ".crt")
        key_path = tmp_path / (name + ".key")
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(_pem_key(key))
        leaves[name] = (cert_path, key_path, sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest())
    return ca_path, leaves


def _ssl_server_context(ca, leaves):
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(str(leaves["server"][0]), str(leaves["server"][1]))
    context.load_verify_locations(cafile=str(ca))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _ssl_client_context(ca, leaves, who):
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    context.load_cert_chain(str(leaves[who][0]), str(leaves[who][1]))
    context.check_hostname = True
    return context


def _signed(key, grant):
    body = grant.canonical_body()
    sig = key.sign(SIGNATURE_CONTEXT + canonical_json_bytes(body))
    return canonical_json_bytes({"schema": SIGNED_GRANT_SCHEMA, "grant": body,
                                 "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode()})


@contextmanager
def _leader_network(tmp_path, clock=None):
    clock = [100] if clock is None else clock
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    ca, leaves = _tls_credentials(tmp_path)
    issuer_key = ed25519.Ed25519PrivateKey.generate()
    signer = ed25519.Ed25519PrivateKey.generate()
    provider_signer = ed25519.Ed25519PrivateKey.generate()
    pub = issuer_key.public_key().public_bytes_raw()
    p = PrincipalBinding("uid:1234", "model-a", "adapter-a", "runtime-a",
                         "subject-a", frozenset({"provider-a"}))
    bindings = HostBindingSnapshot(
        "host-a", "issuer-a", 4, {p.peer_key: p},
        {"provider-a": ProviderBinding("provider-a", "instance-a", frozenset({"execute"}))},
    )
    verifier = SignedGrantVerifier(pub, issuer_id="issuer-a", host_id="host-a",
                                   epoch=4, trusted_clock=lambda: clock[0])
    config = WitnessLeaderConfig("host-a", "issuer-a", 4, 11,
                                 leaves["host"][2], {"provider-a": leaves["provider"][2]})
    leader = UnifiedWitnessLeader(
        state / "leader.sqlite", config=config, bindings=bindings,
        verifier=verifier, receipt_signer=signer,
        provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
        trusted_clock=lambda: clock[0],
        consent_status=lambda grant, now: True,
    )
    listener = UnifiedWitnessHTTPServer(("127.0.0.1", 0), leader,
                                        _ssl_server_context(ca, leaves))
    thread = threading.Thread(target=listener.serve_forever, daemon=True)
    thread.start()
    port = listener.server_address[1]
    clients = {name: UnifiedWitnessMTLSClient("localhost", port,
                                              _ssl_client_context(ca, leaves, name),
                                              leader_public_key=signer.public_key().public_bytes_raw(),
                                              leader_epoch=11)
               for name in ("host", "provider", "rogue")}
    try:
        yield leader, signer, issuer_key, bindings, verifier, clients, state, provider_signer
    finally:
        listener.shutdown()
        listener.server_close()
        thread.join(3)


def _grant(request=None, *, grant_id="grant-1"):
    request = {"action": "real-fixture"} if request is None else request
    return ApprovedGrant(
        grant_id, "issuer-a", "host-a", 4, "uid:1234", "model-a",
        "adapter-a", "runtime-a", "subject-a", "participant-1", "research",
        "provider-a", "instance-a", "execute",
        sha256(canonical_json_bytes(request)).hexdigest(), 50, 500,
    )


@pytest.mark.skipif(os.name != "posix", reason="provider/host state UID required")
def test_two_cloned_host_authorities_have_only_one_leader_claim(tmp_path):
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier, clients, state, provider_signer):
        grant, request = _grant(), {"action": "real-fixture"}
        envelope = _signed(issuer, grant)
        assert leader.register_grant(envelope) == grant.grant_id
        kw = dict(bindings=bindings, grant_verifier=verifier, witness=clients["host"],
                  witness_public_key=signer.public_key().public_bytes_raw(),
                  leader_epoch=11, provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
                  trusted_clock=lambda: 100, consent_status=lambda g, now: True)
        a = UnifiedHostAuthority(state / "host-a.sqlite", **kw)
        b = UnifiedHostAuthority(state / "host-b.sqlite", **kw)
        claimed = a.claim(envelope, "uid:1234", request)
        assert claimed.claim_sequence == 1
        with pytest.raises((UnifiedAuthorityDenied, WitnessLeaderDenied)):
            b.claim(envelope, "uid:1234", request)
        assert a.read(grant.grant_id).state == "CLAIMED"
        assert b.read(grant.grant_id) is None
        start = a.start(grant.grant_id)
        assert start.sequence == 2
        assert start.event
        assert leader.reserve_provider_effect(
            host_id="host-a", epoch=4, provider_id="provider-a", provider_instance_id="instance-a",
            effect_id=claimed.effect_id, claim_sequence=claimed.claim_sequence,
            request_digest=grant.request_digest, grant_id=grant.grant_id,
            participant_id=grant.participant_id, purpose=grant.purpose, operation=grant.operation,
        ) is True
        with pytest.raises(WitnessLeaderDenied):
            leader.reserve_provider_effect(
                host_id="host-a", epoch=4, provider_id="provider-a", provider_instance_id="instance-a",
                effect_id=claimed.effect_id, claim_sequence=claimed.claim_sequence,
                request_digest=grant.request_digest, grant_id=grant.grant_id,
                participant_id=grant.participant_id, purpose=grant.purpose, operation=grant.operation,
            )


@pytest.mark.skipif(os.name != "posix", reason="leader host state ownership required")
def test_two_mtls_roles_cannot_swap_authority_and_provider_effect(tmp_path):
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier, clients, state, provider_signer):
        request = {"action": "real-fixture"}
        grant = _grant(request)
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        authority = UnifiedHostAuthority(
            state / "host.sqlite", bindings=bindings, grant_verifier=verifier,
            witness=clients["host"], witness_public_key=signer.public_key().public_bytes_raw(),
            leader_epoch=11, provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
            trusted_clock=lambda: 100, consent_status=lambda g, now: True,
        )
        claim = authority.claim(envelope, "uid:1234", request)
        start = authority.start(grant.grant_id)
        kwargs = dict(host_id="host-a", epoch=4, provider_id="provider-a",
                      provider_instance_id="instance-a", effect_id=claim.effect_id,
                      claim_sequence=claim.claim_sequence, request_digest=grant.request_digest,
                      grant_id=grant.grant_id, participant_id=grant.participant_id,
                      purpose=grant.purpose, operation=grant.operation)
        # The provider cert can reserve a physical effect; the host cert cannot.
        with pytest.raises(WitnessLeaderDenied):
            clients["host"].reserve_provider_effect(**kwargs)
        with pytest.raises(WitnessLeaderDenied):
            clients["provider"].allocate_event(canonical_json_bytes({"garbage": True}))
        with pytest.raises(WitnessLeaderDenied):
            clients["rogue"].reserve_provider_effect(**kwargs)
        assert clients["provider"].reserve_provider_effect(**kwargs) is True
        with pytest.raises(WitnessLeaderDenied):
            clients["provider"].reserve_provider_effect(**kwargs)


@pytest.mark.skipif(os.name != "posix", reason="leader host state ownership required")
def test_leader_does_not_accept_unsigned_or_wrong_host_grant_registration(tmp_path):
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier, clients, state, provider_signer):
        grant = _grant()
        with pytest.raises(Exception):
            leader.register_grant(b"{}")
        with pytest.raises(Exception):
            leader.register_grant(_signed(ed25519.Ed25519PrivateKey.generate(), grant))
        altered = _grant(grant_id="grant-2")
        altered = ApprovedGrant(**{**altered.canonical_body(), "peer_key": "uid:999"})
        with pytest.raises((WitnessLeaderDenied, ValueError)):
            leader.register_grant(_signed(issuer, altered))
        assert leader.register_grant(_signed(issuer, grant)) == grant.grant_id
        with pytest.raises(WitnessLeaderDenied):
            leader.register_grant(_signed(issuer, grant))


@pytest.mark.skipif(os.name != "posix", reason="leader host state ownership required")
def test_leader_restart_preserves_monotonic_state_and_rejects_key_epoch_change(tmp_path):
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier, clients, state, provider_signer):
        grant = _grant()
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        restarted = UnifiedWitnessLeader(
            state / "leader.sqlite", config=leader.config, bindings=bindings,
            verifier=verifier, receipt_signer=signer,
            provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
            trusted_clock=lambda: 100,
            consent_status=lambda grant, now: True,
        )
        assert restarted.register_grant  # exact typed service reconstructed from persisted rows
        with pytest.raises(WitnessLeaderDenied):
            UnifiedWitnessLeader(
                state / "leader.sqlite", config=leader.config, bindings=bindings,
                verifier=verifier, receipt_signer=ed25519.Ed25519PrivateKey.generate(),
                provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
                trusted_clock=lambda: 100, consent_status=lambda grant, now: True,
            )
        wrong_epoch = WitnessLeaderConfig("host-a", "issuer-a", 4, 12,
                                          leader.config.host_client_sha256,
                                          dict(leader.config.provider_client_sha256))
        with pytest.raises(WitnessLeaderDenied):
            UnifiedWitnessLeader(
                state / "leader.sqlite", config=wrong_epoch, bindings=bindings,
                verifier=verifier, receipt_signer=signer,
                provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
                trusted_clock=lambda: 100,
                consent_status=lambda grant, now: True,
            )
        wrong_host_cert = WitnessLeaderConfig("host-a", "issuer-a", 4, 11,
            "b" * 64, dict(leader.config.provider_client_sha256))
        with pytest.raises(WitnessLeaderDenied):
            UnifiedWitnessLeader(
                state / "leader.sqlite", config=wrong_host_cert, bindings=bindings,
                verifier=verifier, receipt_signer=signer,
                provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
                trusted_clock=lambda: 100,
                consent_status=lambda grant, now: True,
            )
        with pytest.raises(WitnessLeaderDenied):
            UnifiedWitnessLeader(
                state / "leader.sqlite", config=leader.config, bindings=bindings,
                verifier=verifier, receipt_signer=signer,
                provider_public_keys={"provider-a": ed25519.Ed25519PrivateKey.generate().public_key().public_bytes_raw()},
                trusted_clock=lambda: 100,
                consent_status=lambda grant, now: True,
            )


@pytest.mark.skipif(os.name != "posix", reason="leader and provider durable state ownership required")
def test_one_leader_proves_complete_with_provider_ack_and_blocks_cloned_service(tmp_path):
    with _leader_network(tmp_path) as (leader, witness_signer, issuer, bindings,
                                       verifier, clients, state, provider_signer):
        grant, request = _grant(), {"action": "real-fixture"}
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        worker_calls = []
        host_command_key = ed25519.Ed25519PrivateKey.generate()
        command_signer = HostDispatchSigner(host_command_key, host_id="host-a", epoch=4,
                                             trusted_clock=lambda: 100)
        worker = ProviderCustodyWorker(
            state_path=state / "physical-provider.sqlite", provider_id="provider-a",
            provider_instance_id="instance-a", host_id="host-a", epoch=4,
            host_command_public_key=command_signer.public_key_bytes,
            receipt_signer=provider_signer,
            witness_start_public_key=witness_signer.public_key().public_bytes_raw(),
            witness_leader_epoch=11, effect_witness=clients["provider"],
            execute=lambda command: (worker_calls.append(command.effect_id) or {"effect": "committed"}),
            trusted_clock=lambda: 100,
        )
        options = dict(bindings=bindings, grant_verifier=verifier,
                       witness=clients["host"],
                       witness_public_key=witness_signer.public_key().public_bytes_raw(),
                       leader_epoch=11,
                       provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
                       trusted_clock=lambda: 100, consent_status=lambda g, now: True)
        host_a = UnifiedHostAuthority(state / "host-one.sqlite", **options)
        host_b = UnifiedHostAuthority(state / "host-copy.sqlite", **options)
        service_a = UnifiedAuthorizationService(
            authority=host_a, host_command_signer=command_signer,
            provider_workers={"provider-a": worker},
            unqualified_in_process_fixture=True)
        service_b = UnifiedAuthorizationService(
            authority=host_b, host_command_signer=command_signer,
            provider_workers={"provider-a": worker},
            unqualified_in_process_fixture=True)
        receipt = service_a.execute(
            peer_key="uid:1234", signed_grant=envelope, provider_id="provider-a",
            operation="execute", request_payload=request)
        assert receipt.state == "ACKNOWLEDGED"
        assert host_a.read(grant.grant_id).state == "COMPLETED"
        assert len(worker_calls) == 1
        assert worker.status(receipt.effect_id) == "COMMITTED"
        with pytest.raises((UnifiedAuthorityDenied, WitnessLeaderDenied)):
            service_b.execute(peer_key="uid:1234", signed_grant=envelope,
                              provider_id="provider-a", operation="execute",
                              request_payload=request)
        assert len(worker_calls) == 1
        assert host_b.read(grant.grant_id) is None
        with pytest.raises(Exception):
            service_a.execute(peer_key="uid:1234", signed_grant=envelope,
                              provider_id="provider-a", operation="execute",
                              request_payload=request)


@pytest.mark.skipif(os.name != "posix", reason="leader host state ownership required")
def test_independent_leader_rejects_forged_provider_complete_signature(tmp_path):
    with _leader_network(tmp_path) as (leader, witness_signer, issuer, bindings,
                                       verifier, clients, state, provider_signer):
        request, grant = {"action": "real-fixture"}, _grant()
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        authority = UnifiedHostAuthority(
            state / "host.sqlite", bindings=bindings, grant_verifier=verifier,
            witness=clients["host"], witness_public_key=witness_signer.public_key().public_bytes_raw(),
            leader_epoch=11,
            provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
            trusted_clock=lambda: 100, consent_status=lambda g, now: True,
        )
        claim = authority.claim(envelope, "uid:1234", request)
        start = authority.start(grant.grant_id)
        assert clients["provider"].reserve_provider_effect(
            host_id="host-a", epoch=4, provider_id="provider-a", provider_instance_id="instance-a",
            effect_id=claim.effect_id, claim_sequence=claim.claim_sequence,
            request_digest=grant.request_digest, grant_id=grant.grant_id,
            participant_id=grant.participant_id, purpose=grant.purpose, operation=grant.operation)
        receipt_digest = sha256(canonical_json_bytes({"committed": True})).hexdigest()
        ack_body = {
            "schema": "HOST_AUTHZ_PROVIDER_ACK_V1", "effect_id": claim.effect_id,
            "provider_id": "provider-a", "provider_instance_id": "instance-a",
            "claim_sequence": claim.claim_sequence, "request_digest": grant.request_digest,
            "provider_receipt_digest": receipt_digest,
        }
        forged = ed25519.Ed25519PrivateKey.generate().sign(ACK_CONTEXT + canonical_json_bytes(ack_body))
        bad_event = {"kind": "COMPLETE", "grant_id": grant.grant_id,
                     "effect_id": claim.effect_id, "start_sequence": start.sequence,
                     "receipt_digest": receipt_digest, "provider_ack_body": ack_body,
                     "provider_ack_signature": base64.urlsafe_b64encode(forged).rstrip(b"=").decode()}
        bad_request = {
            "schema": REQUEST_SCHEMA, "host_id": "host-a", "issuer_id": "issuer-a",
            "epoch": 4, "leader_epoch": 11, "challenge": secrets.token_hex(24),
            "kind": "COMPLETE", "event_digest": sha256(canonical_json_bytes(bad_event)).hexdigest(),
            "event": bad_event,
        }
        with pytest.raises(WitnessLeaderDenied):
            leader.allocate_event(canonical_json_bytes(bad_request))
        genuine_signature = provider_signer.sign(ACK_CONTEXT + canonical_json_bytes(ack_body))
        ack = ProviderAcknowledgement(
            claim.effect_id, "provider-a", "instance-a", claim.claim_sequence,
            grant.request_digest, receipt_digest, genuine_signature)
        completed = authority.complete(grant.grant_id, ack)
        assert completed.state == "COMPLETED"


@pytest.mark.skipif(os.name != "posix", reason="leader and cloned host DB ownership required")
def test_leader_revocation_denies_start_even_with_older_cloned_host_claim(tmp_path):
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier,
                                       clients, state, provider_signer):
        grant, request = _grant(), {"action": "real-fixture"}
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        options = dict(bindings=bindings, grant_verifier=verifier,
                       witness=clients["host"],
                       witness_public_key=signer.public_key().public_bytes_raw(),
                       leader_epoch=11,
                       provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
                       trusted_clock=lambda: 100, consent_status=lambda g, now: True)
        origin_path = state / "origin.sqlite"
        origin = UnifiedHostAuthority(origin_path, **options)
        claim = origin.claim(envelope, "uid:1234", request)
        copy_path = state / "cloned-before-revoke.sqlite"
        shutil.copy2(origin_path, copy_path)
        clone = UnifiedHostAuthority(copy_path, **options)
        assert clone.read(grant.grant_id).claim_sequence == claim.claim_sequence
        revoked = origin.revoke_scope(grant)
        assert revoked.sequence == 2
        with pytest.raises((WitnessLeaderDenied, UnifiedAuthorityDenied)):
            clone.start(grant.grant_id)
        assert clone.read(grant.grant_id).state == "CLAIMED"


@pytest.mark.skipif(os.name != "posix", reason="leader state ownership required")
def test_cloning_leader_database_and_signing_key_still_creates_split_brain(tmp_path):
    """EXPECTED ATTACK SUCCESS: source code cannot make an exportable key exclusive.

    This is a deliberately red qualification case: if a deployment allows a
    second copy of BOTH leader state and signing key, each clone can approve
    the same effect with the same sequence. Never mark physical qualification
    PASS from the other source-level tests.
    """
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier,
                                       clients, state, provider_signer):
        grant = _grant()
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        clone_path = state / "cloned-leader.sqlite"
        shutil.copy2(state / "leader.sqlite", clone_path)
        clone = UnifiedWitnessLeader(
            clone_path, config=leader.config, bindings=bindings, verifier=verifier,
            receipt_signer=signer,
            provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
            trusted_clock=lambda: 100, consent_status=lambda g, now: True,
        )
        scope_fields = ("participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
                        "subject_id", "host_id", "provider_id", "provider_instance_id")
        scope = sha256(canonical_json_bytes({k: getattr(grant, k) for k in scope_fields})).hexdigest()
        effect = sha256(canonical_json_bytes({
            "schema": "HOST_AUTHZ_UNIFIED_EFFECT_V1", "grant_id": grant.grant_id,
            "issuer_id": grant.issuer_id, "host_id": grant.host_id,
            "epoch": grant.epoch, "provider_instance_id": grant.provider_instance_id,
            "request_digest": grant.request_digest})).hexdigest()
        event = {"kind": "CLAIM", "grant_id": grant.grant_id,
                 "effect_id": effect, "scope_digest": scope,
                 "provider_instance_id": grant.provider_instance_id,
                 "request_digest": grant.request_digest}
        def wire(challenge):
            return canonical_json_bytes({"schema": REQUEST_SCHEMA, "host_id": "host-a",
                                         "issuer_id": "issuer-a", "epoch": 4,
                                         "leader_epoch": 11, "challenge": challenge,
                                         "kind": "CLAIM", "event": event,
                                         "event_digest": sha256(canonical_json_bytes(event)).hexdigest()})
        response_a = json.loads(leader.allocate_event(wire(secrets.token_hex(24))))
        response_b = json.loads(clone.allocate_event(wire(secrets.token_hex(24))))
        assert response_a["body"]["sequence"] == response_b["body"]["sequence"] == 1
        assert response_a["body"]["approved"] is response_b["body"]["approved"] is True


@pytest.mark.skipif(os.name != "posix", reason="host witness state ownership required")
def test_leader_denies_physical_reservation_past_signed_start_deadline(tmp_path):
    clock = [100]
    with _leader_network(tmp_path, clock) as (leader, signer, issuer, bindings,
                                               verifier, clients, state, provider_signer):
        grant, request = _grant(), {"action": "real-fixture"}
        envelope = _signed(issuer, grant)
        leader.register_grant(envelope)
        authority = UnifiedHostAuthority(
            state / "host.sqlite", bindings=bindings, grant_verifier=verifier,
            witness=clients["host"], witness_public_key=signer.public_key().public_bytes_raw(),
            leader_epoch=11,
            provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
            trusted_clock=lambda: clock[0], consent_status=lambda g, now: True)
        claim = authority.claim(envelope, "uid:1234", request)
        start = authority.start(grant.grant_id)
        assert json.loads(start.event)["start_deadline"] == 130
        clock[0] = 131
        with pytest.raises(WitnessLeaderDenied):
            clients["provider"].reserve_provider_effect(
                host_id="host-a", epoch=4, provider_id="provider-a",
                provider_instance_id="instance-a", effect_id=claim.effect_id,
                claim_sequence=claim.claim_sequence, request_digest=grant.request_digest,
                grant_id=grant.grant_id, participant_id=grant.participant_id,
                purpose=grant.purpose, operation=grant.operation)


@pytest.mark.parametrize("rogue_signs", [False, True])
def test_provider_fence_refuses_unsigned_or_wrong_leader_ack(monkeypatch, rogue_signs):
    """A CA-trusted but non-leader endpoint cannot authorize an effect."""
    pinned = ed25519.Ed25519PrivateKey.generate()
    rogue = ed25519.Ed25519PrivateKey.generate()
    client = UnifiedWitnessMTLSClient(
        "localhost", 443, ssl.create_default_context(),
        leader_public_key=pinned.public_key().public_bytes_raw(), leader_epoch=11,
    )
    fields = {
        "host_id": "host-a", "epoch": 4, "provider_id": "provider-a",
        "provider_instance_id": "instance-a", "effect_id": "effect-a",
        "claim_sequence": 9, "request_digest": "f" * 64,
        "grant_id": "grant-a", "participant_id": "participant-a",
        "purpose": "research", "operation": "execute",
    }

    def counterfeit(_client, endpoint, request):
        assert endpoint == "/v1/reserve-effect"
        if not rogue_signs:
            return canonical_json_bytes({
                "schema": FENCE_RESPONSE_SCHEMA, "approved": True,
                "effect_id": fields["effect_id"],
            })
        challenge = json.loads(request)["challenge"]
        body = {
            "schema": FENCE_RESPONSE_SCHEMA, "approved": True,
            "host_id": fields["host_id"], "epoch": fields["epoch"],
            "leader_epoch": 11, "provider_id": fields["provider_id"],
            "provider_instance_id": fields["provider_instance_id"],
            "grant_id": fields["grant_id"], "effect_id": fields["effect_id"],
            "challenge": challenge, "fence_request_digest": sha256(request).hexdigest(),
        }
        sig = rogue.sign(FENCE_ACK_CONTEXT + canonical_json_bytes(body))
        return canonical_json_bytes({
            "schema": FENCE_RESPONSE_SCHEMA, "body": body,
            "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode(),
        })

    monkeypatch.setattr(UnifiedWitnessMTLSClient, "_post", counterfeit)
    with pytest.raises(WitnessLeaderDenied):
        client.reserve_provider_effect(**fields)
