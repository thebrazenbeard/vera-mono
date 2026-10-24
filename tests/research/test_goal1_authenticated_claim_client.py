"""Source-only real loopback TLS handshake tests; not endpoint deployment.

The test CA and signing keys are disposable, same-process test fixtures. They
prove TLS behavior, NOT independently administered evaluator custody.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from research.goal1_gateway.authenticated_claim_client import (
    AuthenticatedReservationClaimClient, ClaimTransportHold,
)

DIGEST = "a" * 64
RESERVATION = {
    "reservation_id": "res-test", "run_id": "run-test",
    "arm": "FROZEN", "challenge_id": "c-test",
    "challenge_view_digest": DIGEST, "model_prompt_sha256": DIGEST,
    "model_identity": "mock-model", "model_artifact_sha256": DIGEST,
}


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _certificate(subject, key, *, ca_key, ca_cert=None, is_ca=False, server=False, client=False):
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    issuer = name if ca_cert is None else ca_cert.subject
    builder = (x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=1))
        .not_valid_after(now+timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=0 if is_ca else None),critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=not is_ca, data_encipherment=False,
            key_agreement=False, key_cert_sign=is_ca, crl_sign=is_ca,
            encipher_only=False, decipher_only=False,
        ),critical=True))
    if server:
        builder = (builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False))
    if client:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),critical=False)
    return builder.sign(private_key=ca_key, algorithm=hashes.SHA256())


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def _cert_pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


class _ClaimHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        with self.server.lock:
            self.server.received += 1
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path != "/v1/reservations/claim" or not self.connection.getpeercert():
            self.send_error(403)
            return
        if self.server.reply_mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:11434/api/generate")
            self.end_headers()
            return
        if self.server.reply_mode == "oversized":
            data = b" " * 4100
        elif self.server.reply_mode == "badjson":
            data = b"{bad}"
        else:
            reservation = request["reservation"]
            claim = dict(reservation, status="CLAIMED", gateway_id=request["gateway_id"],
                         invocation_id=request["invocation_id"], claim_id="claim-once")
            if self.server.reply_mode == "mismatch":
                claim["run_id"] = "run-substituted"
            with self.server.lock:
                if self.server.claimed:
                    self.send_error(409, "reservation already claimed")
                    return
                self.server.claimed = True
            data = json.dumps(claim).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class AuthenticatedClaimClientTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gateway-mtls-test-")
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        ca_key = _key()
        ca_cert = _certificate("synthetic CA", ca_key, ca_key=ca_key, is_ca=True)
        server_key = _key()
        server_cert = _certificate("localhost", server_key,
                                   ca_key=ca_key, ca_cert=ca_cert, server=True)
        client_key = _key()
        client_cert = _certificate("research gateway", client_key,
                                   ca_key=ca_key, ca_cert=ca_cert, client=True)
        self.ca = _write(self.dir/"ca.pem", _cert_pem(ca_cert))
        self.server_cert = _write(self.dir/"server.pem", _cert_pem(server_cert))
        self.server_key = _write(self.dir/"server.key", _key_pem(server_key))
        self.client_cert = _write(self.dir/"client.pem", _cert_pem(client_cert))
        self.client_key = _write(self.dir/"client.key", _key_pem(client_key))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ClaimHandler)
        self.server.lock = threading.RLock()
        self.server.claimed = False
        self.server.received = 0
        self.server.reply_mode = "valid"
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(certfile=str(self.server_cert), keyfile=str(self.server_key))
        tls.verify_mode = ssl.CERT_REQUIRED
        tls.load_verify_locations(cafile=str(self.ca))
        self.server.socket = tls.wrap_socket(self.server.socket, server_side=True)
        thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "https://localhost:%d/v1/reservations/claim" % self.server.server_port

    def client(self, **changes):
        config = dict(endpoint_url=self.url,ca_bundle=self.ca,
                      client_certificate=self.client_cert,client_private_key=self.client_key,
                      timeout_seconds=3)
        config.update(changes)
        return AuthenticatedReservationClaimClient(**config)

    def claim(self, client=None):
        return (client or self.client()).claim_reservation(
            reservation=dict(RESERVATION),gateway_id="gateway-test",
            invocation_id="invocation-test"
        )

    def test_real_mutual_tls_claim_and_one_use_remote_replay(self):
        got = self.claim()
        self.assertEqual(got["claim_id"], "claim-once")
        self.assertEqual(got["status"], "CLAIMED")
        with self.assertRaises(ClaimTransportHold):
            self.claim()
        self.assertEqual(self.server.received, 2)
        self.assertTrue(self.server.claimed)

    def test_tls_wrong_trust_root_denied_before_http_handler(self):
        bad_key = _key()
        bad_cert = _certificate("untrusted CA",bad_key,ca_key=bad_key,is_ca=True)
        bad_ca = _write(self.dir/"bad-ca.pem",_cert_pem(bad_cert))
        with self.assertRaises(ClaimTransportHold):
            self.claim(self.client(ca_bundle=bad_ca))
        self.assertEqual(self.server.received,0)

    def test_valid_but_untrusted_gateway_certificate_is_rejected_by_server(self):
        key = _key()
        wrong_ca_key = _key()
        wrong_ca = _certificate("separate CA", wrong_ca_key,
                                ca_key=wrong_ca_key, is_ca=True)
        bad_client = _certificate("unauthorized client", key,
                                  ca_key=wrong_ca_key, ca_cert=wrong_ca, client=True)
        bad_cert_path = _write(self.dir/"unauthorized.pem", _cert_pem(bad_client))
        bad_key_path = _write(self.dir/"unauthorized.key", _key_pem(key))
        with self.assertRaises(ClaimTransportHold):
            self.claim(self.client(client_certificate=bad_cert_path,
                                   client_private_key=bad_key_path))
        self.assertEqual(self.server.received, 0)

    def test_server_hostname_mismatch_is_denied(self):
        # The test server presents a certificate for localhost only.
        with self.assertRaises(ClaimTransportHold):
            self.claim(self.client(endpoint_url=self.url.replace("localhost", "127.0.0.1")))
        self.assertEqual(self.server.received, 0)

    def test_tls_missing_gateway_certificate_denied(self):
        with self.assertRaises(ClaimTransportHold):
            self.client(client_certificate=self.dir/"absent.pem")
        self.assertEqual(self.server.received, 0)

    def test_no_http_redirect_even_to_local_ollama(self):
        self.server.reply_mode = "redirect"
        with self.assertRaises(ClaimTransportHold):
            self.claim()
        self.assertEqual(self.server.received,1)

    def test_response_size_and_json_must_be_bounded(self):
        for mode in ("oversized","badjson"):
            with self.subTest(mode=mode):
                self.server.reply_mode=mode
                with self.assertRaises(ClaimTransportHold):
                    self.claim()
        self.assertEqual(self.server.received,2)

    def test_mismatched_claim_remains_untrusted_until_exact_helper_checks(self):
        # #87 owns binding validation; the transport returns the raw untrusted
        # response for that helper, never labels it independently verified.
        self.server.reply_mode="mismatch"
        got=self.claim()
        self.assertNotEqual(got["run_id"],RESERVATION["run_id"])

    def test_never_accept_unauthenticated_or_bearer_urls(self):
        for url in (
            "http://localhost:11434/v1/reservations/claim",
            "https://user:pass@localhost/v1/reservations/claim",
            "https://localhost/v1/reservations/claim?ticket=x",
            "https://localhost/api/generate",
        ):
            with self.subTest(url=url),self.assertRaises(ValueError):
                self.client(endpoint_url=url)
        self.assertEqual(self.server.received,0)

    def test_invalid_envelope_has_no_network_or_remote_claim(self):
        invalid=dict(RESERVATION)
        invalid["surprise"]="x"
        with self.assertRaises(ValueError):
            self.client().claim_reservation(
                reservation=invalid,gateway_id="gateway",invocation_id="invocation")
        self.assertEqual(self.server.received,0)


if __name__ == "__main__":
    unittest.main()
