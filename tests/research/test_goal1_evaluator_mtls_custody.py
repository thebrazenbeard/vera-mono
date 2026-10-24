"""Ephemeral loopback mTLS claim-custody tests. No external listener or service."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from urllib.error import HTTPError,URLError
from urllib.request import Request,HTTPSHandler,ProxyHandler,build_opener

from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa,ed25519
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID

from research.goal1_acceptance_bridge.evaluator_claim_custody import (
    CustodyLedger, ClaimDenied, ClaimEvidenceReader, serve_mtls,
)

def h(s):return hashlib.sha256(s.encode()).hexdigest()
BIND={
    "reservation_id":"res-mtls","run_id":"run-mtls","arm":"FROZEN",
    "challenge_id":"challenge-mtls","challenge_view_digest":h("view"),
    "model_prompt_sha256":h("prompt"),"model_identity":"synthetic",
    "model_artifact_sha256":h("artifact"),
}

def pem_private(key):
    return key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,serialization.NoEncryption())

def make_certs(root:Path):
    issuer=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"Goal1 isolated test CA")])
    now=datetime.now(timezone.utc)
    ca=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(issuer.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,
            key_encipherment=False,data_encipherment=False,key_agreement=False,
            key_cert_sign=True,crl_sign=True,encipher_only=False,decipher_only=False),critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(issuer.public_key()),critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer.public_key()),critical=False)
        .sign(issuer,hashes.SHA256()))
    (root/"ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    def leaf(label,filename,server=False):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,label)])
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(subject)
             .public_key(key.public_key()).serial_number(x509.random_serial_number())
             .not_valid_before(now-timedelta(minutes=1))
             .not_valid_after(now+timedelta(minutes=30))
             .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
             .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer.public_key()),critical=False)
             .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),critical=False)
             .add_extension(x509.ExtendedKeyUsage([
                 ExtendedKeyUsageOID.SERVER_AUTH if server else ExtendedKeyUsageOID.CLIENT_AUTH
             ]),critical=False)
             .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]) if server
                 else x509.SubjectAlternativeName([x509.DNSName(label)]),critical=False)
             .sign(issuer,hashes.SHA256()))
        (root/(filename+".pem")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root/(filename+".key")).write_bytes(pem_private(key))
    leaf("localhost","server",True)
    leaf("gateway-test","gateway")
    leaf("wrong-identity","wrong")
    return root

class LoopbackCustody(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="goal1-mtls-custody-")
        self.addCleanup(tmp.cleanup)
        self.root=make_certs(Path(tmp.name))
        self.signing=ed25519.Ed25519PrivateKey.generate()
        self.ledger=CustodyLedger(self.root/"ledger.sqlite",
            signing_key=self.signing,key_id="ephemeral-evaluator")
        self.ledger.reserve(BIND)
        with socket.socket() as s:
            s.bind(("127.0.0.1",0))
            port=s.getsockname()[1]
        self.server=serve_mtls(ledger=self.ledger,bind_host="127.0.0.1",port=port,
            server_cert=self.root/"server.pem",server_key=self.root/"server.key",
            ca_bundle=self.root/"ca.pem",allowed_gateway_id="gateway-test")
        self.addCleanup(self._cleanup)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base="https://localhost:"+str(port)
    def _cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
    def opener(self,cert="gateway"):
        ctx=ssl.create_default_context(cafile=str(self.root/"ca.pem"))
        if cert is not None:
            ctx.load_cert_chain(str(self.root/(cert+".pem")),
                                str(self.root/(cert+".key")))
        return build_opener(ProxyHandler({}),HTTPSHandler(context=ctx))
    def claim(self,cert="gateway"):
        body=json.dumps({"reservation":BIND,"gateway_id":"gateway-test",
                         "invocation_id":"inv-mtls"}).encode()
        request=Request(self.base+"/v1/reservations/claim",data=body,method="POST",
                        headers={"Content-Type":"application/json"})
        with self.opener(cert).open(request,timeout=3) as response:
            self.assertEqual(response.status,200)
            return json.loads(response.read())
    def reader(self,pub=None):
        if pub is None:
            pub=self.signing.public_key().public_bytes(
                serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        return ClaimEvidenceReader(endpoint_url=self.base+"/v1/reservations/evidence/",
            ca_bundle=self.root/"ca.pem",client_certificate=self.root/"gateway.pem",
            client_private_key=self.root/"gateway.key",pinned_public_key=pub,
            expected_key_id="ephemeral-evaluator")
    def test_real_mtls_claim_cold_signed_readback(self):
        claimed=self.claim()
        expected={k:claimed[k] for k in (*BIND,"gateway_id","invocation_id","claim_id")}
        verified=self.reader().verify_claim_evidence(expected_binding=expected)
        self.assertEqual(verified,claimed)
        fresh=CustodyLedger(self.root/"ledger.sqlite",signing_key=self.signing,
                            key_id="ephemeral-evaluator")
        self.assertEqual(fresh.read_claim(claimed["claim_id"]),claimed)
        with self.assertRaises(HTTPError) as error: self.claim()
        self.assertEqual(error.exception.code,409)
        error.exception.close()
    def test_wrong_client_identity_denied_and_reservation_preserved(self):
        with self.assertRaises(HTTPError) as error:self.claim("wrong")
        self.assertEqual(error.exception.code,403)
        error.exception.close()
        self.assertEqual(self.ledger.reservation_status("res-mtls"),"RESERVED")
        self.assertEqual(self.claim()["status"],"CLAIMED")
    def test_no_client_cert_tls_handshake_rejected(self):
        with self.assertRaises((ssl.SSLError,URLError,OSError)):
            self.claim(None)
        self.assertEqual(self.ledger.reservation_status("res-mtls"),"RESERVED")
    def test_wrong_pinned_evaluator_signer_rejected(self):
        claimed=self.claim()
        alternate=ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        expected={k:claimed[k] for k in (*BIND,"gateway_id","invocation_id","claim_id")}
        with self.assertRaises(ClaimDenied):
            self.reader(pub=alternate).verify_claim_evidence(expected_binding=expected)
    def test_bad_claim_expected_binding_rejected(self):
        claimed=self.claim()
        expected={k:claimed[k] for k in (*BIND,"gateway_id","invocation_id","claim_id")}
        expected["run_id"]="other"
        with self.assertRaises(ClaimDenied):
            self.reader().verify_claim_evidence(expected_binding=expected)

if __name__=="__main__":
    unittest.main()
