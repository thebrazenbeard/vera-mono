"""Exclusive witness event leader and mutually authenticated network boundary.

SOURCE CANDIDATE ONLY. The signing key, SQLite database, consent controller,
TLS server identity, and registration API MUST live in a dedicated OS principal
outside both model and provider processes. Cloning all these roots together or
running model code in the leader process defeats the guarantee.

The leader independently verifies issuer-signed grants through an out-of-band,
host-admin-only registration operation. Neither model IPC nor the mTLS event
endpoint can enroll grants. A locally cloned host-authority DB has no control
over the leader's durable grant/effect/consent state or global event sequence.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import stat
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .bindings import HostBindingSnapshot
from .grants import ApprovedGrant, SignedGrantVerifier
from .unified_authority import (
    ACK_CONTEXT, KINDS, RECEIPT_SCHEMA, REQUEST_SCHEMA, SIGNATURE_CONTEXT,
)


FENCE_REQUEST_SCHEMA = "HOST_AUTHZ_UNIFIED_PROVIDER_FENCE_REQUEST_V1"
FENCE_RESPONSE_SCHEMA = "HOST_AUTHZ_UNIFIED_PROVIDER_FENCE_RESPONSE_V1"
FENCE_ACK_CONTEXT = b"VERA_HOST_AUTHZ_UNIFIED_PROVIDER_FENCE_ACK_V1\0"
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BODY = 64 * 1024
_REQUEST_FIELDS = frozenset({
    "schema", "host_id", "issuer_id", "epoch", "leader_epoch", "challenge",
    "kind", "event_digest", "event",
})
_RECEIPT_FIELDS = frozenset({
    "host_id", "issuer_id", "epoch", "leader_epoch", "challenge", "kind",
    "event_digest", "sequence", "approved",
})
_FENCE_FIELDS = frozenset({
    "schema", "host_id", "epoch", "provider_id", "provider_instance_id",
    "effect_id", "claim_sequence", "request_digest", "grant_id",
    "participant_id", "purpose", "operation",
})


class WitnessLeaderDenied(PermissionError):
    """The independently owned leader refused a transition."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise WitnessLeaderDenied("duplicate JSON field")
        result[key] = value
    return result


def _bad_constant(_: str) -> Any:
    raise WitnessLeaderDenied("nonfinite JSON constant")


def _canonical(obj: Any) -> bytes:
    try:
        return canonical_json_bytes(obj)
    except (ValueError, TypeError, OverflowError) as exc:
        raise WitnessLeaderDenied("noncanonical witness JSON") from exc


def _decode(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_BODY:
        raise WitnessLeaderDenied("invalid witness message length")
    try:
        obj = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique,
                         parse_constant=_bad_constant)
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise WitnessLeaderDenied("malformed witness JSON") from exc
    if type(obj) is not dict or _canonical(obj) != raw:
        raise WitnessLeaderDenied("noncanonical witness message")
    return obj


def _check_digest(value: Any) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _scope(grant: ApprovedGrant) -> str:
    return sha256(_canonical({field: getattr(grant, field) for field in (
        "participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
        "subject_id", "host_id", "provider_id", "provider_instance_id",
    )})).hexdigest()


def _effect(grant: ApprovedGrant) -> str:
    return sha256(_canonical({
        "schema": "HOST_AUTHZ_UNIFIED_EFFECT_V1", "grant_id": grant.grant_id,
        "issuer_id": grant.issuer_id, "host_id": grant.host_id,
        "epoch": grant.epoch, "provider_instance_id": grant.provider_instance_id,
        "request_digest": grant.request_digest,
    })).hexdigest()


def _secure_database_path(path: Path) -> None:
    if os.name != "posix" or not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise WitnessLeaderDenied("leader requires POSIX exclusive state path")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise WitnessLeaderDenied("leader state directory absent") from exc
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        raise WitnessLeaderDenied("leader state directory must be owned and private")
    try:
        entry = path.lstat()
    except FileNotFoundError:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    else:
        if not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.geteuid() or entry.st_mode & 0o077:
            raise WitnessLeaderDenied("leader database ownership changed")


