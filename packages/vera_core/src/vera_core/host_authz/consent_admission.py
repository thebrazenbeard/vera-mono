"""One-host consent/effect-start linearization boundary (opt-in, source-only).

Consent revocation and provider effect START are serialized under the SAME
host-owned cross-process file lock. The START record is durable before calling
the provider, and it is never automatically retried. A revocation that wins
the lock first denies the START; a revocation arriving after START waits until
the bounded provider handoff returns. Physical effects cannot be un-done.

This does not grant production authority: the external monotonic witness,
privileged OS/process custody, bounded provider execution, and cooperation of
all revocation paths (including ClaimLedger) require real-host qualification.
It cannot solve cross-host partitions using local SQLite/flock alone.
This module and ClaimLedger currently maintain distinct local event counters;
they are NOT one externally witnessed global order. Deployment must bind both
streams to one independently exclusive authority before any protected effect.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any, Callable, Iterator, Protocol

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .grants import ApprovedGrant, SignedGrantVerifier
from .ledger import ClaimLedger
from .service import ProviderDispatch


class ConsentAdmissionDenied(PermissionError):
    """No trusted authorization for a new physical provider effect."""


class ConsentEffectUnknown(RuntimeError):
    """START was consumed; provider effect requires independent reconciliation."""


class ConsentAdmissionWitness(Protocol):
    def attest_start(
        self, *, authority_id: str, epoch: int, sequence: int,
        grant_id: str, effect_id: str, scope_digest: str,
    ) -> bool: ...

    def attest_scope_revoke(
        self, *, authority_id: str, epoch: int, sequence: int,
        scope_digest: str,
    ) -> bool: ...


_SCOPE_FIELDS = (
    "participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
    "subject_id", "host_id", "provider_id", "provider_instance_id",
)


@dataclass(frozen=True, slots=True)
class ConsentScope:
    participant_id: str
    purpose: str
    model_id: str
    adapter_id: str
    runtime_id: str
    subject_id: str
    host_id: str
    provider_id: str
    provider_instance_id: str

    def __post_init__(self) -> None:
        for key in _SCOPE_FIELDS:
            value = getattr(self, key)
            if (
                type(value) is not str or not value or len(value) > 256
                or value != value.strip() or any(ord(ch) < 32 for ch in value)
            ):
                raise ValueError(f"invalid consent scope field: {key}")

    @classmethod
    def from_grant(cls, grant: ApprovedGrant) -> "ConsentScope":
        if type(grant) is not ApprovedGrant:
            raise ConsentAdmissionDenied("grant is not canonical")
        return cls(**{key: getattr(grant, key) for key in _SCOPE_FIELDS})

    def body(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in _SCOPE_FIELDS}

    @property
    def digest(self) -> str:
        return sha256(canonical_json_bytes(self.body())).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsentAdmissionRecord:
    effect_id: str
    grant_id: str
    scope_digest: str
    claim_sequence: int
    event_sequence: int
    state: str


def _name(value: str, field: str) -> str:
    if (
        type(value) is not str or not value or len(value) > 256
        or value != value.strip() or any(ord(ch) < 32 for ch in value)
    ):
        raise ConsentAdmissionDenied(f"invalid {field}")
    return value


class ConsentAdmission:
    """Host-only serialized revocation versus physical effect start.

    The host MUST supply a qualified external witness and canonical governed
    provider dispatch. This class does not expose a network admin endpoint.
    A caller's model-generated content can never instantiate this authority.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        authority_id: str,
        epoch: int,
        grant_verifier: SignedGrantVerifier,
        claim_ledger: ClaimLedger,
        witness: ConsentAdmissionWitness | None,
        provider_execute: Callable[[ProviderDispatch], Any],
    ) -> None:
        self.authority_id = _name(authority_id, "authority_id")
        if type(epoch) is not int or epoch <= 0:
            raise ValueError("epoch must be positive exact integer")
        self.epoch = epoch
        if type(grant_verifier) is not SignedGrantVerifier:
            raise TypeError("grant_verifier must be exact SignedGrantVerifier")
        if type(claim_ledger) is not ClaimLedger:
            raise TypeError("claim_ledger must be exact ClaimLedger")
        if (
            grant_verifier.host_id != authority_id or grant_verifier.epoch != epoch
            or claim_ledger.authority_id != authority_id or claim_ledger.epoch != epoch
        ):
            raise ConsentAdmissionDenied("different host or authority epoch")
        if not callable(provider_execute):
            raise TypeError("host provider must be callable")
        self._verifier = grant_verifier
        self._claims = claim_ledger
        claim_meta = claim_ledger.path.lstat()
        if not stat.S_ISREG(claim_meta.st_mode) or claim_meta.st_uid != os.getuid():
            raise ConsentAdmissionDenied("claim ledger is not host-owned regular storage")
        self._claim_store_identity = (claim_meta.st_dev, claim_meta.st_ino)
        self._witness = witness
        self._provider = provider_execute
        self.path = Path(path)
        self.lock_path = Path(str(self.path) + ".lock")
        parent = self.path.parent
        if not parent.is_dir() or parent.is_symlink():
            raise ConsentAdmissionDenied("host state parent must be a real directory")
        self._check_parent(parent)
        self._store_identity = self._open_store_file()
        self._init_db()

    @staticmethod
    def _check_parent(parent: Path) -> None:
        meta = parent.lstat()
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != os.getuid()
            or meta.st_mode & 0o022
        ):
            raise ConsentAdmissionDenied("host state parent is not protected")

    def _open_store_file(self) -> tuple[int, int]:
        """Create mode-0600 store or refuse substituted/non-regular data files."""
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise ConsentAdmissionDenied("host state file unavailable") from exc
        try:
            meta = os.fstat(fd)
            path_meta = self.path.lstat()
            if (
                not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or meta.st_mode & 0o077
                or (meta.st_dev, meta.st_ino) != (path_meta.st_dev, path_meta.st_ino)
            ):
                raise ConsentAdmissionDenied("host state file is not privately owned")
            return (meta.st_dev, meta.st_ino)
        finally:
            os.close(fd)

    def _verify_store_identity(self) -> None:
        meta = self.path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or (meta.st_dev, meta.st_ino) != self._store_identity
            or meta.st_mode & 0o077
        ):
            raise ConsentAdmissionDenied("host state file identity changed")

    @contextmanager
    def _host_lock(self) -> Iterator[None]:
        try:
            import fcntl
        except ImportError as exc:
            raise ConsentAdmissionDenied("POSIX host lock unavailable") from exc
        self._check_parent(self.path.parent)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError as exc:
            raise ConsentAdmissionDenied("host lock file unavailable") from exc
        try:
            meta = os.fstat(fd)
            if (
                not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or (meta.st_mode & 0o022)
            ):
                raise ConsentAdmissionDenied("host lock is not protected")
            fcntl.flock(fd, fcntl.LOCK_EX)
            observed = self.lock_path.lstat()
            if observed.st_ino != meta.st_ino or observed.st_dev != meta.st_dev:
                raise ConsentAdmissionDenied("host lock path was replaced")
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        self._verify_store_identity()
        db = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _init_db(self) -> None:
        with self._host_lock():
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""CREATE TABLE IF NOT EXISTS consent_authority (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    authority_id TEXT NOT NULL, epoch INTEGER NOT NULL,
                    last_event INTEGER NOT NULL
                )""")
                db.execute("""CREATE TABLE IF NOT EXISTS consent_revocations (
                    scope_digest TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE
                )""")
                db.execute("""CREATE TABLE IF NOT EXISTS effect_admissions (
                    effect_id TEXT PRIMARY KEY, grant_id TEXT UNIQUE NOT NULL,
                    scope_digest TEXT NOT NULL, claim_sequence INTEGER NOT NULL,
                    event_sequence INTEGER NOT NULL UNIQUE,
                    state TEXT NOT NULL CHECK(state IN (
                        'STARTED', 'RETURNED_UNVERIFIED', 'AMBIGUOUS'
                    ))
                )""")
                row = db.execute(
                    "SELECT authority_id,epoch FROM consent_authority WHERE singleton=1"
                ).fetchone()
                if row is None:
                    db.execute(
                        "INSERT INTO consent_authority VALUES(1,?,?,0)",
                        (self.authority_id, self.epoch),
                    )
                elif row["authority_id"] != self.authority_id or row["epoch"] != self.epoch:
                    raise ConsentAdmissionDenied("persisted authority mismatch")
                db.commit()

    @staticmethod
    def _record(row: sqlite3.Row) -> ConsentAdmissionRecord:
        return ConsentAdmissionRecord(
            row["effect_id"], row["grant_id"], row["scope_digest"],
            row["claim_sequence"], row["event_sequence"], row["state"],
        )

    def read(self, effect_id: str) -> ConsentAdmissionRecord | None:
        effect_id = _name(effect_id, "effect_id")
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM effect_admissions WHERE effect_id=?", (effect_id,)
            ).fetchone()
        return self._record(row) if row else None

    def revoked(self, scope: ConsentScope) -> bool:
        if type(scope) is not ConsentScope:
            raise TypeError("scope must be exact ConsentScope")
        with self._db() as db:
            row = db.execute(
                "SELECT 1 FROM consent_revocations WHERE scope_digest=?", (scope.digest,)
            ).fetchone()
        return row is not None

    @contextmanager
    def _claim_writer_lock(
        self, grant_id: str, claim_sequence: int, claim_digest: str,
    ) -> Iterator[None]:
        """Serialize existing ClaimLedger.revoke against physical START.

        ClaimLedger.revoke uses SQLite BEGIN IMMEDIATE on its own database.
        Holding the same SQLite writer lock across the provider handoff is the
        only available source-local way to prevent that separate revocation
        path overtaking START. This intentionally serializes all claim writes
        on one host and MUST run with a bounded OS-enforced provider timeout.
        An uncooperative provider callback can otherwise delay revocation.
        """
        claim_meta = self._claims.path.lstat()
        if (
            not stat.S_ISREG(claim_meta.st_mode)
            or (claim_meta.st_dev, claim_meta.st_ino) != self._claim_store_identity
        ):
            raise ConsentAdmissionDenied("claim ledger storage was replaced")
        db = sqlite3.connect(self._claims.path, timeout=30.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("BEGIN IMMEDIATE")
            claim_meta = self._claims.path.lstat()
            if (
                not stat.S_ISREG(claim_meta.st_mode)
                or (claim_meta.st_dev, claim_meta.st_ino) != self._claim_store_identity
            ):
                raise ConsentAdmissionDenied("claim ledger storage changed during lock")
            row = db.execute(
                "SELECT claim_digest,sequence,state,revoked FROM claims WHERE grant_id=?",
                (grant_id,),
            ).fetchone()
            if (
                row is None or row["state"] != "RESERVED" or row["revoked"]
                or row["sequence"] != claim_sequence
                or row["claim_digest"] != claim_digest
            ):
                raise ConsentAdmissionDenied("claim was revoked or changed before START")
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def revoke_scope(self, scope: ConsentScope) -> int:
        """Privileged consent controller only; never add this to model IPC.

        Revocation linearizes when this host lock is acquired. It cannot
        retroactively stop an effect whose START already linearized.
        """
        if type(scope) is not ConsentScope:
            raise TypeError("scope must be exact ConsentScope")
        with self._host_lock():
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT sequence FROM consent_revocations WHERE scope_digest=?",
                    (scope.digest,),
                ).fetchone()
                if existing is not None:
                    db.commit()
                    return existing["sequence"]
                seq = db.execute(
                    "SELECT last_event FROM consent_authority WHERE singleton=1"
                ).fetchone()["last_event"] + 1
                attestor = getattr(self._witness, "attest_scope_revoke", None)
                if not callable(attestor):
                    raise ConsentAdmissionDenied("external revocation witness unavailable")
                try:
                    positive = attestor(
                        authority_id=self.authority_id, epoch=self.epoch,
                        sequence=seq, scope_digest=scope.digest,
                    )
                except Exception as exc:
                    raise ConsentAdmissionDenied("external revocation witness failed") from exc
                if positive is not True:
                    raise ConsentAdmissionDenied("external revocation witness denied")
                db.execute(
                    "INSERT INTO consent_revocations VALUES(?,?)", (scope.digest, seq)
                )
                db.execute(
                    "UPDATE consent_authority SET last_event=? WHERE singleton=1", (seq,)
                )
                db.commit()
                return seq

    def perform(self, signed_grant: bytes, instruction: ProviderDispatch) -> Any:
        """One admitted provider handoff, held under same lock as revocation.

        A returned response is NOT independent provider-effect proof. The
        caller must verify it and reconcile the separate ClaimLedger.
        """
        if type(instruction) is not ProviderDispatch:
            raise ConsentAdmissionDenied("noncanonical provider instruction")
        try:
            grant = self._verifier.verify(signed_grant)
        except Exception as exc:
            raise ConsentAdmissionDenied("invalid host-issued grant") from exc
        scope = ConsentScope.from_grant(grant)
        if (
            grant.grant_id != instruction.grant_id
            or grant.provider_id != instruction.provider_id
            or grant.provider_instance_id != instruction.provider_instance_id
            or grant.operation != instruction.operation
            or grant.request_digest != instruction.request_digest
            or grant.participant_id != instruction.participant_id
            or grant.purpose != instruction.purpose
            or sha256(canonical_json_bytes(instruction.request_payload)).hexdigest()
            != instruction.request_digest
        ):
            raise ConsentAdmissionDenied("grant and effect instruction differ")
        claim = self._claims.read(grant.grant_id)
        if (
            claim is None or claim.state != "RESERVED" or claim.revoked
            or claim.sequence != instruction.claim_sequence
        ):
            raise ConsentAdmissionDenied("grant has no current durable claim")
        claim_digest = sha256(canonical_json_bytes({
            "schema": "HOST_AUTHZ_CLAIM_V1",
            "grant": grant.canonical_body(),
            "provider_instance_id": grant.provider_instance_id,
            "request_digest": grant.request_digest,
        })).hexdigest()
        effect_id = sha256(canonical_json_bytes({
            "schema": "HOST_AUTHZ_EFFECT_ID_V1", "host_id": grant.host_id,
            "epoch": grant.epoch, "claim_sequence": claim.sequence,
            "claim_digest": claim_digest, "grant_id": grant.grant_id,
        })).hexdigest()
        if claim.claim_digest != claim_digest or instruction.effect_id != effect_id:
            raise ConsentAdmissionDenied("effect does not bind the signed durable claim")
        # Snapshot the exact provider payload so caller mutation cannot retarget it.
        body = json.loads(canonical_json_bytes(instruction.request_payload))
        pinned = ProviderDispatch(
            instruction.effect_id, instruction.grant_id, instruction.provider_id,
            instruction.provider_instance_id, instruction.operation,
            instruction.request_digest, instruction.claim_sequence,
            instruction.participant_id, instruction.purpose, body,
        )
        with self._host_lock(), self._claim_writer_lock(
            grant.grant_id, instruction.claim_sequence, claim_digest
        ):
            # Revocation and START use this same exclusive lock, even across
            # processes sharing the same protected host state directory.
            # A call can wait for that lock long enough for a grant to expire.
            # Reverify its signed validity at the actual START boundary.
            try:
                refreshed_grant = self._verifier.verify(signed_grant)
            except Exception as exc:
                raise ConsentAdmissionDenied("grant stale before physical START") from exc
            if refreshed_grant.canonical_body() != grant.canonical_body():
                raise ConsentAdmissionDenied("signed grant changed before START")
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT 1 FROM consent_revocations WHERE scope_digest=?",
                    (scope.digest,),
                ).fetchone() is not None:
                    raise ConsentAdmissionDenied("consent scope revoked before start")
                if db.execute(
                    "SELECT 1 FROM effect_admissions WHERE effect_id=? OR grant_id=?",
                    (instruction.effect_id, instruction.grant_id),
                ).fetchone() is not None:
                    raise ConsentAdmissionDenied("effect already started; no retry")
                refreshed = self._claims.read(grant.grant_id)
                if (
                    refreshed is None or refreshed.revoked
                    or refreshed.state != "RESERVED"
                    or refreshed.sequence != instruction.claim_sequence
                    or refreshed.claim_digest != claim_digest
                ):
                    raise ConsentAdmissionDenied("grant state changed before start")
                seq = db.execute(
                    "SELECT last_event FROM consent_authority WHERE singleton=1"
                ).fetchone()["last_event"] + 1
                attestor = getattr(self._witness, "attest_start", None)
                if not callable(attestor):
                    raise ConsentAdmissionDenied("external start witness unavailable")
                try:
                    positive = attestor(
                        authority_id=self.authority_id, epoch=self.epoch,
                        sequence=seq, grant_id=grant.grant_id,
                        effect_id=instruction.effect_id, scope_digest=scope.digest,
                    )
                except Exception as exc:
                    raise ConsentAdmissionDenied("external start witness failed") from exc
                if positive is not True:
                    raise ConsentAdmissionDenied("external start witness denied")
                db.execute(
                    """INSERT INTO effect_admissions
                    VALUES(?,?,?,?,?,'STARTED')""",
                    (
                        instruction.effect_id, grant.grant_id, scope.digest,
                        instruction.claim_sequence, seq,
                    ),
                )
                db.execute(
                    "UPDATE consent_authority SET last_event=? WHERE singleton=1",
                    (seq,),
                )
                db.commit()
            try:
                response = self._provider(pinned)
            except BaseException as exc:
                self._mark(instruction.effect_id, "AMBIGUOUS")
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise ConsentEffectUnknown("provider handoff outcome unknown") from exc
            self._mark(instruction.effect_id, "RETURNED_UNVERIFIED")
            return response

    def _mark(self, effect_id: str, state: str) -> None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state FROM effect_admissions WHERE effect_id=?", (effect_id,)
            ).fetchone()
            if row is None or row["state"] != "STARTED":
                raise ConsentEffectUnknown("durable start record missing")
            db.execute(
                "UPDATE effect_admissions SET state=? WHERE effect_id=?",
                (state, effect_id),
            )
            db.commit()
