"""A provider-owned execution/fence boundary with signed host admission.

This reference module is intentionally not a model-visible tool or a device
installer. A dedicated, OS-isolated provider process must own the code, effect
store, provider credentials, and Ed25519 receipt key. The host authorization
service can send a signed *command*, but cannot mint the provider's ACK.

The witness must be a genuinely external exclusive/monotonic trust domain:
injecting an always-True fake or cloning its state together with this SQLite
store does NOT prevent cross-host split brain. Likewise, a callback running in
the same process as hostile model code does NOT establish immutable custody.

For known/unknown provider outcomes, duplicates are always denied. A crash
after an effect and before acknowledgement leaves a durable RESERVED record;
it must be reconciled through authoritative provider status, never retried.
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
import re
import sqlite3
import stat
from typing import Any, Callable, Iterator, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .service import ProviderAcknowledgement, ProviderDispatch
from .unified_authority import (
    UnifiedAuthorityDenied,
    WitnessEventReceipt,
    verify_provider_start_lease,
)


COMMAND_SCHEMA = "HOST_AUTHZ_PROVIDER_COMMAND_V1"
COMMAND_CONTEXT = b"VERA_HOST_AUTHZ_PROVIDER_COMMAND_V1\0"
ACK_CONTEXT = b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0"
_EXPECTED_FIELDS = frozenset({
    "effect_id", "grant_id", "provider_id", "provider_instance_id",
    "operation", "request_digest", "claim_sequence", "participant_id",
    "purpose", "request_payload",
})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MAX_SIGNED_COMMAND = 131_072


class ProviderCustodyDenied(PermissionError):
    """A command, witness, fence or provider operation was not authoritative."""


class EffectWitness(Protocol):
    def reserve_provider_effect(
        self, *, host_id: str, epoch: int, provider_id: str,
        provider_instance_id: str, effect_id: str, claim_sequence: int,
        request_digest: str, grant_id: str, participant_id: str,
        purpose: str, operation: str,
    ) -> bool:
        """Atomically fence this effect across all hosts in external trust domain."""


def _id(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value or len(value) > 256:
        raise ProviderCustodyDenied(f"invalid {label}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ProviderCustodyDenied(f"invalid control character in {label}")
    return value


def _request_digest(value: Any) -> str:
    try:
        return sha256(canonical_json_bytes(value)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ProviderCustodyDenied("request is not canonical JSON") from exc


def _host_owned_fence_path(path: Path) -> None:
    """Reject mutable/unowned state directories, symlinks and unsafe file modes.

    Only a dedicated provider OS account may own this directory. A model that
    shares that account can still change the database; that deployment is NOT
    permitted by this module's trust contract.
    """
    if os.name != "posix" or not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise ProviderCustodyDenied("provider fence requires absolute POSIX host path")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise ProviderCustodyDenied("provider state directory unprovisioned") from exc
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or parent.st_mode & 0o077
    ):
        raise ProviderCustodyDenied("provider state directory not exclusively host-owned")
    try:
        existing = path.lstat()
    except FileNotFoundError:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            os.close(descriptor)
        except OSError as exc:
            raise ProviderCustodyDenied("cannot safely provision provider fence file") from exc
    else:
        if (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.geteuid()
            or existing.st_mode & 0o077
        ):
            raise ProviderCustodyDenied("provider fence file is mutable or unowned")


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for key, value in pairs:
        if key in body:
            raise ProviderCustodyDenied("duplicate command JSON field")
        body[key] = value
    return body


def _invalid_json_constant(value: str) -> Any:
    raise ProviderCustodyDenied("invalid JSON constant")


def _canonical_decode(data: bytes) -> dict[str, Any]:
    if type(data) is not bytes or len(data) > _MAX_SIGNED_COMMAND or not data:
        raise ProviderCustodyDenied("invalid signed command size")
    try:
        parsed = json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=_strict_pairs,
            parse_constant=_invalid_json_constant,
        )
        if type(parsed) is not dict or canonical_json_bytes(parsed) != data:
            raise ProviderCustodyDenied("noncanonical command JSON")
        return parsed
    except (UnicodeDecodeError, ValueError, OverflowError, RecursionError, TypeError) as exc:
        raise ProviderCustodyDenied("invalid signed command encoding") from exc


def _dispatch_body(command: ProviderDispatch) -> dict[str, Any]:
    if type(command) is not ProviderDispatch:
        raise ProviderCustodyDenied("noncanonical provider instruction")
    for key in _EXPECTED_FIELDS - {"claim_sequence", "request_payload", "request_digest"}:
        _id(getattr(command, key), key)
    if type(command.claim_sequence) is not int or command.claim_sequence <= 0:
        raise ProviderCustodyDenied("invalid claim sequence")
    if type(command.request_digest) is not str or _DIGEST.fullmatch(command.request_digest) is None:
        raise ProviderCustodyDenied("invalid request digest")
    if _request_digest(command.request_payload) != command.request_digest:
        raise ProviderCustodyDenied("provider request payload digest mismatch")
    # Deep canonical copy severs aliasing with mutable caller payload dicts.
    return {
        key: (
            json.loads(canonical_json_bytes(command.request_payload))
            if key == "request_payload" else getattr(command, key)
        )
        for key in sorted(_EXPECTED_FIELDS)
    }


class HostDispatchSigner:
    """Host-owned command signer; MUST NOT be imported/held by a model process."""

    __slots__ = ("_key", "host_id", "epoch", "public_key_bytes", "_trusted_clock", "_ttl")

    def __init__(
        self, signing_key: Ed25519PrivateKey, *, host_id: str, epoch: int,
        trusted_clock: Callable[[], int], ttl_seconds: int = 30,
    ):
        if not isinstance(signing_key, Ed25519PrivateKey):
            raise TypeError("host signer must be Ed25519PrivateKey")
        self.host_id = _id(host_id, "host id")
        if type(epoch) is not int or epoch <= 0:
            raise ProviderCustodyDenied("invalid host authority epoch")
        self.epoch = epoch
        if not callable(trusted_clock):
            raise ProviderCustodyDenied("trusted command clock required")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 60:
            raise ProviderCustodyDenied("signed command TTL must be 1–60 seconds")
        self._key = signing_key
        self._trusted_clock = trusted_clock
        self._ttl = ttl_seconds
        self.public_key_bytes = signing_key.public_key().public_bytes_raw()

    def sign(self, command: ProviderDispatch) -> bytes:
        now = self._now()
        body = {
            "host_id": self.host_id,
            "epoch": self.epoch,
            "not_before": now,
            "expires_at": now + self._ttl,
            "dispatch": _dispatch_body(command),
        }
        signature = self._key.sign(COMMAND_CONTEXT + canonical_json_bytes(body))
        return canonical_json_bytes({
            "schema": COMMAND_SCHEMA,
            "body": body,
            "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
        })

    def _now(self) -> int:
        try:
            now = self._trusted_clock()
        except Exception as exc:
            raise ProviderCustodyDenied("trusted command clock unavailable") from exc
        if type(now) is not int or now < 0:
            raise ProviderCustodyDenied("trusted command clock invalid")
        return now


@dataclass(frozen=True, slots=True)
class ProviderEffectRecord:
    effect_id: str
    command_digest: str
    state: str
    claim_sequence: int
    provider_result_digest: str | None


class ProviderCustodyWorker:
    """Run only inside a separately privileged provider *process*.

    The worker owns effect state, provider signing key and physical transport.
    The host/modeled client is trusted only for correctly signed command bytes;
    the worker independently verifies authority, one-use witness and fence.
    """

    def __init__(
        self, *, state_path: str | Path, provider_id: str,
        provider_instance_id: str, host_id: str, epoch: int,
        host_command_public_key: bytes, receipt_signer: Ed25519PrivateKey,
        witness_start_public_key: bytes, witness_leader_epoch: int,
        effect_witness: EffectWitness | None,
        execute: Callable[[ProviderDispatch], Any],
        trusted_clock: Callable[[], int],
    ) -> None:
        self.provider_id = _id(provider_id, "provider id")
        self.provider_instance_id = _id(provider_instance_id, "provider instance")
        self.host_id = _id(host_id, "host id")
        if type(epoch) is not int or epoch <= 0:
            raise ProviderCustodyDenied("invalid host authority epoch")
        self.epoch = epoch
        if type(host_command_public_key) is not bytes or len(host_command_public_key) != 32:
            raise ProviderCustodyDenied("host public key must be exact Ed25519 bytes")
        self._host_key = Ed25519PublicKey.from_public_bytes(host_command_public_key)
        if type(witness_start_public_key) is not bytes or len(witness_start_public_key) != 32:
            raise ProviderCustodyDenied("provider witness START key must be pinned Ed25519 bytes")
        self._witness_start_public_key = witness_start_public_key
        if type(witness_leader_epoch) is not int or not 0 < witness_leader_epoch < (1 << 63):
            raise ProviderCustodyDenied("provider witness leader epoch must be pinned")
        self._witness_leader_epoch = witness_leader_epoch
        if not isinstance(receipt_signer, Ed25519PrivateKey):
            raise TypeError("provider must own Ed25519 receipt signer")
        self._receipt_key = receipt_signer
        self.receipt_public_key_bytes = receipt_signer.public_key().public_bytes_raw()
        self._effect_witness = effect_witness
        if not callable(trusted_clock):
            raise ProviderCustodyDenied("provider trusted clock unavailable")
        self._trusted_clock = trusted_clock
        if not callable(execute):
            raise TypeError("physical transport must be host-owned callable")
        self._execute = execute
        self.path = Path(state_path)
        _host_owned_fence_path(self.path)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS provider_authority (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                host_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                provider_id TEXT NOT NULL,
                provider_instance_id TEXT NOT NULL,
                witness_leader_epoch INTEGER NOT NULL,
                witness_start_public_key BLOB NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS provider_effects (
                effect_id TEXT PRIMARY KEY,
                command_digest TEXT NOT NULL,
                claim_sequence INTEGER NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('RESERVED', 'AMBIGUOUS', 'COMMITTED')),
                provider_result_digest TEXT
            )""")
            expected = (self.host_id, self.epoch, self.provider_id, self.provider_instance_id,
                        self._witness_leader_epoch, self._witness_start_public_key)
            bound = db.execute(
                "SELECT host_id,epoch,provider_id,provider_instance_id,"
                "witness_leader_epoch,witness_start_public_key "
                "FROM provider_authority WHERE singleton=1"
            ).fetchone()
            if bound is None:
                db.execute("INSERT INTO provider_authority VALUES(1,?,?,?,?,?,?)", expected)
            elif tuple(bound) != expected:
                raise ProviderCustodyDenied("provider effect store authority binding changed")
            db.commit()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _decode_signed_command(self, signed_command: bytes) -> tuple[ProviderDispatch, str]:
        message = _canonical_decode(signed_command)
        if set(message) != {"schema", "body", "signature"} or message["schema"] != COMMAND_SCHEMA:
            raise ProviderCustodyDenied("unknown provider command envelope")
        body, encoded_signature = message["body"], message["signature"]
        if type(body) is not dict or set(body) != {"host_id", "epoch", "not_before", "expires_at", "dispatch"}:
            raise ProviderCustodyDenied("invalid provider command body")
        if body["host_id"] != self.host_id or type(body["epoch"]) is not int or body["epoch"] != self.epoch:
            raise ProviderCustodyDenied("provider command host/epoch mismatch")
        if (
            type(body["not_before"]) is not int
            or type(body["expires_at"]) is not int
            or body["not_before"] < 0
            or not 1 <= body["expires_at"] - body["not_before"] <= 60
        ):
            raise ProviderCustodyDenied("invalid signed provider command validity interval")
        if type(encoded_signature) is not str or len(encoded_signature) != 86:
            raise ProviderCustodyDenied("invalid provider command signature")
        try:
            signature = base64.urlsafe_b64decode(encoded_signature + "==")
            if base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") != encoded_signature:
                raise ProviderCustodyDenied("noncanonical provider signature")
            self._host_key.verify(signature, COMMAND_CONTEXT + canonical_json_bytes(body))
        except (InvalidSignature, binascii.Error, ValueError) as exc:
            raise ProviderCustodyDenied("untrusted provider command signature") from exc
        try:
            now = self._trusted_clock()
        except Exception as exc:
            raise ProviderCustodyDenied("provider clock unavailable") from exc
        if type(now) is not int or now < body["not_before"] or now >= body["expires_at"]:
            raise ProviderCustodyDenied("provider command no longer valid")
        dispatch = body["dispatch"]
        if type(dispatch) is not dict or set(dispatch) != _EXPECTED_FIELDS:
            raise ProviderCustodyDenied("unknown provider command dispatch fields")
        try:
            command = ProviderDispatch(**dispatch)
        except TypeError as exc:
            raise ProviderCustodyDenied("invalid provider command field types") from exc
        canonical_command = _dispatch_body(command)
        if canonical_command != dispatch:
            raise ProviderCustodyDenied("noncanonical signed provider dispatch")
        if command.provider_id != self.provider_id or command.provider_instance_id != self.provider_instance_id:
            raise ProviderCustodyDenied("provider instance authorization mismatch")
        command_digest = sha256(canonical_json_bytes(body)).hexdigest()
        return command, command_digest

    def status(self, effect_id: str) -> str | None:
        """Host-internal reconciliation observation; do not publish as unauthenticated RPC."""
        effect_id = _id(effect_id, "effect id")
        with self._db() as db:
            row = db.execute("SELECT state FROM provider_effects WHERE effect_id=?", (effect_id,)).fetchone()
        return str(row["state"]) if row is not None else None

    def dispatch(
        self, signed_command: bytes, *, start_lease: WitnessEventReceipt | None = None,
    ) -> ProviderAcknowledgement:
        command, command_digest = self._decode_signed_command(signed_command)
        # A host signature authenticates routing but never substitutes for the
        # witness's atomic, consent-authoritative START decision. Both distinct
        # trust roots must agree before the provider can touch a physical effect.
        if type(start_lease) is not WitnessEventReceipt:
            raise ProviderCustodyDenied("witness START lease required before physical effect")
        try:
            now = self._trusted_clock()
        except Exception as exc:
            raise ProviderCustodyDenied("provider START clock unavailable") from exc
        if type(now) is not int:
            raise ProviderCustodyDenied("provider START clock invalid")
        try:
            verified = verify_provider_start_lease(
                start_lease.raw,
                event=start_lease.event,
                witness_public_key=self._witness_start_public_key,
                expected_host_id=self.host_id,
                expected_epoch=self.epoch,
                expected_leader_epoch=self._witness_leader_epoch,
                expected_effect_id=command.effect_id,
                expected_provider_id=self.provider_id,
                expected_provider_instance_id=self.provider_instance_id,
                expected_request_digest=command.request_digest,
                provider_now=now,
            )
            # These fields are authenticated by the witness signature over
            # the event digest, and are independently compared to the signed
            # host dispatch. Never trust the caller-provided .body property.
            lease_event = _canonical_decode(verified.event)
        except (UnifiedAuthorityDenied, ProviderCustodyDenied, ValueError, TypeError) as exc:
            raise ProviderCustodyDenied("untrusted or inconsistent witness START lease") from exc
        # The grant's potentially long expiry is NOT an execution lease: a
        # paused provider must not perform its effect minutes/hours after
        # consent-authoritative START. The witness signs this narrow window.
        issued_at = lease_event.get("issued_at")
        start_deadline = lease_event.get("start_deadline")
        expires_at = lease_event.get("expires_at")
        if (type(issued_at) is not int or type(start_deadline) is not int
                or type(expires_at) is not int
                or issued_at < 0
                or not issued_at <= now <= start_deadline < expires_at
                or start_deadline - issued_at > 30):
            raise ProviderCustodyDenied("witness START execution deadline invalid or elapsed")
        for field, expected in (
            ("grant_id", command.grant_id),
            ("claim_sequence", command.claim_sequence),
            ("participant_id", command.participant_id),
            ("purpose", command.purpose),
            ("operation", command.operation),
        ):
            if type(lease_event.get(field)) is not type(expected) or lease_event[field] != expected:
                raise ProviderCustodyDenied(f"witness START {field} does not match host dispatch")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT state FROM provider_effects WHERE effect_id=?", (command.effect_id,)
            ).fetchone()
            if existing is not None:
                raise ProviderCustodyDenied("provider effect already reserved; no retry")
            witness = getattr(self._effect_witness, "reserve_provider_effect", None)
            if not callable(witness):
                raise ProviderCustodyDenied("external effect witness unavailable")
            try:
                verdict = witness(
                    host_id=self.host_id,
                    epoch=self.epoch,
                    provider_id=self.provider_id,
                    provider_instance_id=self.provider_instance_id,
                    effect_id=command.effect_id,
                    claim_sequence=command.claim_sequence,
                    request_digest=command.request_digest,
                    grant_id=command.grant_id,
                    participant_id=command.participant_id,
                    purpose=command.purpose,
                    operation=command.operation,
                )
            except Exception as exc:
                raise ProviderCustodyDenied("external effect witness failed") from exc
            if verdict is not True:
                raise ProviderCustodyDenied("external effect witness denied")
            db.execute(
                "INSERT INTO provider_effects VALUES(?,?,?,'RESERVED',NULL)",
                (command.effect_id, command_digest, command.claim_sequence),
            )
            db.commit()

        try:
            # Recheck AFTER the potentially blocking external fence reservation:
            # a pause there cannot turn a formerly valid START into permission
            # for a late physical call. The RESERVED fence remains non-replayable
            # when the lease expires during admission.
            try:
                at_physical_boundary = self._trusted_clock()
            except Exception as exc:
                raise ProviderCustodyDenied("provider clock unavailable at physical boundary") from exc
            if (type(at_physical_boundary) is not int
                    or not issued_at <= at_physical_boundary <= start_deadline
                    or at_physical_boundary >= expires_at):
                raise ProviderCustodyDenied("witness START elapsed before provider physical call")
            result = self._execute(command)
            provider_digest = _request_digest(result)
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT command_digest, state FROM provider_effects WHERE effect_id=?",
                    (command.effect_id,),
                ).fetchone()
                if row is None or row["state"] != "RESERVED" or row["command_digest"] != command_digest:
                    raise ProviderCustodyDenied("provider fence changed during execution")
                db.execute(
                    "UPDATE provider_effects SET state='COMMITTED', provider_result_digest=? WHERE effect_id=?",
                    (provider_digest, command.effect_id),
                )
                db.commit()
        except BaseException as exc:
            # May already have performed a non-transactional physical effect.
            # Keep the one-use reservation; never roll back and re-execute.
            try:
                with self._db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute(
                        "UPDATE provider_effects SET state='AMBIGUOUS' WHERE effect_id=? AND state='RESERVED'",
                        (command.effect_id,),
                    )
                    db.commit()
            except BaseException:
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise ProviderCustodyDenied("provider outcome ambiguous; reconcile before any new effect") from exc

        acknowledgement = ProviderAcknowledgement(
            effect_id=command.effect_id,
            provider_id=self.provider_id,
            provider_instance_id=self.provider_instance_id,
            claim_sequence=command.claim_sequence,
            request_digest=command.request_digest,
            provider_receipt_digest=provider_digest,
            receipt_signature=b"",
        )
        signature = self._receipt_key.sign(ACK_CONTEXT + canonical_json_bytes(acknowledgement.signed_body()))
        return ProviderAcknowledgement(
            effect_id=acknowledgement.effect_id,
            provider_id=acknowledgement.provider_id,
            provider_instance_id=acknowledgement.provider_instance_id,
            claim_sequence=acknowledgement.claim_sequence,
            request_digest=acknowledgement.request_digest,
            provider_receipt_digest=acknowledgement.provider_receipt_digest,
            receipt_signature=signature,
        )