@dataclass(frozen=True, slots=True)
class WitnessLeaderConfig:
    host_id: str
    issuer_id: str
    epoch: int
    leader_epoch: int
    host_client_sha256: str
    provider_client_sha256: Mapping[str, str]

    def __post_init__(self) -> None:
        if not all(type(value) is str and value for value in (self.host_id, self.issuer_id)):
            raise ValueError("host/issuer identity required")
        if type(self.epoch) is not int or type(self.leader_epoch) is not int or self.epoch < 1 or self.leader_epoch < 1:
            raise ValueError("positive epochs required")
        if not _check_digest(self.host_client_sha256) or type(self.provider_client_sha256) is not dict:
            raise ValueError("host and per-provider mTLS client certificate fingerprints required")
        provider_certs = dict(self.provider_client_sha256)
        if (not provider_certs
                or any(type(provider) is not str or not provider or not _check_digest(cert)
                       for provider, cert in provider_certs.items())
                or len(set(provider_certs.values())) != len(provider_certs)
                or self.host_client_sha256 in provider_certs.values()):
            raise ValueError("host/provider certificate identities must be disjoint")
        object.__setattr__(self, "provider_client_sha256", MappingProxyType(provider_certs))


class UnifiedWitnessLeader:
    """One durable, exclusive source-level leader, no network grant enrollment."""

    def __init__(self, path: str | Path, *, config: WitnessLeaderConfig,
                 bindings: HostBindingSnapshot, verifier: SignedGrantVerifier,
                 receipt_signer: Ed25519PrivateKey,
                 provider_public_keys: Mapping[str, bytes],
                 trusted_clock: Callable[[], int],
                 consent_status: Callable[[ApprovedGrant, int], bool]):
        if type(config) is not WitnessLeaderConfig or type(bindings) is not HostBindingSnapshot:
            raise TypeError("host-owned exact leader configuration required")
        if type(verifier) is not SignedGrantVerifier or not isinstance(receipt_signer, Ed25519PrivateKey):
            raise TypeError("pinned issuer verifier and Ed25519 leader signer required")
        if not callable(trusted_clock) or not callable(consent_status):
            raise ValueError("leader clock and consent authority must be configured")
        if (bindings.host_id, bindings.issuer_id, bindings.epoch) != (config.host_id, config.issuer_id, config.epoch):
            raise ValueError("leader host binding does not match host/issuer/epoch")
        if set(config.provider_client_sha256) != set(bindings.providers):
            raise ValueError("per-provider certificate identity registry differs from bindings")
        if (verifier.host_id, verifier.issuer_id, verifier.epoch) != (config.host_id, config.issuer_id, config.epoch):
            raise ValueError("leader issuer verifier does not match host binding")
        if type(provider_public_keys) is not dict or set(provider_public_keys) != set(bindings.providers):
            raise ValueError("exact pinned provider key registry required")
        if any(type(key) is not bytes or len(key) != 32 for key in provider_public_keys.values()):
            raise ValueError("invalid pinned provider Ed25519 key")
        self.config = config
        self.bindings = bindings
        self._verifier = verifier
        self._key = receipt_signer
        self._provider_keys = {provider: Ed25519PublicKey.from_public_bytes(key)
                               for provider, key in provider_public_keys.items()}
        self._provider_digest = sha256(_canonical({provider: key.hex()
                                                  for provider, key in provider_public_keys.items()})).hexdigest()
        self._client_digest = sha256(_canonical(dict(config.provider_client_sha256))).hexdigest()
        self._clock = trusted_clock
        self._consent = consent_status
        self._path = Path(path)
        _secure_database_path(self._path)
        self._identity = (self._path.stat().st_dev, self._path.stat().st_ino)
        self._key_sha256 = sha256(receipt_signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )).hexdigest()
        self._init()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        _secure_database_path(self._path)
        st = self._path.stat()
        if (st.st_dev, st.st_ino) != self._identity:
            raise WitnessLeaderDenied("leader database substituted")
        db = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _init(self) -> None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS leader_identity (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), host_id TEXT,
                issuer_id TEXT, epoch INTEGER, leader_epoch INTEGER,
                signing_key_sha256 TEXT, provider_roots_sha256 TEXT,
                host_client_sha256 TEXT, provider_clients_sha256 TEXT,
                last_sequence INTEGER)""")
            db.execute("""CREATE TABLE IF NOT EXISTS grants (
                grant_id TEXT PRIMARY KEY, body TEXT NOT NULL,
                effect_id TEXT NOT NULL UNIQUE, scope_digest TEXT NOT NULL,
                claim_sequence INTEGER, start_sequence INTEGER,
                issued_at INTEGER, start_deadline INTEGER,
                state TEXT NOT NULL CHECK(state IN
                    ('REGISTERED','CLAIMED','STARTED','UNKNOWN','COMPLETED')))""")
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY, challenge TEXT UNIQUE NOT NULL,
                event_digest TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
                grant_id TEXT NOT NULL, receipt BLOB NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS revocations (
                scope_digest TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE)""")
            db.execute("""CREATE TABLE IF NOT EXISTS provider_fences (
                effect_id TEXT PRIMARY KEY, grant_id TEXT NOT NULL UNIQUE,
                start_sequence INTEGER NOT NULL)""")
            row = db.execute("SELECT * FROM leader_identity WHERE singleton=1").fetchone()
            expected = (self.config.host_id, self.config.issuer_id,
                        self.config.epoch, self.config.leader_epoch,
                        self._key_sha256, self._provider_digest,
                        self.config.host_client_sha256,
                        self._client_digest)
            if row is None:
                db.execute("INSERT INTO leader_identity VALUES(1,?,?,?,?,?,?,?,?,0)", expected)
            elif tuple(row[field] for field in (
                "host_id", "issuer_id", "epoch", "leader_epoch", "signing_key_sha256",
                "provider_roots_sha256", "host_client_sha256", "provider_clients_sha256",
            )) != expected:
                raise WitnessLeaderDenied("leader persisted identity/key/epoch mismatch")
            db.commit()

    def _now(self) -> int:
        now = self._clock()
        if type(now) is not int or now < 0:
            raise WitnessLeaderDenied("leader clock unavailable")
        return now

    def _consent_positive(self, grant: ApprovedGrant) -> bool:
        try:
            return self._consent(grant, self._now()) is True
        except Exception:
            return False

    def register_grant(self, signed_grant: bytes) -> str:
        """HOST-ADMIN ONLY; never reachable through HTTPS listener/model IPC.

        A real deployment needs an OS-protected administrator/issuer channel.
        Signed issuer grant and leader-owned consent must both be positive.
        """
        try:
            grant = self._verifier.verify(signed_grant)
            principal = self.bindings.principal_for_peer(grant.peer_key)
            provider = self.bindings.provider_for(principal, grant.provider_id, grant.operation)
        except Exception as exc:
            raise WitnessLeaderDenied("issuer grant or host/provider binding rejected") from exc
        if any(getattr(grant, attr) != getattr(principal, attr) for attr in (
            "peer_key", "model_id", "adapter_id", "runtime_id", "subject_id"
        )) or grant.provider_instance_id != provider.provider_instance_id:
            raise WitnessLeaderDenied("registered grant not bound to host model/provider")
        if not self._consent_positive(grant):
            raise WitnessLeaderDenied("leader has no positive consent at registration")
        scope = _scope(grant)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM revocations WHERE scope_digest=?", (scope,)).fetchone():
                raise WitnessLeaderDenied("registered scope already revoked")
            try:
                db.execute("INSERT INTO grants VALUES(?,?,?,?,NULL,NULL,NULL,NULL,'REGISTERED')",
                           (grant.grant_id, _canonical(grant.canonical_body()).decode(), _effect(grant), scope))
            except sqlite3.IntegrityError as exc:
                raise WitnessLeaderDenied("grant or effect already registered") from exc
            db.commit()
        return grant.grant_id

    def allocate_event(self, request: bytes) -> bytes:
        req = _decode(request)
        if set(req) != _REQUEST_FIELDS or req.get("schema") != REQUEST_SCHEMA:
            raise WitnessLeaderDenied("unknown allocation request")
        c = self.config
        expected = {"host_id": c.host_id, "issuer_id": c.issuer_id,
                    "epoch": c.epoch, "leader_epoch": c.leader_epoch}
        if any(type(req.get(k)) is not type(v) or req.get(k) != v for k, v in expected.items()):
            raise WitnessLeaderDenied("leader authority/epoch mismatch")
        challenge = req.get("challenge")
        if type(challenge) is not str or len(challenge) != 48 or any(ch not in "0123456789abcdef" for ch in challenge):
            raise WitnessLeaderDenied("invalid caller challenge")
        kind, event = req.get("kind"), req.get("event")
        if type(kind) is not str or kind not in KINDS or type(event) is not dict or event.get("kind") != kind:
            raise WitnessLeaderDenied("invalid witness event type")
        if not _check_digest(req.get("event_digest")) or req["event_digest"] != sha256(_canonical(event)).hexdigest():
            raise WitnessLeaderDenied("event digest does not bind event")
        grant_id = event.get("grant_id")
        if type(grant_id) is not str or not grant_id or len(grant_id) > 256:
            raise WitnessLeaderDenied("invalid grant identity")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM grants WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None:
                raise WitnessLeaderDenied("no independently registered signed grant")
            grant = ApprovedGrant(**json.loads(row["body"]))
            self._validate_transition(db, kind, event, row, grant)
            next_seq = db.execute("SELECT last_sequence FROM leader_identity WHERE singleton=1").fetchone()[0] + 1
            body = {"host_id": c.host_id, "issuer_id": c.issuer_id,
                    "epoch": c.epoch, "leader_epoch": c.leader_epoch,
                    "challenge": challenge, "kind": kind,
                    "event_digest": req["event_digest"], "sequence": next_seq,
                    "approved": True}
            assert set(body) == _RECEIPT_FIELDS
            signature = self._key.sign(SIGNATURE_CONTEXT + _canonical(body))
            response = _canonical({
                "schema": RECEIPT_SCHEMA, "body": body,
                "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
            })
            try:
                db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                           (next_seq, challenge, req["event_digest"], kind, grant_id, response))
            except sqlite3.IntegrityError as exc:
                raise WitnessLeaderDenied("challenge/event replay") from exc
            db.execute("UPDATE leader_identity SET last_sequence=? WHERE singleton=1", (next_seq,))
            if kind == "CLAIM":
                db.execute("UPDATE grants SET state='CLAIMED',claim_sequence=? WHERE grant_id=?",
                           (next_seq, grant_id))
            elif kind == "START":
                db.execute("UPDATE grants SET state='STARTED',start_sequence=?,issued_at=?,start_deadline=? WHERE grant_id=?",
                           (next_seq, event["issued_at"], event["start_deadline"], grant_id))
            elif kind == "REVOKE_SCOPE":
                db.execute("INSERT INTO revocations VALUES(?,?)", (row["scope_digest"], next_seq))
            elif kind in ("COMPLETE", "UNKNOWN"):
                db.execute("UPDATE grants SET state=? WHERE grant_id=?",
                           ("COMPLETED" if kind == "COMPLETE" else "UNKNOWN", grant_id))
            db.commit()
            return response

    def _validate_transition(self, db: sqlite3.Connection, kind: str, event: dict[str, Any],
                             row: sqlite3.Row, grant: ApprovedGrant) -> None:
        base = {"kind": "CLAIM", "grant_id": grant.grant_id,
                "effect_id": row["effect_id"], "scope_digest": row["scope_digest"],
                "provider_instance_id": grant.provider_instance_id,
                "request_digest": grant.request_digest}
        if kind == "CLAIM":
            if event != base or row["state"] != "REGISTERED":
                raise WitnessLeaderDenied("invalid/already claimed issuer grant")
            if not self._consent_positive(grant):
                raise WitnessLeaderDenied("leader consent not positive at CLAIM")
        elif kind == "REVOKE_SCOPE":
            if event != {"kind": kind, "grant_id": grant.grant_id,
                         "scope_digest": row["scope_digest"]}:
                raise WitnessLeaderDenied("invalid revocation scope")
        elif kind == "START":
            expected = {"kind": kind, "grant_id": grant.grant_id,
                        "effect_id": row["effect_id"], "scope_digest": row["scope_digest"],
                        "claim_sequence": row["claim_sequence"]}
            expected.update({name: getattr(grant, name) for name in (
                "peer_key", "model_id", "adapter_id", "runtime_id", "subject_id",
                "participant_id", "purpose", "host_id", "epoch", "operation",
                "provider_id", "provider_instance_id", "request_digest",
                "expires_at", "not_before",
            )})
            issued_at, deadline = event.get("issued_at"), event.get("start_deadline")
            expected.update({"issued_at": issued_at, "start_deadline": deadline})
            if (type(issued_at) is not int or type(deadline) is not int
                    or event != expected or row["state"] != "CLAIMED"):
                raise WitnessLeaderDenied("invalid or duplicate START")
            now = self._now()
            if not (grant.not_before <= issued_at <= now < grant.expires_at
                    and now - issued_at <= 30
                    and deadline == min(issued_at + 30, grant.expires_at - 1)
                    and issued_at <= deadline < grant.expires_at
                    and self._consent_positive(grant)):
                raise WitnessLeaderDenied("leader consent/time not positive at START")
        elif kind == "COMPLETE":
            expected = {"kind": kind, "grant_id": grant.grant_id,
                        "effect_id": row["effect_id"],
                        "start_sequence": row["start_sequence"]}
            # COMPLETE requires a previously reserved physical effect.
            if row["state"] != "STARTED" or not db.execute(
                    "SELECT 1 FROM provider_fences WHERE effect_id=?", (row["effect_id"],)).fetchone():
                raise WitnessLeaderDenied("physical effect not reserved")
            if (set(event) != set(expected) | {"receipt_digest", "provider_ack_body", "provider_ack_signature"}
                    or any(type(event.get(k)) is not type(v) or event[k] != v for k, v in expected.items())
                    or not _check_digest(event.get("receipt_digest"))):
                raise WitnessLeaderDenied("invalid COMPLETE")
            ack = event["provider_ack_body"]
            if type(ack) is not dict or set(ack) != {
                "schema", "effect_id", "provider_id", "provider_instance_id",
                "claim_sequence", "request_digest", "provider_receipt_digest",
            } or any(type(ack[name]) is not str for name in (
                "schema", "effect_id", "provider_id", "provider_instance_id",
                "request_digest", "provider_receipt_digest",
            )) or type(ack["claim_sequence"]) is not int:
                raise WitnessLeaderDenied("provider ACK shape invalid")
            if (ack["schema"] != "HOST_AUTHZ_PROVIDER_ACK_V1"
                    or ack["effect_id"] != row["effect_id"]
                    or ack["provider_id"] != grant.provider_id
                    or ack["provider_instance_id"] != grant.provider_instance_id
                    or ack["claim_sequence"] != row["claim_sequence"]
                    or ack["request_digest"] != grant.request_digest
                    or ack["provider_receipt_digest"] != event["receipt_digest"]
                    or not _check_digest(ack["provider_receipt_digest"])):
                raise WitnessLeaderDenied("provider ACK not bound to physically started grant")
            signature_text = event["provider_ack_signature"]
            if type(signature_text) is not str:
                raise WitnessLeaderDenied("provider ACK signature missing")
            try:
                signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
                if len(signature) != 64 or base64.urlsafe_b64encode(signature).rstrip(b"=").decode() != signature_text:
                    raise ValueError("noncanonical provider signature")
                self._provider_keys[grant.provider_id].verify(
                    signature, ACK_CONTEXT + _canonical(ack))
            except (InvalidSignature, ValueError, TypeError, KeyError) as exc:
                raise WitnessLeaderDenied("provider ACK independently unverifiable") from exc
        elif kind == "UNKNOWN":
            if event != {"kind": kind, "grant_id": grant.grant_id,
                         "effect_id": row["effect_id"],
                         "start_sequence": row["start_sequence"]} or row["state"] != "STARTED":
                raise WitnessLeaderDenied("invalid or duplicate UNKNOWN")
        else:
            raise WitnessLeaderDenied("unsupported leader transition")
        if kind in ("CLAIM", "START") and db.execute(
                "SELECT 1 FROM revocations WHERE scope_digest=?", (row["scope_digest"],)).fetchone():
            raise WitnessLeaderDenied("scope revoked by independent leader")

    def reserve_provider_effect(self, **kwargs: Any) -> bool:
        """Network provider mTLS identity required in server wrapper.

        The START must already exist in this *same* leader transaction log.
        The reservation survives an ambiguous result and can never be replayed.
        """
        if set(kwargs) != _FENCE_FIELDS - {"schema"}:
            raise WitnessLeaderDenied("invalid provider fence attributes")
        if any(type(kwargs.get(name)) is not str for name in (
            "host_id", "provider_id", "provider_instance_id", "effect_id",
            "request_digest", "grant_id", "participant_id", "purpose", "operation",
        )) or type(kwargs.get("epoch")) is not int or type(kwargs.get("claim_sequence")) is not int:
            raise WitnessLeaderDenied("invalid provider fence field types")
        if kwargs["host_id"] != self.config.host_id or kwargs["epoch"] != self.config.epoch:
            raise WitnessLeaderDenied("provider fence host/epoch mismatch")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM grants WHERE grant_id=?", (kwargs["grant_id"],)).fetchone()
            if row is None or row["state"] != "STARTED":
                raise WitnessLeaderDenied("no leader-authorized START")
            grant = ApprovedGrant(**json.loads(row["body"]))
            expected = {
                "host_id": grant.host_id, "epoch": grant.epoch,
                "provider_id": grant.provider_id, "provider_instance_id": grant.provider_instance_id,
                "effect_id": row["effect_id"], "claim_sequence": row["claim_sequence"],
                "request_digest": grant.request_digest, "grant_id": grant.grant_id,
                "participant_id": grant.participant_id, "purpose": grant.purpose,
                "operation": grant.operation,
            }
            now = self._now()
            if (kwargs != expected or type(row["issued_at"]) is not int
                    or type(row["start_deadline"]) is not int
                    or not row["issued_at"] <= now <= row["start_deadline"]
                    or now >= grant.expires_at):
                raise WitnessLeaderDenied("provider fence not bound to current signed START")
            try:
                db.execute("INSERT INTO provider_fences VALUES(?,?,?)",
                           (row["effect_id"], grant.grant_id, row["start_sequence"]))
            except sqlite3.IntegrityError as exc:
                raise WitnessLeaderDenied("provider effect already physically reserved") from exc
            db.commit()
            return True


