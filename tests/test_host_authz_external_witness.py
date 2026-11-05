"""Out-of-domain witness protocol and local-test authority; not trust qualification."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sqlite3
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest

from vera_core.host_authz.external_witness import (
    ExternalWitnessClient,
    ExternalWitnessDenied,
    HTTPSWitnessTransport,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    RESPONSE_SIGNATURE_CONTEXT,
)
from vera_core.host_authz.ledger import ClaimDenied, ClaimLedger


DIGEST = "a" * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


class SyntheticExternalAuthority:
    """Separate DB is a test seam, not trusted hardware or quorum."""

    def __init__(self, path, signer, *, witness_id="witness-1", leader_id="leader-1", leader_epoch=7):
        self.path = path
        self.signer = signer
        self.witness_id = witness_id
        self.leader_id = leader_id
        self.leader_epoch = leader_epoch
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS events(authority TEXT, seq INTEGER, grant_id TEXT, kind TEXT, PRIMARY KEY(authority,seq), UNIQUE(authority,grant_id,kind))")

    def send(self, event_bytes):
        event = json.loads(event_bytes)
        assert event["schema"] == REQUEST_SCHEMA
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT MAX(seq) FROM events WHERE authority=?", (event["authority_id"],)).fetchone()[0] or 0
            prior_claim = db.execute("SELECT 1 FROM events WHERE authority=? AND grant_id=? AND kind='CLAIM'", (event["authority_id"], event["grant_id"])).fetchone()
            prior_revoke = db.execute("SELECT 1 FROM events WHERE authority=? AND grant_id=? AND kind='REVOKE'", (event["authority_id"], event["grant_id"])).fetchone()
            approved = (
                event["witness_id"] == self.witness_id
                and event["leader_epoch"] == self.leader_epoch
                and event["sequence"] == last + 1
                and prior_revoke is None
                and (event["kind"] == "REVOKE" or prior_claim is None)
            )
            if approved:
                db.execute("INSERT INTO events VALUES(?,?,?,?)", (event["authority_id"], event["sequence"], event["grant_id"], event["kind"]))
                db.commit()
        body = {
            "schema": RESPONSE_SCHEMA,
            "witness_id": self.witness_id,
            "leader_id": self.leader_id,
            "leader_epoch": self.leader_epoch,
            "authority_id": event["authority_id"],
            "epoch": event["epoch"],
            "sequence": event["sequence"],
            "nonce": event["nonce"],
            "event_digest": sha256(event_bytes).hexdigest(),
            "decision": "APPROVED" if approved else "DENIED",
        }
        sig = self.signer.sign(RESPONSE_SIGNATURE_CONTEXT + canonical(body))
        return canonical({"body": body, "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode()})


def make(tmp_path):
    key = Ed25519PrivateKey.generate()
    authority = SyntheticExternalAuthority(tmp_path / "external.sqlite", key)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    client = ExternalWitnessClient(authority, witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    return client, authority, key, pub


def claim(client, *, seq=1, grant="grant-1", digest=DIGEST):
    return client.attest_claim(authority_id="host-A", epoch=3, sequence=seq, grant_id=grant, claim_digest=digest)


def test_external_protocol_approves_one_claim_then_denies_duplicate(tmp_path):
    client, _, _, _ = make(tmp_path)
    assert claim(client) is True
    assert claim(client) is False


def test_live_external_witness_separates_cloned_local_ledgers(tmp_path):
    client, _, _, _ = make(tmp_path)
    a = ClaimLedger(tmp_path / "client-a.sqlite", "host-A", 3, client)
    b = ClaimLedger(tmp_path / "client-b.sqlite", "host-A", 3, client)
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert a.claim("grant-1", DIGEST, now).state == "RESERVED"
    with pytest.raises(ClaimDenied):
        b.claim("grant-1", DIGEST, now)
    assert b.read("grant-1") is None


def test_remote_linearization_one_of_32_simultaneous_claimants(tmp_path):
    client, _, _, _ = make(tmp_path)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: claim(client), range(32)))
    assert results.count(True) == 1
    assert results.count(False) == 31


def test_witness_revocation_consumes_global_sequence(tmp_path):
    client, _, _, _ = make(tmp_path)
    assert client.attest_revocation(authority_id="host-A", epoch=3, sequence=1, grant_id="grant-1") is True
    assert claim(client, grant="grant-1", seq=2) is False
    assert claim(client, grant="grant-2", seq=2) is True


def test_claim_can_be_revoked_and_further_claim_replayed_denied(tmp_path):
    client, _, _, _ = make(tmp_path)
    assert claim(client) is True
    assert client.attest_revocation(authority_id="host-A", epoch=3, sequence=2, grant_id="grant-1") is True
    assert claim(client, seq=3) is False


def test_claim_ledger_uses_same_external_witness_for_claim_and_revocation(tmp_path):
    client, _, _, _ = make(tmp_path)
    ledger = ClaimLedger(tmp_path / "claims.sqlite", "host-A", 3, client)
    now = datetime(2026, 10, 30, tzinfo=timezone.utc)
    assert ledger.claim("grant-1", DIGEST, now).state == "RESERVED"
    revoked = ledger.revoke("grant-1")
    assert revoked.revoked is True
    with pytest.raises(ClaimDenied):
        ledger.claim("grant-1", DIGEST, now)


def test_claim_after_external_timeout_or_partition_fails_closed(tmp_path):
    client, authority, key, pub = make(tmp_path)
    class Lost:
        def send(self, _request):
            raise TimeoutError("partition")
    offline = ExternalWitnessClient(Lost(), witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    with pytest.raises(ExternalWitnessDenied):
        claim(offline)


def test_response_lost_after_remote_commit_never_retries_as_new_approval(tmp_path):
    _, authority, _, pub = make(tmp_path)
    class CommitThenDrop:
        def send(self, event):
            authority.send(event)
            raise TimeoutError("response lost after durable witness commit")
    lost = ExternalWitnessClient(CommitThenDrop(), witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    with pytest.raises(ExternalWitnessDenied):
        claim(lost)
    recovered = ExternalWitnessClient(authority, witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    assert claim(recovered) is False


def test_signed_response_replay_and_wrong_nonce_denied(tmp_path):
    client, authority, key, pub = make(tmp_path)
    captured = []
    class Replay:
        def send(self, request):
            if not captured:
                captured.append(authority.send(request))
            return captured[0]
    c = ExternalWitnessClient(Replay(), witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    assert claim(c) is True
    with pytest.raises(ExternalWitnessDenied):
        claim(c, grant="grant-2", seq=2)


def test_wrong_key_leader_or_epoch_denied(tmp_path):
    _, authority, key, pub = make(tmp_path)
    badkey = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    with pytest.raises(ExternalWitnessDenied):
        claim(ExternalWitnessClient(authority, witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=badkey))
    with pytest.raises(ExternalWitnessDenied):
        claim(ExternalWitnessClient(authority, witness_id="witness-1", leader_id="leader-changed", leader_epoch=7, response_public_key=pub))
    with pytest.raises(ExternalWitnessDenied):
        claim(ExternalWitnessClient(authority, witness_id="witness-1", leader_id="leader-1", leader_epoch=8, response_public_key=pub))


def test_client_trust_binding_cannot_be_reassigned_even_using_object_setattr(tmp_path):
    client, _, _, _ = make(tmp_path)
    with pytest.raises((AttributeError, TypeError)):
        client._public_key = Ed25519PrivateKey.generate().public_key()
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(client, "_leader_epoch", 999)
    assert claim(client) is True


def test_mutated_signed_response_and_duplicate_json_denied(tmp_path):
    _, authority, key, pub = make(tmp_path)
    class Mutated:
        def send(self, request):
            blob = authority.send(request)
            return blob.replace(b'"APPROVED"', b'"DENIED"')
    with pytest.raises(ExternalWitnessDenied):
        claim(ExternalWitnessClient(Mutated(), witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub))
    class Duplicate:
        def send(self, request):
            blob = authority.send(request)
            return blob[:-1] + b',"signature":"other"}'
    with pytest.raises(ExternalWitnessDenied):
        claim(ExternalWitnessClient(Duplicate(), witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub))


def test_wrong_request_scope_or_invalid_fields_denied_before_transport(tmp_path):
    client, _, _, _ = make(tmp_path)
    for kwargs in ({"epoch": True}, {"sequence": 0}, {"grant_id": ""}, {"claim_digest": "GG"}):
        values = {"authority_id": "host-A", "epoch": 3, "sequence": 1, "grant_id": "grant-1", "claim_digest": DIGEST}
        values.update(kwargs)
        with pytest.raises(ExternalWitnessDenied):
            client.attest_claim(**values)


def test_insecure_https_transport_configuration_rejected(tmp_path):
    tls = ssl.create_default_context()
    transport = HTTPSWitnessTransport("https://witness.example/api", tls)
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(transport, "_url", "https://attacker.example/api")
    assert transport._url == "https://witness.example/api"
    with pytest.raises(ValueError):
        HTTPSWitnessTransport("http://witness.example/api", tls)
    with pytest.raises(ValueError):
        HTTPSWitnessTransport("https://user:password@witness.example/api", tls)
    tls.check_hostname = False
    with pytest.raises(ValueError):
        HTTPSWitnessTransport("https://witness.example/api", tls)


def test_real_local_mtls_https_witness_roundtrip(tmp_path):
    """Real TLS transport; issuer, credentials and server state are TEST-only."""
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Witness CA")])
    now = datetime.now(timezone.utc)

    def cert(key, name, *, ca=False, server=False):
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca_name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        )
        if server:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
            )
        if not ca:
            purpose = ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
            builder = builder.add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
        return builder.sign(ca_key, hashes.SHA256())

    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = ec.generate_private_key(ec.SECP256R1())
    client_key = ec.generate_private_key(ec.SECP256R1())

    def write_cert(name, value):
        path = tmp_path / name
        path.write_bytes(value.public_bytes(serialization.Encoding.PEM))
        return path

    def write_key(name, key):
        path = tmp_path / name
        path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        path.chmod(0o600)
        return path

    cafile = write_cert("ca.pem", ca_cert)
    serverfile = write_cert("server.pem", cert(server_key, "localhost", server=True))
    serverkey = write_key("server-key.pem", server_key)
    clientfile = write_cert("client.pem", cert(client_key, "test-model-host-client"))
    clientkey = write_key("client-key.pem", client_key)
    _, authority, _, pub = make(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            response = authority.send(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args):
            pass

    listener = HTTPServer(("127.0.0.1", 0), Handler)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.verify_mode = ssl.CERT_REQUIRED
    server_tls.load_cert_chain(str(serverfile), str(serverkey))
    server_tls.load_verify_locations(cafile=str(cafile))
    listener.socket = server_tls.wrap_socket(listener.socket, server_side=True)
    worker = threading.Thread(target=listener.serve_forever, daemon=True)
    worker.start()
    try:
        client_tls = ssl.create_default_context(cafile=str(cafile))
        client_tls.load_cert_chain(str(clientfile), str(clientkey))
        transport = HTTPSWitnessTransport(
            f"https://localhost:{listener.server_port}/attest", client_tls,
            timeout_seconds=2.0,
        )
        client = ExternalWitnessClient(
            transport, witness_id="witness-1", leader_id="leader-1",
            leader_epoch=7, response_public_key=pub,
        )
        assert claim(client) is True
        without_client_certificate = ssl.create_default_context(cafile=str(cafile))
        unauthenticated = ExternalWitnessClient(
            HTTPSWitnessTransport(
                f"https://localhost:{listener.server_port}/attest",
                without_client_certificate, timeout_seconds=2.0,
            ),
            witness_id="witness-1", leader_id="leader-1",
            leader_epoch=7, response_public_key=pub,
        )
        with pytest.raises(ExternalWitnessDenied):
            claim(unauthenticated, grant="grant-2", seq=2)
    finally:
        listener.shutdown()
        listener.server_close()
        worker.join(timeout=3)


def test_cloning_witness_trust_domain_would_still_split_brain(tmp_path):
    """Expected qualification gap: duplicated signer and witness DB are unsafe."""
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    left = SyntheticExternalAuthority(tmp_path / "witness-left.sqlite", key)
    right = SyntheticExternalAuthority(tmp_path / "witness-right.sqlite", key)
    l = ExternalWitnessClient(left, witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    r = ExternalWitnessClient(right, witness_id="witness-1", leader_id="leader-1", leader_epoch=7, response_public_key=pub)
    assert claim(l) is True
    assert claim(r) is True
