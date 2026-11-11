"""Experimental evaluator-controlled reservation ledger and mTLS readback.

The custodian's PRIVATE signing key and database are held by the evaluator
process, not the networkless learner or the gateway callback. Running this
test under the same administrative owner does not establish independent
operator custody, production enrollment, or real model evidence.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address, ip_network
import json
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
from threading import BoundedSemaphore, Lock, Thread, Timer, current_thread
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener
from urllib.error import HTTPError, URLError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FIELDS=("reservation_id","run_id","arm","challenge_id","challenge_view_digest",
        "model_prompt_sha256","model_identity","model_artifact_sha256")
IDENT=re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
SHA=re.compile(r"[0-9a-f]{64}\Z")
ARMS=frozenset(("FROZEN","LEARNED","PLACEBO","SHUFFLED"))
MAX_ACTIVE_MTLS_CLIENTS=8
MAX_MTLS_CLIENT_SECONDS=3.0
TLS_HANDSHAKE_SECONDS=1.0
TLS_IDLE_SECONDS=1.0


class ClaimDenied(RuntimeError):
    """A missing/ambiguous/previously consumed claim is never replayable."""


def canonical(value: dict) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),
                      ensure_ascii=False,allow_nan=False).encode("utf-8")


def check_reservation(binding: dict) -> None:
    if type(binding) is not dict or frozenset(binding)!=frozenset(FIELDS):
        raise ClaimDenied("reservation schema rejected")
    for name,value in binding.items():
        if type(value) is not str or not value:
            raise ClaimDenied("empty reservation field")
        if name.endswith("_sha256") or name.endswith("_digest"):
            if not SHA.fullmatch(value):
                raise ClaimDenied("invalid reservation digest")
        elif name!="model_identity" and not IDENT.fullmatch(value):
            raise ClaimDenied("invalid reservation identity")
    if binding["arm"] not in ARMS or len(binding["model_identity"])>128:
        raise ClaimDenied("reservation arm/model invalid")


def check_id(value: str) -> None:
    if type(value) is not str or not IDENT.fullmatch(value):
        raise ClaimDenied("invalid request identity")


class CustodyLedger:
    def __init__(self,path,*,signing_key,key_id:str):
        check_id(key_id)
        if not callable(getattr(signing_key,"sign",None)):
            raise ValueError("independent evaluator signing key required")
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.signing_key=signing_key
        self.key_id=key_id
        with closing(self._connect()) as db,db:
            db.execute("""CREATE TABLE IF NOT EXISTS reservations(
                reservation_id TEXT PRIMARY KEY,run_id TEXT NOT NULL,
                arm TEXT NOT NULL,challenge_id TEXT NOT NULL,
                reservation_bytes BLOB NOT NULL,binding_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('RESERVED','CLAIMED')),
                gateway_id TEXT,invocation_id TEXT,claim_id TEXT UNIQUE,
                claim_bytes BLOB,signature BLOB,
                UNIQUE(run_id,arm,challenge_id))""")

    def _connect(self):
        db=sqlite3.connect(str(self.path),timeout=8,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute("PRAGMA busy_timeout=8000")
        return db

    def reserve(self,binding:dict)->None:
        """Administrative seed only. NEVER expose over public gateway route."""
        check_reservation(binding)
        wire=canonical(binding)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""INSERT INTO reservations
                    (reservation_id,run_id,arm,challenge_id,
                     reservation_bytes,binding_sha256,status)
                    VALUES(?,?,?,?,?,?,'RESERVED')""",
                    (binding["reservation_id"],binding["run_id"],binding["arm"],
                     binding["challenge_id"],wire,sha256(wire).hexdigest()))
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ClaimDenied("reservation already used/seeded") from exc

    def reservation_status(self,reservation_id:str)->str|None:
        check_id(reservation_id)
        with closing(self._connect()) as db:
            row=db.execute("SELECT status FROM reservations WHERE reservation_id=?",
                           (reservation_id,)).fetchone()
            return row["status"] if row else None

    def claim(self,reservation:dict,*,gateway_id:str,invocation_id:str)->dict:
        check_reservation(reservation)
        check_id(gateway_id);check_id(invocation_id)
        wire=canonical(reservation)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row=db.execute("""SELECT reservation_bytes,binding_sha256,status
                       FROM reservations WHERE reservation_id=?""",
                       (reservation["reservation_id"],)).fetchone()
                if (row is None or row["status"]!="RESERVED"
                        or row["reservation_bytes"]!=wire
                        or row["binding_sha256"]!=sha256(wire).hexdigest()):
                    raise ClaimDenied("unseeded, modified or already claimed")
                claim={**reservation,"gateway_id":gateway_id,
                       "invocation_id":invocation_id,
                       "status":"CLAIMED","claim_id":"claim-"+secrets.token_hex(16)}
                claim_wire=canonical(claim)
                sig=self.signing_key.sign(claim_wire)
                changed=db.execute("""UPDATE reservations
                      SET status='CLAIMED',gateway_id=?,invocation_id=?,
                          claim_id=?,claim_bytes=?,signature=?
                      WHERE reservation_id=? AND status='RESERVED'""",
                      (gateway_id,invocation_id,claim["claim_id"],
                       sqlite3.Binary(claim_wire),sqlite3.Binary(sig),
                       reservation["reservation_id"]))
                if changed.rowcount!=1:
                    raise ClaimDenied("atomic reservation claim lost")
                db.commit()
                return claim
            except BaseException:
                db.rollback()
                raise

    def evidence(self,claim_id:str)->dict:
        check_id(claim_id)
        with closing(self._connect()) as db:
            row=db.execute("""SELECT claim_bytes,signature,status FROM reservations
                           WHERE claim_id=?""",(claim_id,)).fetchone()
        if row is None or row["status"]!="CLAIMED":
            raise ClaimDenied("claim evidence unavailable")
        wire=row["claim_bytes"];sig=row["signature"]
        if type(wire) is not bytes or type(sig) is not bytes:
            raise ClaimDenied("claim evidence corrupted")
        parsed=json.loads(wire.decode("utf-8"))
        if canonical(parsed)!=wire or parsed.get("claim_id")!=claim_id:
            raise ClaimDenied("claim evidence wire mismatch")
        return {"payload_bytes":wire,"signature":sig,"response":parsed,
                "key_id":self.key_id}

    def read_claim(self,claim_id:str)->dict:
        return self.evidence(claim_id)["response"]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        raise ClaimDenied("claim readback redirect denied")