class _WitnessMTLSHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, UnifiedWitnessHTTPServer)
        der = self.connection.getpeercert(binary_form=True)
        fingerprint = sha256(der).hexdigest() if der else ""
        if self.path == "/v1/allocate":
            allowed = {server.leader.config.host_client_sha256}
        elif self.path == "/v1/reserve-effect":
            allowed = set(server.leader.config.provider_client_sha256.values())
        else:
            self._reply(404, b"")
            return
        if fingerprint not in allowed:
            self._reply(403, b"")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
            self._reply(400, b"")
            return
        content_length = lengths[0]
        if content_length is None or not content_length.isascii() or not content_length.isdecimal():
            self._reply(400, b"")
            return
        size = int(content_length)
        if not 0 < size <= _MAX_BODY:
            self._reply(413, b"")
            return
        self.connection.settimeout(5)
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise WitnessLeaderDenied("short authenticated event")
            if self.path == "/v1/allocate":
                result = server.leader.allocate_event(raw)
            else:
                req = _decode(raw)
                if set(req) != _FENCE_FIELDS | {"challenge"} or req["schema"] != FENCE_REQUEST_SCHEMA:
                    raise WitnessLeaderDenied("invalid physical fence request")
                challenge = req["challenge"]
                if (type(challenge) is not str or len(challenge) != 48
                        or any(ch not in "0123456789abcdef" for ch in challenge)):
                    raise WitnessLeaderDenied("invalid physical fence challenge")
                if server.leader.config.provider_client_sha256.get(req.get("provider_id")) != fingerprint:
                    raise WitnessLeaderDenied("provider certificate not bound to requested provider")
                server.leader.reserve_provider_effect(**{
                    k: v for k, v in req.items() if k not in ("schema", "challenge")
                })
                fence_body = {
                    "schema": FENCE_RESPONSE_SCHEMA,
                    "approved": True,
                    "host_id": req["host_id"],
                    "epoch": req["epoch"],
                    "leader_epoch": server.leader.config.leader_epoch,
                    "provider_id": req["provider_id"],
                    "provider_instance_id": req["provider_instance_id"],
                    "grant_id": req["grant_id"],
                    "effect_id": req["effect_id"],
                    "challenge": challenge,
                    "fence_request_digest": sha256(raw).hexdigest(),
                }
                signature = server.leader._key.sign(
                    FENCE_ACK_CONTEXT + _canonical(fence_body))
                result = _canonical({
                    "schema": FENCE_RESPONSE_SCHEMA,
                    "body": fence_body,
                    "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
                })
        except (WitnessLeaderDenied, ValueError, TypeError, sqlite3.DatabaseError, TimeoutError, OSError):
            self._reply(403, b"")
            return
        self._reply(200, result)

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)
        self.close_connection = True

    def log_message(self, *_: Any) -> None:
        return


