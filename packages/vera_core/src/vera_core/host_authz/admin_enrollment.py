"""Linux host-administrator grant enrollment, isolated from model/witness RPC.

This is a source reference boundary, NOT a deployed administrator service.
The witness's ``register_grant`` method is callable here only after a pinned
kernel OS identity authenticates on a private Unix socket. Network witness
clients never acquire registration privileges. The server keeps a durable
PRE-ADMISSION audit attempt; a crash after witness commit leaves PENDING and
MUST be reconciled manually rather than blindly resubmitted.

The administrator, leader, provider and each model require distinct OS
principals in production. Protected account provisioning, group membership,
consent-origin custody, Windows transport and live host proof are NOT provided.
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
import socket
import sqlite3
import stat
import struct
from typing import Any, Iterator

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .grants import GrantVerificationError
from .peer_isolation import read_linux_process_identity
from .unified_witness_server import UnifiedWitnessLeader, WitnessLeaderDenied


ENROLL_SCHEMA = "HOST_AUTHZ_ADMIN_ENROLL_V1"
RESPONSE_SCHEMA = "HOST_AUTHZ_ADMIN_ENROLL_RESULT_V1"
_MAX_FRAME = 131_072


class AdminEnrollmentDenied(PermissionError):
    """The caller or requested enrollment has no host-admin authority."""


def _linux() -> None:
    if (os.name != "posix" or not hasattr(os, "getuid")
            or not hasattr(socket, "SO_PEERCRED")
            or not hasattr(socket, "SO_PASSCRED")
            or not hasattr(socket, "SCM_CREDENTIALS")
            or not hasattr(socket, "SOCK_SEQPACKET")):
        raise AdminEnrollmentDenied("administrator enrollment requires Linux kernel IPC")


def _strict_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_FRAME:
        raise AdminEnrollmentDenied("invalid enrollment frame size")

    def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdminEnrollmentDenied("duplicate enrollment field")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               AdminEnrollmentDenied("nonfinite enrollment field")))
    except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
        raise AdminEnrollmentDenied("malformed enrollment frame") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise AdminEnrollmentDenied("noncanonical enrollment frame")
    return value


def _unbase64(text: Any) -> bytes:
    if type(text) is not str or not 0 < len(text) < _MAX_FRAME * 2:
        raise AdminEnrollmentDenied("invalid signed grant encoding")
    try:
        data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, binascii.Error) as exc:
        raise AdminEnrollmentDenied("malformed signed grant encoding") from exc
    if base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii") != text:
        raise AdminEnrollmentDenied("noncanonical signed grant encoding")
    if not 0 < len(data) <= _MAX_FRAME:
        raise AdminEnrollmentDenied("signed grant exceeds bound")
    return data


@dataclass(frozen=True, slots=True)
class AdminProcessPin:
    """Host-launcher attested, exact administrator process and consent domain."""

    pid: int
    uid: int
    gid: int
    process_start: int
    host_id: str
    issuer_id: str
    epoch: int

    def __post_init__(self) -> None:
        for name in ("pid", "uid", "gid", "process_start", "epoch"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise AdminEnrollmentDenied(f"invalid administrator {name}")
        if self.pid < 2:
            raise AdminEnrollmentDenied("administrator PID cannot be kernel PID")
        if any(type(s) is not str or not s or s.strip() != s
               for s in (self.host_id, self.issuer_id)):
            raise AdminEnrollmentDenied("invalid administrator authority identity")


def _secure_journal(path: Path) -> None:
    _linux()
    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise AdminEnrollmentDenied("audit journal requires absolute Linux path")
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise AdminEnrollmentDenied("audit journal directory absent") from exc
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or parent.st_mode & 0o077):
        raise AdminEnrollmentDenied("audit directory not exclusively leader-owned")
    try:
        entry = path.lstat()
    except FileNotFoundError:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    else:
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != os.geteuid()
                or entry.st_mode & 0o077):
            raise AdminEnrollmentDenied("audit journal is replaced or accessible")


class AdminEnrollmentJournal:
    """Durable attempt audit without issuer private keys or raw signed grants."""

    def __init__(self, path: str | Path, *, host_id: str, issuer_id: str, epoch: int):
        self._path = Path(path)
        _secure_journal(self._path)
        self._inode = (self._path.stat().st_dev, self._path.stat().st_ino)
        self._identity = (host_id, issuer_id, epoch)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS journal_identity (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                host_id TEXT NOT NULL, issuer_id TEXT NOT NULL, epoch INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                request_digest TEXT PRIMARY KEY, admin_uid INTEGER NOT NULL,
                admin_pid INTEGER NOT NULL, status TEXT NOT NULL
                CHECK(status IN ('PENDING','ADMITTED','DENIED')),
                grant_id TEXT)""")
            row = db.execute("SELECT host_id,issuer_id,epoch FROM journal_identity WHERE singleton=1").fetchone()
            if row is None:
                db.execute("INSERT INTO journal_identity VALUES(1,?,?,?)", self._identity)
            elif tuple(row) != self._identity:
                raise AdminEnrollmentDenied("audit authority identity changed")
            db.commit()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        _secure_journal(self._path)
        entry = self._path.stat()
        if (entry.st_dev, entry.st_ino) != self._inode:
            raise AdminEnrollmentDenied("audit journal substituted")
        db = sqlite3.connect(self._path, isolation_level=None, timeout=5)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def begin(self, request_digest: str, *, admin_uid: int, admin_pid: int) -> None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT INTO attempts VALUES(?,?,?,'PENDING',NULL)",
                           (request_digest, admin_uid, admin_pid))
            except sqlite3.IntegrityError as exc:
                raise AdminEnrollmentDenied("enrollment request already consumed") from exc
            db.commit()

    def finish(self, request_digest: str, *, status: str, grant_id: str | None = None) -> None:
        if status not in ("ADMITTED", "DENIED"):
            raise ValueError("journal cannot silently resolve ambiguous enrollment")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("UPDATE attempts SET status=?,grant_id=? "
                                "WHERE request_digest=? AND status='PENDING'",
                                (status, grant_id, request_digest))
            if result.rowcount != 1:
                raise AdminEnrollmentDenied("journal attempt missing or already final")
            db.commit()

    def read(self, request_digest: str) -> tuple[str, str | None] | None:
        with self._db() as db:
            row = db.execute("SELECT status,grant_id FROM attempts WHERE request_digest=?",
                             (request_digest,)).fetchone()
            return tuple(row) if row is not None else None