class ClaimEvidenceReader:
    """Authenticated mTLS readback, original Ed25519 bytes + externally pinned key.

    Pinning inputs and certificates supplied by the SAME operator do not
    establish separate governance; verify actual custody independently.
    """
    def __init__(self,*,endpoint_url:str,ca_bundle,client_certificate,
                 client_private_key,pinned_public_key:bytes,
                 expected_key_id:str,timeout:float=3):
        check_id(expected_key_id)
        if type(pinned_public_key) is not bytes or len(pinned_public_key)!=32:
            raise ValueError("32-byte pinned evaluator Ed25519 key required")
        parts=urlsplit(endpoint_url)
        if (parts.scheme!="https" or not parts.hostname
                or parts.path!="/v1/reservations/evidence/"
                or parts.query or parts.fragment or parts.username or parts.password):
            raise ValueError("exact HTTPS evaluator evidence URL required")
        if type(timeout) not in (int,float) or not 0<timeout<=10:
            raise ValueError("bounded verifier timeout required")
        self.endpoint_url=endpoint_url
        self.expected_key_id=expected_key_id
        self.pinned_public_key=pinned_public_key
        self.timeout=timeout
        ctx=ssl.create_default_context(cafile=str(ca_bundle))
        ctx.load_cert_chain(certfile=str(client_certificate),
                            keyfile=str(client_private_key))
        ctx.verify_mode=ssl.CERT_REQUIRED
        ctx.check_hostname=True
        self.opener=build_opener(ProxyHandler({}),HTTPSHandler(context=ctx),
                                _NoRedirect())

    def verify_claim_evidence(self,*,expected_binding:dict[str,str])->dict[str,str]:
        if type(expected_binding) is not dict or frozenset(expected_binding)!=frozenset(
                (*FIELDS,"gateway_id","invocation_id","claim_id")):
            raise ClaimDenied("expected claim binding schema invalid")
        for value in expected_binding.values():
            if type(value) is not str or not value:
                raise ClaimDenied("expected claim binding empty")
        claim_id=expected_binding["claim_id"]
        check_id(claim_id)
        request=Request(self.endpoint_url+claim_id,method="GET")
        try:
            with self.opener.open(request,timeout=self.timeout) as response:
                if response.status!=200:
                    raise ClaimDenied("claim readback status invalid")
                raw=response.read(8193)
                if len(raw)>8192:
                    raise ClaimDenied("claim readback oversized")
        except ClaimDenied:
            raise
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as exc:
            raise ClaimDenied("authenticated claim evidence readback unavailable") from exc
        try:
            body=json.loads(raw)
            if type(body) is not dict or frozenset(body)!={"payload_hex","signature_hex","key_id"}:
                raise ValueError("invalid evidence schema")
            wire=bytes.fromhex(body["payload_hex"])
            signature=bytes.fromhex(body["signature_hex"])
            if body["key_id"]!=self.expected_key_id:
                raise ValueError("wrong evaluator key identity")
            Ed25519PublicKey.from_public_bytes(self.pinned_public_key).verify(signature,wire)
            evidence=json.loads(wire.decode("utf-8"))
            if (type(evidence) is not dict or canonical(evidence)!=wire
                    or evidence.get("status")!="CLAIMED"
                    or frozenset(evidence)!=frozenset((*FIELDS,"status",
                       "gateway_id","invocation_id","claim_id"))
                    or any(evidence.get(k)!=v for k,v in expected_binding.items())):
                raise ValueError("claim evidence original binding mismatch")
            return evidence
        except (ValueError,TypeError,KeyError,UnicodeError,Exception) as exc:
            raise ClaimDenied("claim evidence signature or binding invalid") from exc


