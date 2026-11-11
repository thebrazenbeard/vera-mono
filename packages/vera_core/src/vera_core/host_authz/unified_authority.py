"""One ordered host authorization decision boundary (source-only candidate).

All claim, consent revocation, effect START, completion and uncertainty events
are recorded in a SINGLE local SQL transaction stream and must first receive
a challenge-bound, independently signed sequence allocated by ONE remote
leader. Different local counters for claims/consent/provider are NOT authority.

This module never invokes a physical provider. It returns a signed START lease
that an independently isolated provider must verify and fence at use time.
The physical provider and its status/reconciliation are separate trust roots.
No synthetic witness or SQLite clone can establish production split-brain
resistance; a genuinely exclusive external leader/monotonic witness is required.
"""

from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .bindings import HostBindingSnapshot, ProviderBinding
from .grants import ApprovedGrant, SignedGrantVerifier
from .service import ProviderAcknowledgement


REQUEST_SCHEMA = "HOST_AUTHZ_UNIFIED_EVENT_REQUEST_V1"
RECEIPT_SCHEMA = "HOST_AUTHZ_UNIFIED_EVENT_RECEIPT_V1"
SIGNATURE_CONTEXT = b"VERA_HOST_AUTHZ_UNIFIED_WITNESS_V1\0"
ACK_CONTEXT = b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0"
KINDS = frozenset({"CLAIM", "REVOKE_SCOPE", "START", "COMPLETE", "UNKNOWN"})
MAX_START_TTL_SECONDS = 30


class UnifiedAuthorityDenied(PermissionError):
    """No fresh, coherent host authorization for this transition."""


class UnifiedAuthorityUnavailable(UnifiedAuthorityDenied):
    """An external witness/ledger is unavailable or cannot reconcile."""


class UnifiedEventWitness(Protocol):
    def allocate_event(self, request: bytes) -> bytes:
        """Return signed receipt with leader-allocated monotonic sequence.

        Must be a physically independent, authenticated, SINGLE leader. It
        must check authorization epoch, event uniqueness and event ordering.
        Never use a model-process in-memory implementation in deployment.
        """


def _canonical(value: Any) -> bytes:
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise UnifiedAuthorityDenied("invalid canonical JSON") from exc


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for name, value in pairs:
        if name in obj:
            raise UnifiedAuthorityDenied("duplicate witness field")
        obj[name] = value
    return obj


def _invalid_constant(_: str) -> Any:
    raise UnifiedAuthorityDenied("nonfinite witness constant")