class HostAdminEnrollmentServer:
    """One-request Linux host-admin listener with kernel credential admission.

    The exact issuer-admin principal is fixed by the leader launcher, and may
    not equal a bound model principal. Network models cannot self-enroll.
    """

    def __init__(self, socket_path: str | Path, *, leader: UnifiedWitnessLeader,
                 journal: AdminEnrollmentJournal, admin: AdminProcessPin,
                 forbidden_uids: frozenset[int] = frozenset(),
                 timeout_seconds: float = 5.0):
        _linux()
        if type(leader) is not UnifiedWitnessLeader or type(journal) is not AdminEnrollmentJournal:
            raise TypeError("exact leader and journal required")
        if type(admin) is not AdminProcessPin or type(forbidden_uids) is not frozenset:
            raise TypeError("host administrator pin and forbidden principals required")
        if any(type(value) is not int or value < 0 for value in forbidden_uids):
            raise AdminEnrollmentDenied("invalid forbidden UID")
        c = leader.config
        if (admin.host_id, admin.issuer_id, admin.epoch) != (c.host_id, c.issuer_id, c.epoch):
            raise AdminEnrollmentDenied("administrator not bound to witness authority")
        if journal._identity != (c.host_id, c.issuer_id, c.epoch):
            raise AdminEnrollmentDenied("journal authority differs from witness")
        model_uids: set[int] = set()
        for peer in leader.bindings.principals:
            if not peer.startswith("uid:"):
                raise AdminEnrollmentDenied("Linux admin requires kernel-bound model principals")
            try:
                uid_text = peer.split(":", 1)[1]
                if not uid_text.isascii() or not uid_text.isdecimal():
                    raise ValueError("nondecimal UID")
                parsed_uid = int(uid_text)
                if str(parsed_uid) != uid_text:
                    raise ValueError("noncanonical UID")
                model_uids.add(parsed_uid)
            except ValueError as exc:
                raise AdminEnrollmentDenied("malformed model peer UID") from exc
        if admin.uid in (os.geteuid(), *model_uids, *forbidden_uids):
            raise AdminEnrollmentDenied("administrator must have distinct OS principal")
        if type(timeout_seconds) is not float or not 0 < timeout_seconds <= 30:
            raise ValueError("bounded socket timeout required")
        self._path = Path(socket_path)
        self._leader = leader
        self._journal = journal
        self._admin = admin
        self._timeout = timeout_seconds

    def _verify_admin(self, connection: socket.socket, ancillary: list[tuple[int, int, bytes]]) -> None:
        pin = self._admin
        size = struct.calcsize("3i")
        actual = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size))
        if actual != (pin.pid, pin.uid, pin.gid):
            raise AdminEnrollmentDenied("socket peer is not pinned administrator")
        credentials = [struct.unpack("3i", data) for level, kind, data in ancillary
                       if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
                       and len(data) == size]
        if credentials != [(pin.pid, pin.uid, pin.gid)]:
            raise AdminEnrollmentDenied("message author is not pinned administrator")
        try:
            uid, start = read_linux_process_identity(pin.pid)
        except Exception as exc:
            raise AdminEnrollmentDenied("administrator process no longer pinned") from exc
        if (uid, start) != (pin.uid, pin.process_start):
            raise AdminEnrollmentDenied("administrator process identity changed")

    def _register(self, frame: bytes) -> dict[str, Any]:
        data = _strict_json(frame)
        if set(data) != {"schema", "signed_grant"} or data["schema"] != ENROLL_SCHEMA:
            raise AdminEnrollmentDenied("unknown administrator operation")
        signed = _unbase64(data["signed_grant"])
        digest = sha256(signed).hexdigest()
        self._journal.begin(digest, admin_uid=self._admin.uid, admin_pid=self._admin.pid)
        try:
            grant_id = self._leader.register_grant(signed)
        except (WitnessLeaderDenied, GrantVerificationError):
            # Explicit issuer/consent denial is final. Unknown failures must
            # preserve PENDING because leader commit may have taken place.
            self._journal.finish(digest, status="DENIED")
            raise AdminEnrollmentDenied("signed registration not approved") from None
        except Exception as exc:
            # No retry: this may have happened after registration committed.
            raise AdminEnrollmentDenied("enrollment result requires reconciliation") from exc
        self._journal.finish(digest, status="ADMITTED", grant_id=grant_id)
        return {"schema": RESPONSE_SCHEMA, "ok": True, "grant_id": grant_id}

    def serve_once(self, *, ready: Any = None) -> None:
        pin = self._admin
        try:
            uid, start = read_linux_process_identity(pin.pid)
            if (uid, start) != (pin.uid, pin.process_start):
                raise AdminEnrollmentDenied("administrator process not active")
            parent = self._path.parent.lstat()
        except OSError as exc:
            raise AdminEnrollmentDenied("administrator socket directory unavailable") from exc
        if (not self._path.is_absolute() or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.geteuid() or parent.st_gid != pin.gid
                or parent.st_mode & 0o007 or not parent.st_mode & stat.S_IXGRP):
            raise AdminEnrollmentDenied("admin socket directory ownership/ACL invalid")
        try:
            self._path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise AdminEnrollmentDenied("admin socket path already exists")
        if len(os.fsencode(self._path)) >= 104:
            raise AdminEnrollmentDenied("administrator socket path too long")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        inode = None
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            listener.bind(str(self._path))
            inode = self._path.stat().st_ino
            os.chown(self._path, -1, pin.gid, follow_symlinks=False)
            os.chmod(self._path, 0o660)
            listener.listen(1)
            listener.settimeout(self._timeout)
            if ready is not None:
                ready.set()
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(self._timeout)
                try:
                    frame, ancillary, flags, _ = connection.recvmsg(
                        _MAX_FRAME + 1, socket.CMSG_SPACE(struct.calcsize("3i")))
                    if not frame or len(frame) > _MAX_FRAME or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                        raise AdminEnrollmentDenied("invalid administrator packet")
                    self._verify_admin(connection, ancillary)
                    response = self._register(frame)
                except Exception:
                    response = {"schema": RESPONSE_SCHEMA, "ok": False}
                encoded = canonical_json_bytes(response)
                connection.send(encoded)
        finally:
            listener.close()
            if inode is not None:
                try:
                    current = self._path.lstat()
                    if stat.S_ISSOCK(current.st_mode) and current.st_ino == inode:
                        self._path.unlink()
                except FileNotFoundError:
                    pass