class UnifiedWitnessHTTPServer(ThreadingHTTPServer):
    """mTLS wrapper; distinct pinned host and provider certificate identities."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], leader: UnifiedWitnessLeader,
                 context: ssl.SSLContext):
        if type(leader) is not UnifiedWitnessLeader or type(context) is not ssl.SSLContext:
            raise TypeError("exact leader and host-created TLS context required")
        if context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("leader mTLS must require client certificates")
        if not isinstance(address, tuple) or len(address) != 2 or type(address[0]) is not str:
            raise ValueError("exact bind address required")
        self.leader = leader
        super().__init__(address, _WitnessMTLSHandler, bind_and_activate=False)
        try:
            self.socket = context.wrap_socket(self.socket, server_side=True)
            self.server_bind()
            self.server_activate()
        except BaseException:
            self.server_close()
            raise


class UnifiedWitnessMTLSClient:
    """Host-configured authenticated leader transport; no redirects or proxy."""

    __slots__ = ("_host", "_port", "_context", "_timeout", "_leader_key", "_leader_epoch")

    def __init__(self, host: str, port: int, context: ssl.SSLContext,
                 *, leader_public_key: bytes, leader_epoch: int,
                 timeout: float = 3.0):
        if type(host) is not str or not host or type(port) is not int or not 0 < port < 65536:
            raise ValueError("leader endpoint not pinned")
        if type(context) is not ssl.SSLContext or context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise ValueError("leader certificate hostname and trust verification mandatory")
        if timeout <= 0 or timeout > 30:
            raise ValueError("bounded network timeout required")
        if type(leader_public_key) is not bytes or len(leader_public_key) != 32:
            raise ValueError("pinned independent leader Ed25519 root required")
        if type(leader_epoch) is not int or leader_epoch < 1:
            raise ValueError("pinned external leader epoch required")
        self._host, self._port, self._context, self._timeout = host, port, context, timeout
        self._leader_key = Ed25519PublicKey.from_public_bytes(leader_public_key)
        self._leader_epoch = leader_epoch

    def _post(self, endpoint: str, body: bytes) -> bytes:
        conn = http.client.HTTPSConnection(self._host, self._port, context=self._context,
                                           timeout=self._timeout)
        try:
            conn.request("POST", endpoint, body=body, headers={
                "Content-Type": "application/json", "Content-Length": str(len(body)),
            })
            response = conn.getresponse()
            result = response.read(_MAX_BODY + 1)
            if response.status != 200 or not 0 < len(result) <= _MAX_BODY:
                raise WitnessLeaderDenied("exclusive witness did not approve")
            return result
        except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
            raise WitnessLeaderDenied("independent witness unavailable") from exc
        finally:
            conn.close()

    def allocate_event(self, request: bytes) -> bytes:
        _decode(request)
        return self._post("/v1/allocate", request)

    def reserve_provider_effect(self, **kwargs: Any) -> bool:
        if set(kwargs) != _FENCE_FIELDS - {"schema"}:
            raise WitnessLeaderDenied("missing provider fence fields")
        challenge = secrets.token_hex(24)
        request = _canonical({"schema": FENCE_REQUEST_SCHEMA,
                              "challenge": challenge, **kwargs})
        reply = _decode(self._post("/v1/reserve-effect", request))
        if set(reply) != {"schema", "body", "signature"} or reply["schema"] != FENCE_RESPONSE_SCHEMA:
            raise WitnessLeaderDenied("unsigned provider fence response")
        body = reply["body"]
        expected = {
            "schema": FENCE_RESPONSE_SCHEMA,
            "approved": True,
            "host_id": kwargs["host_id"],
            "epoch": kwargs["epoch"],
            "leader_epoch": self._leader_epoch,
            "provider_id": kwargs["provider_id"],
            "provider_instance_id": kwargs["provider_instance_id"],
            "grant_id": kwargs["grant_id"],
            "effect_id": kwargs["effect_id"],
            "challenge": challenge,
            "fence_request_digest": sha256(request).hexdigest(),
        }
        if type(body) is not dict or body != expected or type(reply["signature"]) is not str:
            raise WitnessLeaderDenied("provider fence response not bound to signed request")
        signature_text = reply["signature"]
        try:
            signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
            if len(signature) != 64 or base64.urlsafe_b64encode(signature).rstrip(b"=").decode() != signature_text:
                raise ValueError("noncanonical fence signature")
            self._leader_key.verify(signature, FENCE_ACK_CONTEXT + _canonical(body))
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise WitnessLeaderDenied("provider fence receipt not signed by pinned leader") from exc
        return True
