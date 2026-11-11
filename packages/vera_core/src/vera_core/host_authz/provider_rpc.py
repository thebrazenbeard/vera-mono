"""Authenticated, bounded Linux process boundary for provider effect custody.

The host process holds only a provider public key and a pinned peer identity.
The provider daemon (a *different OS uid*) owns its execution callback,
provider credentials, receipt private key, and durable one-use fence.
The wire request contains only a host-signed command and a witness-signed
START preimage/receipt; client-supplied callback and signer fields are absent.

Source-level implementation, not a host installation. A qualified launcher
must separately provision OS accounts, protected paths, sockets and keys.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import socket
import stat
import struct
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .peer_isolation import read_linux_process_identity
from .provider_custody import ProviderCustodyWorker
from .service import ProviderAcknowledgement
from .unified_authority import WitnessEventReceipt


_WIRE_SCHEMA = "HOST_AUTHZ_PROVIDER_RPC_V1"
_ACK_SCHEMA = "HOST_AUTHZ_PROVIDER_RPC_ACK_V1"
_ACK_CONTEXT = b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0"
_MAX_FRAME = 192 * 1024


class ProviderRPCDenied(PermissionError):
    """Authenticated provider process or the bounded protocol was invalid."""


def _platform() -> None:
    if (os.name != "posix" or not hasattr(socket, "SO_PEERCRED")
            or not hasattr(socket, "SCM_CREDENTIALS")
            or not hasattr(socket, "SO_PASSCRED")):
        raise ProviderRPCDenied("qualified provider RPC is Linux-only")


def _decode(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_FRAME:
        raise ProviderRPCDenied("provider RPC invalid frame length")
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProviderRPCDenied("duplicate RPC JSON field")
            result[key] = value
        return result
    try:
        item = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ProviderRPCDenied("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ProviderRPCDenied("malformed provider RPC JSON") from exc
    if type(item) is not dict or canonical_json_bytes(item) != raw:
        raise ProviderRPCDenied("provider RPC must use canonical JSON")
    return item


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: Any) -> bytes:
    if type(value) is not str or len(value) > (_MAX_FRAME * 4 // 3 + 8):
        raise ProviderRPCDenied("invalid base64 RPC field")
    try:
        data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise ProviderRPCDenied("malformed base64 RPC field") from exc
    if _b64(data) != value:
        raise ProviderRPCDenied("noncanonical base64 RPC field")
    return data


def _send(sock: socket.socket, body: bytes) -> None:
    if type(body) is not bytes or not 0 < len(body) <= _MAX_FRAME:
        raise ProviderRPCDenied("provider RPC output exceeds bound")
    # SOCK_SEQPACKET preserves exactly one writer and message boundary.
    # Splitting a frame into stream reads can allow inherited-FD substitution
    # between the credentials-bearing header and the remaining body.
    if sock.send(body) != len(body):
        raise ProviderRPCDenied("provider RPC packet was not sent atomically")


def _receive(sock: socket.socket, *, authenticated_sender: tuple[int, int, int] | None = None) -> bytes:
    anc_size = socket.CMSG_SPACE(struct.calcsize("3i"))
    body, anc, flags, _ = sock.recvmsg(_MAX_FRAME + 1, anc_size)
    if not body or len(body) > _MAX_FRAME or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        raise ProviderRPCDenied("provider RPC packet missing or truncated")
    if authenticated_sender is not None:
        # Every packet has one kernel-attested sending process identity.
        # Inherited connected socket descriptors do not transfer identity.
        credentials = [struct.unpack("3i", cdata) for level, kind, cdata in anc
                       if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS
                       and len(cdata) == struct.calcsize("3i")]
        if len(credentials) != 1 or credentials[0] != authenticated_sender:
            raise ProviderRPCDenied("RPC writer kernel credentials changed")
    return body


def _pin(pid: int, uid: int, start: int, *, must_differ_from_uid: int) -> None:
    if any(type(v) is not int or v < 0 for v in (pid, uid, start)) or pid < 2 or start < 1:
        raise ProviderRPCDenied("unprovisioned kernel process identity")
    if uid == must_differ_from_uid:
        raise ProviderRPCDenied("host/provider must have separate OS uid")


def _assert_live(pid: int, uid: int, start: int) -> None:
    try:
        live_uid, live_start = read_linux_process_identity(pid)
    except Exception as exc:
        raise ProviderRPCDenied("pinned RPC process unavailable") from exc
    if (live_uid, live_start) != (uid, start):
        raise ProviderRPCDenied("pinned RPC process replaced")


def _peer(sock: socket.socket, expected: tuple[int, int, int]) -> tuple[int, int, int]:
    # SO_PEERCRED reports uid/gid of connecting process at connect time.
    # A per-frame SCM_CREDENTIALS check additionally rejects inherited FDs.
    actual = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                  struct.calcsize("3i")))
    pid, uid, _gid = actual
    if pid != expected[0] or uid != expected[1]:
        raise ProviderRPCDenied("provider RPC peer not host-provisioned")
    _assert_live(expected[0], expected[1], expected[2])
    return actual


class ProviderCustodyRPCServer:
    """Launch inside provider-owned process after dropping to a dedicated UID."""

    def __init__(self, path: str | Path, worker: ProviderCustodyWorker, *,
                 host_pid: int, host_uid: int, host_start: int,
                 timeout_seconds: float = 5.0):
        _platform()
        if type(worker) is not ProviderCustodyWorker:
            raise ProviderRPCDenied("provider server needs exact isolated custody worker")
        _pin(host_pid, host_uid, host_start, must_differ_from_uid=os.geteuid())
        if type(timeout_seconds) is not float or not 0 < timeout_seconds <= 30:
            raise ValueError("bounded RPC timeout required")
        self.path = Path(path)
        self.worker = worker
        self.host_peer = (host_pid, host_uid, host_start)
        self.timeout = timeout_seconds

    def serve_once(self, *, ready: Any = None) -> None:
        # The containing directory is provider-owned and private; a privileged
        # host client may connect, but unprivileged models cannot replace it.
        parent = self.path.parent.lstat()
        if (not self.path.is_absolute() or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.geteuid() or parent.st_mode & 0o077):
            raise ProviderRPCDenied("provider socket directory not privately owned")
        try:
            existing = self.path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ProviderRPCDenied("provider socket path already exists")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        inode = None
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            listener.bind(str(self.path))
            os.chmod(self.path, 0o600)
            inode = self.path.stat().st_ino
            listener.listen(1)
            listener.settimeout(self.timeout)
            if ready is not None:
                ready.set()
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(self.timeout)
                try:
                    authenticated = _peer(connection, self.host_peer)
                    body = _decode(_receive(connection, authenticated_sender=authenticated))
                    if set(body) != {"schema", "command", "start_receipt", "start_event"} or body["schema"] != _WIRE_SCHEMA:
                        raise ProviderRPCDenied("unknown provider RPC request")
                    lease = WitnessEventReceipt(raw=_unb64(body["start_receipt"]),
                                                event=_unb64(body["start_event"]), body={})
                    acknowledgement = self.worker.dispatch(_unb64(body["command"]), start_lease=lease)
                    response = canonical_json_bytes({
                        "schema": _ACK_SCHEMA, "ok": True,
                        "ack": {**acknowledgement.signed_body(),
                                "signature": _b64(acknowledgement.receipt_signature)},
                    })
                except Exception:
                    response = canonical_json_bytes({"schema": _ACK_SCHEMA, "ok": False})
                _send(connection, response)
        finally:
            listener.close()
            if inode is not None:
                try:
                    if self.path.lstat().st_ino == inode and stat.S_ISSOCK(self.path.lstat().st_mode):
                        self.path.unlink()
                except FileNotFoundError:
                    pass


class ProviderCustodyRPCClient:
    """Host-owned provider endpoint pin; never contains provider private key."""

    __slots__ = ("path", "provider_id", "provider_instance_id", "host_id",
                 "epoch", "receipt_public_key_bytes", "host_command_public_key_bytes",
                 "witness_start_public_key", "witness_leader_epoch",
                 "_provider_pid", "_provider_uid", "_provider_start", "_timeout", "_sealed")

    def __setattr__(self, name: str, value: Any) -> None:
        # Construction-time snapshot: no ordinary callback/endpoint retarget.
        # This Python guard is NOT the security boundary against arbitrary
        # code already executing inside the trusted host process.
        if getattr(self, "_sealed", False):
            raise AttributeError("host-pinned provider RPC client is sealed")
        object.__setattr__(self, name, value)

    def __init__(self, path: str | Path, *, provider_pid: int, provider_uid: int,
                 provider_start: int, provider_id: str, provider_instance_id: str,
                 host_id: str, epoch: int, receipt_public_key_bytes: bytes,
                 host_command_public_key_bytes: bytes, witness_start_public_key: bytes,
                 witness_leader_epoch: int, timeout_seconds: float = 5.0):
        _platform()
        _pin(provider_pid, provider_uid, provider_start, must_differ_from_uid=os.geteuid())
        for name, value in (("provider", provider_id), ("instance", provider_instance_id),
                            ("host", host_id)):
            if type(value) is not str or not value or value != value.strip():
                raise ProviderRPCDenied(f"invalid pinned {name}")
        if type(epoch) is not int or epoch < 1 or type(witness_leader_epoch) is not int or witness_leader_epoch < 1:
            raise ProviderRPCDenied("invalid pinned authority epochs")
        for key in (receipt_public_key_bytes, host_command_public_key_bytes, witness_start_public_key):
            if type(key) is not bytes or len(key) != 32:
                raise ProviderRPCDenied("provider client requires pinned Ed25519 roots")
        if type(timeout_seconds) is not float or not 0 < timeout_seconds <= 30:
            raise ValueError("bounded RPC timeout required")
        self.path = Path(path)
        self._provider_pid, self._provider_uid, self._provider_start = provider_pid, provider_uid, provider_start
        self.provider_id = provider_id
        self.provider_instance_id = provider_instance_id
        self.host_id = host_id
        self.epoch = epoch
        self.receipt_public_key_bytes = receipt_public_key_bytes
        self.host_command_public_key_bytes = host_command_public_key_bytes
        self.witness_start_public_key = witness_start_public_key
        self.witness_leader_epoch = witness_leader_epoch
        self._timeout = timeout_seconds
        self._sealed = True

    def dispatch(self, signed_command: bytes, *, start_lease: WitnessEventReceipt) -> ProviderAcknowledgement:
        if type(signed_command) is not bytes or type(start_lease) is not WitnessEventReceipt:
            raise ProviderRPCDenied("RPC needs exact signed command and START lease")
        try:
            meta = self.path.lstat()
        except OSError as exc:
            raise ProviderRPCDenied("provider socket missing") from exc
        if not stat.S_ISSOCK(meta.st_mode) or meta.st_uid != self._provider_uid or meta.st_mode & 0o077:
            raise ProviderRPCDenied("provider socket ownership changed")
        _assert_live(self._provider_pid, self._provider_uid, self._provider_start)
        request = canonical_json_bytes({
            "schema": _WIRE_SCHEMA, "command": _b64(signed_command),
            "start_receipt": _b64(start_lease.raw), "start_event": _b64(start_lease.event),
        })
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
            connection.settimeout(self._timeout)
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            connection.connect(str(self.path))
            authenticated = _peer(connection, (self._provider_pid, self._provider_uid, self._provider_start))
            _send(connection, request)
            response = _decode(_receive(connection, authenticated_sender=authenticated))
        if set(response) != {"schema", "ok", "ack"} or response.get("schema") != _ACK_SCHEMA or response["ok"] is not True:
            raise ProviderRPCDenied("isolated provider refused or lost RPC outcome")
        body = response["ack"]
        signed_fields = {"schema", "effect_id", "provider_id", "provider_instance_id",
                         "claim_sequence", "request_digest", "provider_receipt_digest"}
        if type(body) is not dict or set(body) != signed_fields | {"signature"}:
            raise ProviderRPCDenied("provider ACK malformed")
        try:
            ack = ProviderAcknowledgement(effect_id=body["effect_id"],
                    provider_id=body["provider_id"], provider_instance_id=body["provider_instance_id"],
                    claim_sequence=body["claim_sequence"], request_digest=body["request_digest"],
                    provider_receipt_digest=body["provider_receipt_digest"],
                    receipt_signature=_unb64(body["signature"]))
            Ed25519PublicKey.from_public_bytes(self.receipt_public_key_bytes).verify(
                ack.receipt_signature, _ACK_CONTEXT + canonical_json_bytes(ack.signed_body()))
        except (InvalidSignature, TypeError, ValueError) as exc:
            raise ProviderRPCDenied("provider ACK not signed by pinned receipt key") from exc
        if (ack.provider_id, ack.provider_instance_id) != (self.provider_id, self.provider_instance_id):
            raise ProviderRPCDenied("provider ACK identity substituted")
        return ack