class _BoundedMTLSServer(ThreadingHTTPServer):
    """Accept raw TCP promptly; do bounded TLS and HTTP work in workers.

    Wrapping the *listening* socket in TLS performs blocking handshakes inside
    accept(), serializing the entire server behind an unauthenticated peer.
    Each admitted raw peer instead owns one bounded worker and an absolute
    deadline that also interrupts slow-trickled HTTP headers and bodies.
    """

    daemon_threads=True
    request_queue_size=MAX_ACTIVE_MTLS_CLIENTS

    def __init__(self,address,handler,*,tls_context):
        self._tls_context=tls_context
        self._client_slots=BoundedSemaphore(MAX_ACTIVE_MTLS_CLIENTS)
        self._workers={}
        self._workers_lock=Lock()
        self._closing=False
        super().__init__(address,handler)

    def process_request(self,request,client_address):
        if not self._client_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        worker=Thread(target=self._process_bounded_tls,
                      name="goal1-mtls-client-"+str(client_address[1]),
                      args=(request,client_address),daemon=True)
        with self._workers_lock:
            if self._closing:
                self._client_slots.release()
                self.shutdown_request(request)
                return
            self._workers[worker]=request
            try:
                # Registration/start are atomic with respect to server_close.
                worker.start()
            except BaseException:
                self._workers.pop(worker,None)
                self._client_slots.release()
                self.shutdown_request(request)
                raise

    def _process_bounded_tls(self,request,client_address):
        protected=None
        deadline=None
        try:
            request.settimeout(TLS_HANDSHAKE_SECONDS)
            # Explicitly defer the handshake; it must run in THIS worker,
            # never in the main TCP accept loop.
            protected=self._tls_context.wrap_socket(
                request,server_side=True,do_handshake_on_connect=False)
            protected.settimeout(TLS_HANDSHAKE_SECONDS)
            with self._workers_lock:
                self._workers[current_thread()]=protected
                closing=self._closing
            if closing:
                return

            def expire():
                # shutdown(), unlike close() alone from another thread,
                # interrupts buffered socket reads already in progress.
                try:protected.shutdown(socket.SHUT_RDWR)
                except OSError:pass

            deadline=Timer(MAX_MTLS_CLIENT_SECONDS,expire)
            deadline.daemon=True
            deadline.start()
            protected.do_handshake()
            protected.settimeout(TLS_IDLE_SECONDS)
            self.process_request_thread(protected,client_address)
        except (OSError,ssl.SSLError,TimeoutError):
            # Certificate failure, timeout, abrupt peer disconnect: no claim.
            pass
        finally:
            if deadline is not None:deadline.cancel()
            if protected is not None:protected.close()
            else:request.close()
            with self._workers_lock:self._workers.pop(current_thread(),None)
            self._client_slots.release()

    def server_close(self):
        with self._workers_lock:
            self._closing=True
            workers=dict(self._workers)
        for connection in workers.values():
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        super().server_close()
        # A closing test/service does not retain detached TLS worker threads.
        deadline=monotonic()+MAX_MTLS_CLIENT_SECONDS+0.5
        for worker in workers:
            if worker is not current_thread() and worker.ident is not None:
                worker.join(timeout=max(0,deadline-monotonic()))

    def handle_error(self,request,client_address):
        # Connection deadline or disconnected TLS client may interrupt a
        # response write. Do not emit a traceback for ordinary transport loss.
        import sys
        if isinstance(sys.exc_info()[1],(
                BrokenPipeError,ConnectionResetError,TimeoutError,ssl.SSLError)):
            return
        super().handle_error(request,client_address)