def _decode_exact(data: bytes, *, size_limit: int = 65536) -> dict[str, Any]:
    if type(data) is not bytes or not data or len(data) > size_limit:
        raise UnifiedAuthorityDenied("invalid witness message size")
    try:
        body = json.loads(data.decode("utf-8", "strict"),
                          object_pairs_hook=_pairs_unique,
                          parse_constant=_invalid_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise UnifiedAuthorityDenied("malformed witness message") from exc
    if type(body) is not dict or _canonical(body) != data:
        raise UnifiedAuthorityDenied("noncanonical witness message")
    return body


def _identifier(value: str, name: str) -> str:
    if (type(value) is not str or not value or len(value) > 256
            or value != value.strip() or any(ord(c) < 32 for c in value)):
        raise UnifiedAuthorityDenied(f"invalid {name}")
    return value


def _sha(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class UnifiedClaimRecord:
    grant_id: str
    effect_id: str
    scope_digest: str
    provider_id: str
    provider_instance_id: str
    request_digest: str
    claim_sequence: int
    start_sequence: int | None
    state: str
    provider_receipt_digest: str | None


@dataclass(frozen=True, slots=True)
class WitnessEventReceipt:
    """Witness-signed event; START receipt is the provider's scoped lease.

    `event` is the exact canonical event preimage covered by the separately
    signed `event_digest`. Transfer BOTH `raw` and `event` to the isolated
    provider. Provider MUST independently validate the event's effect,
    provider, time and scope, and consume effect_id through a one-use fence.
    """

    raw: bytes
    body: Mapping[str, Any]
    event: bytes = b""

    @property
    def sequence(self) -> int:
        return self.body["sequence"]


class UnifiedHostAuthority:
    """Single host-owned transactional decision stream, no raw dispatch RPC.

    Only an OS-isolated host launcher may construct or invoke this object;
    `authenticated_peer_key` must come from verified kernel credentials.
    Revocation linearizes at its event versus START: revocation BEFORE START
    denies START; after START it cannot undo a physical effect, and the event
    remains pending until independently verified provider ACK/reconciliation.
    An issued START has a maximum 30-second physical-use grace interval; a
    later revocation cannot retroactively cancel an already fenced effect.
    """

    def __init__(self, path: str | Path, *, bindings: HostBindingSnapshot,
                 grant_verifier: SignedGrantVerifier,
                 witness: UnifiedEventWitness | None,
                 witness_public_key: bytes,
                 leader_epoch: int,
                 provider_public_keys: Mapping[str, bytes],
                 trusted_clock: Callable[[], int],
                 consent_status: Callable[[ApprovedGrant, int], bool] | None):
        if type(bindings) is not HostBindingSnapshot:
            raise TypeError("host binding snapshot must be exact")
        if type(grant_verifier) is not SignedGrantVerifier:
            raise TypeError("signed grant verifier must be exact")
        if ((grant_verifier.issuer_id, grant_verifier.host_id,
             grant_verifier.epoch) != (bindings.issuer_id, bindings.host_id, bindings.epoch)):
            raise UnifiedAuthorityDenied("issuer/host/epoch mismatch")
        if type(witness_public_key) is not bytes or len(witness_public_key) != 32:
            raise UnifiedAuthorityDenied("witness trust root must be raw Ed25519 key")
        if type(leader_epoch) is not int or not 0 < leader_epoch < (1 << 63):
            raise UnifiedAuthorityDenied("explicit external leader epoch required")
        Ed25519PublicKey.from_public_bytes(witness_public_key)
        if type(provider_public_keys) not in (dict, MappingProxyType):
            raise TypeError("provider receipt key registry must be host-owned mapping")
        if set(provider_public_keys) != set(bindings.providers):
            raise UnifiedAuthorityDenied("provider receipt roots do not match host bindings")
        roots = {}
        for provider_id, key in provider_public_keys.items():
            if type(key) is not bytes or len(key) != 32:
                raise UnifiedAuthorityDenied("provider receipt key must be exact Ed25519 key")
            Ed25519PublicKey.from_public_bytes(key)
            roots[provider_id] = bytes(key)
        if not callable(trusted_clock):
            raise TypeError("trusted host clock is required")
        if consent_status is not None and not callable(consent_status):
            raise TypeError("host consent authority callback must be callable")
        self.bindings = bindings
        self.grant_verifier = grant_verifier
        self._witness = witness
        self._witness_key = bytes(witness_public_key)
        self._leader_epoch = leader_epoch
        self._provider_keys = MappingProxyType(roots)
        self._authority_digest = _sha({
            "host_id": bindings.host_id,
            "issuer_id": bindings.issuer_id,
            "host_epoch": bindings.epoch,
            "leader_epoch": leader_epoch,
            "issuer_public_key": grant_verifier._key.public_bytes(
                Encoding.Raw, PublicFormat.Raw).hex(),
            "witness_public_key": witness_public_key.hex(),
            "provider_public_keys": {k: v.hex() for k, v in sorted(roots.items())},
            "principals": {k: {
                "peer_key": v.peer_key,
                "model_id": v.model_id,
                "adapter_id": v.adapter_id,
                "runtime_id": v.runtime_id,
                "subject_id": v.subject_id,
                "allowed_provider_ids": sorted(v.allowed_provider_ids),
            } for k, v in sorted(bindings.principals.items())},
            "providers": {k: {
                "provider_id": v.provider_id,
                "provider_instance_id": v.provider_instance_id,
                "allowed_operations": sorted(v.allowed_operations),
            } for k, v in sorted(bindings.providers.items())},
        })
        self._clock = trusted_clock
        self._consent_status = consent_status
        self.path = Path(path)
        self._secure_store()
        self._init_db()

    def _secure_store(self) -> None:
        if (os.name != "posix" or not self.path.is_absolute()
                or not hasattr(os, "O_NOFOLLOW")):
            raise UnifiedAuthorityDenied("protected POSIX authority directory required")
        try:
            parent = self.path.parent.lstat()
        except OSError as exc:
            raise UnifiedAuthorityDenied("authority directory unavailable") from exc
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or parent.st_mode & 0o077):
            raise UnifiedAuthorityDenied("authority directory must be private and host-owned")
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
            try:
                observed = os.fstat(fd)
                pathname = self.path.lstat()
                if (not stat.S_ISREG(observed.st_mode) or observed.st_uid != os.geteuid()
                        or observed.st_mode & 0o077 or
                        (observed.st_ino, observed.st_dev) !=
                        (pathname.st_ino, pathname.st_dev)):
                    raise UnifiedAuthorityDenied("authority store is not privately owned")
                self._store_inode = (observed.st_dev, observed.st_ino)
            finally:
                os.close(fd)
        except OSError as exc:
            raise UnifiedAuthorityDenied("authority store unavailable") from exc

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        stat_now = self.path.lstat()
        if ((stat_now.st_dev, stat_now.st_ino) != self._store_inode
                or not stat.S_ISREG(stat_now.st_mode) or stat_now.st_mode & 0o077):
            raise UnifiedAuthorityUnavailable("authority database path was replaced")
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=5000")
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _init_db(self) -> None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS host_authority (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                host_id TEXT NOT NULL, issuer_id TEXT NOT NULL, epoch INTEGER NOT NULL,
                leader_epoch INTEGER NOT NULL,
                authority_digest TEXT NOT NULL,
                last_sequence INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS unified_claims (
                grant_id TEXT PRIMARY KEY, effect_id TEXT NOT NULL UNIQUE,
                grant_json TEXT NOT NULL, scope_digest TEXT NOT NULL,
                provider_id TEXT NOT NULL, provider_instance_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                claim_sequence INTEGER NOT NULL UNIQUE REFERENCES unified_events(sequence),
                start_sequence INTEGER UNIQUE REFERENCES unified_events(sequence),
                state TEXT NOT NULL CHECK(state IN
                    ('CLAIMED','STARTED','COMPLETED','UNKNOWN')),
                provider_receipt_digest TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS unified_revocations (
                scope_digest TEXT PRIMARY KEY,
                sequence INTEGER NOT NULL UNIQUE REFERENCES unified_events(sequence))""")
            db.execute("""CREATE TABLE IF NOT EXISTS unified_events (
                sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                event_digest TEXT NOT NULL UNIQUE, receipt BLOB NOT NULL)""")
            row = db.execute("SELECT * FROM host_authority WHERE singleton=1").fetchone()
            if row is None:
                db.execute("INSERT INTO host_authority VALUES(1,?,?,?,?,?,0)",
                           (self.bindings.host_id, self.bindings.issuer_id,
                            self.bindings.epoch, self._leader_epoch,
                            self._authority_digest))
            elif ((row["host_id"], row["issuer_id"], row["epoch"],
                    row["leader_epoch"], row["authority_digest"]) !=
                  (self.bindings.host_id, self.bindings.issuer_id,
                   self.bindings.epoch, self._leader_epoch,
                   self._authority_digest)):
                raise UnifiedAuthorityDenied("persisted host authority mismatch")
            db.commit()

    def _now(self) -> int:
        try:
            value = self._clock()
        except Exception as exc:
            raise UnifiedAuthorityUnavailable("host clock unavailable") from exc
        if type(value) is not int or value < 0:
            raise UnifiedAuthorityUnavailable("invalid host clock")
        return value

    def _consent_positive(self, grant: ApprovedGrant, now: int) -> bool:
        try:
            return (self._consent_status is not None and
                    self._consent_status(grant, now) is True)
        except Exception:
            return False

    def _attest(self, db: sqlite3.Connection, kind: str,
                event: dict[str, Any]) -> WitnessEventReceipt:
        """Remote event allocation AND signature verification while local lock held.

        A successful remote allocation followed by failed SQLite COMMIT leaves
        a sequence gap. This fail-closes until external operator reconciliation.
        """
        if kind not in KINDS:
            raise UnifiedAuthorityDenied("unknown authorization transition")
        caller_challenge = secrets.token_hex(24)
        event_digest = _sha(event)
        request = {
            "schema": REQUEST_SCHEMA, "host_id": self.bindings.host_id,
            "issuer_id": self.bindings.issuer_id, "epoch": self.bindings.epoch,
            "leader_epoch": self._leader_epoch,
            "challenge": caller_challenge, "kind": kind,
            "event_digest": event_digest, "event": event,
        }
        attestor = getattr(self._witness, "allocate_event", None)
        if not callable(attestor):
            raise UnifiedAuthorityUnavailable("external exclusive authority unavailable")
        try:
            response = attestor(_canonical(request))
            parsed = _decode_exact(response)
            if set(parsed) != {"schema", "body", "signature"}:
                raise UnifiedAuthorityDenied("invalid witness envelope")
            if parsed["schema"] != RECEIPT_SCHEMA or type(parsed["body"]) is not dict:
                raise UnifiedAuthorityDenied("wrong witness receipt schema")
            body = parsed["body"]
            if set(body) != {"host_id", "issuer_id", "epoch", "leader_epoch", "challenge",
                             "kind", "event_digest", "sequence", "approved"}:
                raise UnifiedAuthorityDenied("invalid witness receipt fields")
            for field in ("host_id", "issuer_id", "epoch", "leader_epoch", "challenge",
                          "kind", "event_digest"):
                if body[field] != request[field] or type(body[field]) is not type(request[field]):
                    raise UnifiedAuthorityDenied("witness receipt does not bind request")
            if body["approved"] is not True or type(body["sequence"]) is not int:
                raise UnifiedAuthorityDenied("no signed witness approval")
            sig_text = parsed["signature"]
            if type(sig_text) is not str:
                raise UnifiedAuthorityDenied("invalid witness signature encoding")
            sig = base64.urlsafe_b64decode(sig_text + "=" * ((-len(sig_text)) % 4))
            if (len(sig) != 64 or base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
                    != sig_text):
                raise UnifiedAuthorityDenied("noncanonical witness signature")
            Ed25519PublicKey.from_public_bytes(self._witness_key).verify(
                sig, SIGNATURE_CONTEXT + _canonical(body)
            )
            row = db.execute("SELECT last_sequence FROM host_authority WHERE singleton=1").fetchone()
            if row is None or body["sequence"] != int(row["last_sequence"]) + 1:
                raise UnifiedAuthorityUnavailable("witness order diverged; reconciliation required")
            db.execute("INSERT INTO unified_events VALUES(?,?,?,?)",
                       (body["sequence"], kind, event_digest, response))
            db.execute("UPDATE host_authority SET last_sequence=? WHERE singleton=1",
                       (body["sequence"],))
            return WitnessEventReceipt(response, MappingProxyType(dict(body)),
                                       _canonical(event))
        except UnifiedAuthorityDenied:
            raise
        except (InvalidSignature, binascii.Error, ValueError, TypeError, OSError) as exc:
            raise UnifiedAuthorityUnavailable("witness response not trusted") from exc

    @staticmethod
    def _claim_row(row: sqlite3.Row) -> UnifiedClaimRecord:
        return UnifiedClaimRecord(
            row["grant_id"], row["effect_id"], row["scope_digest"],
            row["provider_id"], row["provider_instance_id"],
            row["request_digest"], row["claim_sequence"],
            row["start_sequence"], row["state"], row["provider_receipt_digest"],
        )

    def read(self, grant_id: str) -> UnifiedClaimRecord | None:
        grant_id = _identifier(grant_id, "grant_id")
        with self._db() as db:
            row = db.execute("SELECT * FROM unified_claims WHERE grant_id=?", (grant_id,)).fetchone()
        return self._claim_row(row) if row else None

    def claim(self, signed_grant: bytes, authenticated_peer_key: str,
              request_payload: Any) -> UnifiedClaimRecord:
        _identifier(authenticated_peer_key, "authenticated peer")
        try:
            principal = self.bindings.principal_for_peer(authenticated_peer_key)
            grant = self.grant_verifier.verify(signed_grant)
            provider: ProviderBinding = self.bindings.provider_for(
                principal, grant.provider_id, grant.operation)
        except Exception as exc:
            raise UnifiedAuthorityDenied("grant or model is not authorized") from exc
        expected = {"peer_key": principal.peer_key, "model_id": principal.model_id,
                    "adapter_id": principal.adapter_id, "runtime_id": principal.runtime_id,
                    "subject_id": principal.subject_id,
                    "provider_instance_id": provider.provider_instance_id}
        if any(getattr(grant, field) != value for field, value in expected.items()):
            raise UnifiedAuthorityDenied("grant does not bind authenticated host principal")
        digest = _sha(request_payload)
        if digest != grant.request_digest:
            raise UnifiedAuthorityDenied("signed grant does not bind request payload")
        now = self._now()
        if not self._consent_positive(grant, now):
            raise UnifiedAuthorityDenied("participant consent not positively established")
        scope = {field: getattr(grant, field) for field in (
            "participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
            "subject_id", "host_id", "provider_id", "provider_instance_id")}
        scope_digest = _sha(scope)
        effect_id = _sha({"schema": "HOST_AUTHZ_UNIFIED_EFFECT_V1",
                          "grant_id": grant.grant_id, "issuer_id": grant.issuer_id,
                          "host_id": grant.host_id, "epoch": grant.epoch,
                          "provider_instance_id": grant.provider_instance_id,
                          "request_digest": grant.request_digest})
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM unified_revocations WHERE scope_digest=?",
                          (scope_digest,)).fetchone() is not None:
                raise UnifiedAuthorityDenied("participant scope revoked")
            if db.execute("SELECT 1 FROM unified_claims WHERE grant_id=?",
                          (grant.grant_id,)).fetchone() is not None:
                raise UnifiedAuthorityDenied("grant already claimed")
            event = {"kind": "CLAIM", "grant_id": grant.grant_id,
                     "effect_id": effect_id, "scope_digest": scope_digest,
                     "provider_instance_id": provider.provider_instance_id,
                     "request_digest": digest}
            receipt = self._attest(db, "CLAIM", event)
            db.execute("""INSERT INTO unified_claims VALUES(
                ?,?,?,?,?,?,?,?,NULL,'CLAIMED',NULL)""",
                (grant.grant_id, effect_id, _canonical(grant.canonical_body()).decode(),
                 scope_digest, grant.provider_id, provider.provider_instance_id,
                 digest, receipt.sequence))
            db.commit()
        result = self.read(grant.grant_id)
        assert result is not None
        return result

    def revoke_scope(self, grant: ApprovedGrant) -> WitnessEventReceipt:
        """Privileged consent controller only; NEVER expose as a model IPC RPC."""
        if type(grant) is not ApprovedGrant:
            raise UnifiedAuthorityDenied("only canonical host grant scope is allowed")
        if (grant.host_id, grant.issuer_id, grant.epoch) != (
            self.bindings.host_id, self.bindings.issuer_id, self.bindings.epoch):
            raise UnifiedAuthorityDenied("wrong authority for consent scope revoke")
        scope_digest = _sha({field: getattr(grant, field) for field in (
            "participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
            "subject_id", "host_id", "provider_id", "provider_instance_id")})
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM unified_revocations WHERE scope_digest=?",
                          (scope_digest,)).fetchone() is not None:
                raise UnifiedAuthorityDenied("consent scope already revoked")
            event = {"kind": "REVOKE_SCOPE", "grant_id": grant.grant_id,
                     "scope_digest": scope_digest}
            receipt = self._attest(db, "REVOKE_SCOPE", event)
            db.execute("INSERT INTO unified_revocations VALUES(?,?)",
                       (scope_digest, receipt.sequence))
            db.commit()
            return receipt

    def start(self, grant_id: str) -> WitnessEventReceipt:
        """Single physical effect START linearization; returns provider lease.

        The provider's independent effect fence must consume the exact START
        receipt. Revocation after START cannot retroactively cancel an effect.
        """
        grant_id = _identifier(grant_id, "grant_id")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM unified_claims WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None or row["state"] != "CLAIMED":
                raise UnifiedAuthorityDenied("effect is not an unused claim")
            if db.execute("SELECT 1 FROM unified_revocations WHERE scope_digest=?",
                          (row["scope_digest"],)).fetchone() is not None:
                raise UnifiedAuthorityDenied("consent revoked before effect start")
            grant = ApprovedGrant(**json.loads(row["grant_json"]))
            now = self._now()
            if not grant.not_before <= now < grant.expires_at:
                raise UnifiedAuthorityDenied("grant expired before effect start")
            if not self._consent_positive(grant, now):
                raise UnifiedAuthorityDenied("consent status unknown at START")
            event = {"kind": "START", "grant_id": grant_id,
                     "effect_id": row["effect_id"],
                     "scope_digest": row["scope_digest"],
                     "peer_key": grant.peer_key,
                     "model_id": grant.model_id,
                     "adapter_id": grant.adapter_id,
                     "runtime_id": grant.runtime_id,
                     "subject_id": grant.subject_id,
                     "participant_id": grant.participant_id,
                     "purpose": grant.purpose,
                     "host_id": grant.host_id,
                     "epoch": grant.epoch,
                     "operation": grant.operation,
                     "claim_sequence": row["claim_sequence"],
                     "provider_id": row["provider_id"],
                     "provider_instance_id": row["provider_instance_id"],
                     "request_digest": row["request_digest"],
                     "issued_at": now,
                     "start_deadline": min(now + MAX_START_TTL_SECONDS,
                                           grant.expires_at - 1),
                     "expires_at": grant.expires_at,
                     "not_before": grant.not_before}
            receipt = self._attest(db, "START", event)
            db.execute("UPDATE unified_claims SET state='STARTED',start_sequence=? WHERE grant_id=?",
                       (receipt.sequence, grant_id))
            db.commit()
            return receipt

    def complete(self, grant_id: str, acknowledgement: ProviderAcknowledgement) -> UnifiedClaimRecord:
        grant_id = _identifier(grant_id, "grant_id")
        if type(acknowledgement) is not ProviderAcknowledgement:
            raise UnifiedAuthorityDenied("provider ACK must be exact signed record")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM unified_claims WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None or row["state"] != "STARTED":
                raise UnifiedAuthorityDenied("only pending effects can be completed")
            if (acknowledgement.effect_id != row["effect_id"] or
                    acknowledgement.provider_id != row["provider_id"] or
                    acknowledgement.provider_instance_id != row["provider_instance_id"] or
                    acknowledgement.request_digest != row["request_digest"] or
                    acknowledgement.claim_sequence != row["claim_sequence"]):
                raise UnifiedAuthorityDenied("provider ACK did not bind exact effect")
            key = self._provider_keys[row["provider_id"]]
            try:
                Ed25519PublicKey.from_public_bytes(key).verify(
                    acknowledgement.receipt_signature,
                    ACK_CONTEXT + _canonical(acknowledgement.signed_body()))
            except (InvalidSignature, ValueError, TypeError) as exc:
                raise UnifiedAuthorityDenied("provider ACK signature not trustworthy") from exc
            event = {"kind": "COMPLETE", "grant_id": grant_id,
                     "effect_id": row["effect_id"],
                     "start_sequence": row["start_sequence"],
                     "receipt_digest": acknowledgement.provider_receipt_digest,
                     "provider_ack_body": acknowledgement.signed_body(),
                     "provider_ack_signature": base64.urlsafe_b64encode(
                         acknowledgement.receipt_signature).rstrip(b"=").decode("ascii")}
            self._attest(db, "COMPLETE", event)
            db.execute("UPDATE unified_claims SET state='COMPLETED',provider_receipt_digest=? WHERE grant_id=?",
                       (acknowledgement.provider_receipt_digest, grant_id))
            db.commit()
        result = self.read(grant_id)
        assert result is not None
        return result

    def mark_unknown(self, grant_id: str) -> UnifiedClaimRecord:
        grant_id = _identifier(grant_id, "grant_id")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM unified_claims WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None or row["state"] != "STARTED":
                raise UnifiedAuthorityDenied("only started effects have ambiguous provider outcome")
            event = {"kind": "UNKNOWN", "grant_id": grant_id,
                     "effect_id": row["effect_id"],
                     "start_sequence": row["start_sequence"]}
            self._attest(db, "UNKNOWN", event)
            db.execute("UPDATE unified_claims SET state='UNKNOWN' WHERE grant_id=?",
                       (grant_id,))
            db.commit()
        result = self.read(grant_id)
        assert result is not None
        return result


def verify_provider_start_lease(raw: bytes, *, event: bytes,
                                witness_public_key: bytes,
                                expected_host_id: str, expected_epoch: int,
                                expected_leader_epoch: int,
                                expected_effect_id: str,
                                expected_provider_id: str,
                                expected_provider_instance_id: str,
                                expected_request_digest: str,
                                provider_now: int) -> WitnessEventReceipt:
    """Validate START receipt and semantic payload (NOT a one-use fence).

    The expected identifiers MUST be independent provider provisioning, not
    model-supplied arguments. The provider must additionally durably fence
    effect_id and sequence before its physical side effect.
    """
    envelope = _decode_exact(raw)
    start_event = _decode_exact(event)
    if set(start_event) != {
        "kind", "grant_id", "effect_id", "scope_digest", "claim_sequence",
        "provider_id", "provider_instance_id", "request_digest", "expires_at",
        "not_before", "peer_key", "model_id", "adapter_id", "runtime_id",
        "subject_id", "participant_id", "purpose", "host_id", "epoch",
        "operation", "issued_at", "start_deadline",
    } or start_event["kind"] != "START":
        raise UnifiedAuthorityDenied("provider START event is not exact")
    expected_scope = {field: start_event[field] for field in (
        "participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
        "subject_id", "host_id", "provider_id", "provider_instance_id")}
    if (start_event["host_id"] != expected_host_id or
            type(start_event["epoch"]) is not int or
            start_event["epoch"] != expected_epoch or
            start_event["scope_digest"] != _sha(expected_scope)):
        raise UnifiedAuthorityDenied("provider START scope or epoch invalid")
    for field, expected in (
        ("effect_id", expected_effect_id),
        ("provider_id", expected_provider_id),
        ("provider_instance_id", expected_provider_instance_id),
        ("request_digest", expected_request_digest),
    ):
        if type(start_event[field]) is not str or start_event[field] != expected:
            raise UnifiedAuthorityDenied("provider START does not match provisioned effect")
    if (type(provider_now) is not int
            or type(start_event["not_before"]) is not int
            or type(start_event["expires_at"]) is not int
            or type(start_event["issued_at"]) is not int
            or type(start_event["start_deadline"]) is not int
            or not start_event["not_before"] <= start_event["issued_at"] < start_event["expires_at"]
            or not start_event["issued_at"] <= start_event["start_deadline"] < start_event["expires_at"]
            or start_event["start_deadline"] - start_event["issued_at"] > MAX_START_TTL_SECONDS
            or not start_event["issued_at"] <= provider_now <= start_event["start_deadline"]
            or provider_now >= start_event["expires_at"]):
        raise UnifiedAuthorityDenied("provider START lease time invalid")
    if (type(start_event["claim_sequence"]) is not int
            or start_event["claim_sequence"] < 1):
        raise UnifiedAuthorityDenied("provider START sequence invalid")
    if type(witness_public_key) is not bytes or len(witness_public_key) != 32:
        raise UnifiedAuthorityDenied("provider has no pinned witness trust root")
    if set(envelope) != {"schema", "body", "signature"} or envelope["schema"] != RECEIPT_SCHEMA:
        raise UnifiedAuthorityDenied("provider cannot trust witness lease schema")
    body = envelope["body"]
    if type(body) is not dict or body.get("kind") != "START" or body.get("approved") is not True:
        raise UnifiedAuthorityDenied("provider lease is not a positive effect START")
    if (body.get("host_id") != expected_host_id or
            body.get("epoch") != expected_epoch or
            body.get("leader_epoch") != expected_leader_epoch or
            body.get("event_digest") != _sha(start_event)):
        raise UnifiedAuthorityDenied("provider lease does not match exact expected effect")
    sig_txt = envelope["signature"]
    if type(sig_txt) is not str:
        raise UnifiedAuthorityDenied("provider lease has no signature")
    try:
        signature = base64.urlsafe_b64decode(sig_txt + "=" * ((-len(sig_txt)) % 4))
        if (len(signature) != 64 or
                base64.urlsafe_b64encode(signature).rstrip(b"=").decode() != sig_txt):
            raise UnifiedAuthorityDenied("invalid lease signature format")
        Ed25519PublicKey.from_public_bytes(witness_public_key).verify(
            signature, SIGNATURE_CONTEXT + _canonical(body))
    except (InvalidSignature, ValueError, binascii.Error) as exc:
        raise UnifiedAuthorityDenied("provider lease signature failed") from exc
    return WitnessEventReceipt(raw, MappingProxyType(dict(body)), event)