def serve_mtls(*,ledger:CustodyLedger,bind_host:str,port:int,server_cert,
               server_key,ca_bundle,allowed_gateway_id:str):
    """Return an HTTPS server; caller controls start/stop and test cleanup."""
    check_id(allowed_gateway_id)
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError("port required")
    try:
        ip=ip_address(bind_host)
    except ValueError as exc:
        raise ValueError("numeric IP bind address required") from exc
    if (not isinstance(ip,IPv4Address)
            or not (ip.is_loopback or ip in ip_network("100.64.0.0/10"))):
        raise ValueError("research listener restricted to loopback or tailnet IPv4")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            return
        def _authorized(self):
            peer=self.connection.getpeercert()
            cn=[value for row in peer.get("subject",()) for k,value in row if k=="commonName"]
            return cn==[allowed_gateway_id]
        def _send(self,status:int,payload:dict):
            data=canonical(payload)
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(data)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            if self.path!="/v1/reservations/claim" or not self._authorized():
                self._send(403,{"error":"forbidden"});return
            try:
                length=int(self.headers.get("Content-Length","0"))
                if length<1 or length>2048:
                    raise ClaimDenied("request size rejected")
                request=json.loads(self.rfile.read(length))
                if type(request) is not dict or frozenset(request)!={
                        "reservation","gateway_id","invocation_id"}:
                    raise ClaimDenied("request framing rejected")
                if request["gateway_id"]!=allowed_gateway_id:
                    raise ClaimDenied("client certificate/gateway mismatch")
                claim=ledger.claim(request["reservation"],
                    gateway_id=request["gateway_id"],invocation_id=request["invocation_id"])
                self._send(200,claim)
            except (ClaimDenied,ValueError,TypeError,KeyError):
                self._send(409,{"error":"claim denied"})
        def do_GET(self):
            prefix="/v1/reservations/evidence/"
            if not self.path.startswith(prefix) or not self._authorized():
                self._send(403,{"error":"forbidden"});return
            try:
                claim_id=self.path[len(prefix):]
                evidence=ledger.evidence(claim_id)
                self._send(200,{"payload_hex":evidence["payload_bytes"].hex(),
                                "signature_hex":evidence["signature"].hex(),
                                "key_id":evidence["key_id"]})
            except (ClaimDenied,ValueError):
                self._send(404,{"error":"unavailable"})
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(server_cert),str(server_key))
    context.load_verify_locations(cafile=str(ca_bundle))
    context.verify_mode=ssl.CERT_REQUIRED
    return _BoundedMTLSServer((bind_host,port),Handler,tls_context=context)
