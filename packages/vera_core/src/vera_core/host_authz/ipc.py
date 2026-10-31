"""Host-owned, Linux kernel-peer authenticated authorization service endpoint.

The protocol intentionally has only one operation: an effect authorization
request. No caller-provided principal identity is accepted. An OS UID is only
adequate when each model is run under a *different, dedicated* UID; the host
must keep model-owned processes out of the authorization-service UID.

Windows named-pipe peer authentication is not implemented here. Do not replace
it with ordinary localhost TCP, a self-reported model name or a bearer string.
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
import sys
import threading
from typing import Any

from .peer_isolation import (
    HostPeerIsolationPlan,
    PeerIsolationDenied,
    receive_authenticated_linux_frame,
)
from .unified_service import UnifiedAuthorizationService


_REQUEST_KEYS = frozenset({
    "signed_grant_b64", "provider_id", "operation", "request_payload"
})
_DENIED = b'{"ok":false,"error":"denied"}\n'
DEFAULT_MAX_MESSAGE_BYTES = 65_536
MAX_SIGNED_GRANT_BYTES = 16_384
MAX_RESPONSE_BYTES = 8_192


class HostIPCError(OSError):
    """Untrusted/malformed IPC, or unavailable host-bound peer identity."""


def authenticated_peer_key(connection: socket.socket) -> str:
    """Derive identity from Linux SO_PEERCRED, never from the request body.

    The host principal registry must map a single dedicated UID to exactly one
    model binding, and must deny absent or ambiguous UIDs. SO_PEERCRED alone
    does not distinguish two models intentionally sharing a UID.
    """

    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        raise HostIPCError("kernel peer authentication is unavailable")
    size = struct.calcsize("3i")
    try:
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
        pid, uid, gid = struct.unpack("3i", credentials)
    except (AttributeError, OSError, struct.error, TypeError) as exc:
        raise HostIPCError("kernel peer authentication failed") from exc
    if pid <= 0 or uid < 0 or gid < 0:
        raise HostIPCError("kernel peer identity is invalid")
    return f"uid:{uid}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HostIPCError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> Any:
    raise HostIPCError(f"invalid nonfinite JSON constant {value}")


def _decode_request(data: bytes) -> tuple[bytes, str, str, dict[str, Any]]:
    try:
        raw = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_invalid_constant,
        )
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise HostIPCError("invalid request encoding") from exc
    if type(raw) is not dict or raw.keys() != _REQUEST_KEYS:
        raise HostIPCError("unknown or missing request fields")
    grant_b64 = raw["signed_grant_b64"]
    provider_id = raw["provider_id"]
    operation = raw["operation"]
    payload = raw["request_payload"]
    if (
        type(grant_b64) is not str
        or type(provider_id) is not str
        or not provider_id
        or type(operation) is not str
        or not operation
        or type(payload) is not dict
    ):
        raise HostIPCError("incorrect request field types")
    if len(grant_b64) > (MAX_SIGNED_GRANT_BYTES * 4 // 3 + 8):
        raise HostIPCError("oversized grant")
    try:
        signed_grant = base64.b64decode(grant_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HostIPCError("invalid grant encoding") from exc
    if not signed_grant or len(signed_grant) > MAX_SIGNED_GRANT_BYTES:
        raise HostIPCError("invalid grant size")
    return signed_grant, provider_id, operation, payload


def _read_single_frame(connection: socket.socket, max_bytes: int) -> bytes:
    data = bytearray()
    while b"\n" not in data:
        remaining = max_bytes + 1 - len(data)
        if remaining <= 0:
            raise HostIPCError("request too large")
        chunk = connection.recv(min(remaining, 4096))
        if not chunk:
            raise HostIPCError("missing frame terminator")
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HostIPCError("request too large")
    frame, _, remainder = bytes(data).partition(b"\n")
    if remainder or not frame:
        raise HostIPCError("multiple or empty request frames")
    return frame


def handle_connection(
    connection: socket.socket,
    service: Any,
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    timeout_seconds: float = 5.0,
) -> None:
    """Handle exactly one request using an OS-authenticated caller principal.

    Generic denials deliberately do not expose issuer, participant, key,
    provider, consent, policy or ledger internals to untrusted model adapters.
    """

    if type(max_message_bytes) is not int or max_message_bytes < 1:
        raise ValueError("max_message_bytes must be positive exact int")
    if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be in (0,60]")
    try:
        connection.settimeout(float(timeout_seconds))
        peer_key = authenticated_peer_key(connection)
        request = _read_single_frame(connection, max_message_bytes)
        response = _execute_request(service, peer_key, request)
    except Exception:
        response = _DENIED
    try:
        connection.sendall(response)
    except (OSError, TimeoutError):
        pass


def _execute_request(service: Any, peer_key: str, request: bytes) -> bytes:
    """Shared request validation; the caller supplies only kernel peer identity."""
    signed_grant, provider_id, operation, payload = _decode_request(request)
    receipt = service.execute(
        peer_key=peer_key,
        signed_grant=signed_grant,
        provider_id=provider_id,
        operation=operation,
        request_payload=payload,
    )
    public = receipt.public_body()
    if type(public) is not dict:
        raise HostIPCError("invalid public receipt")
    response = (json.dumps(
        {"ok": True, "receipt": public},
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n").encode("utf-8")
    if len(response) > MAX_RESPONSE_BYTES:
        raise HostIPCError("oversized public receipt")
    return response


class UnixAuthorityServer:
    """LEGACY low-level Unix server; NOT a qualified multi-model boundary.

    `socket_path` must be inside a pre-provisioned host-owned directory whose
    permissions prevent group/world writes. The server refuses an existing
    path and only unlinks the exact socket inode it created. Production host
    provisioning, UID isolation and provider custody require separate tests.
    This class verifies only connection-time SO_PEERCRED. A child inheriting a
    connected FD is not distinguished; deploy QualifiedUnixAuthorityServer.
    """

    def __init__(
        self,
        socket_path: str | Path,
        service: Any,
        *,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        timeout_seconds: float = 5.0,
        socket_mode: int = 0o660,
    ) -> None:
        if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
            raise HostIPCError("Linux SO_PEERCRED is required")
        if type(socket_mode) is not int or socket_mode not in (0o600, 0o660):
            raise ValueError("socket_mode must be 0600 or 0660")
        if type(max_message_bytes) is not int or max_message_bytes < 1:
            raise ValueError("max_message_bytes must be positive exact int")
        if type(timeout_seconds) not in (float, int) or not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be in (0,60]")
        path = Path(socket_path)
        if not path.is_absolute():
            raise HostIPCError("socket_path must be absolute")
        if len(os.fsencode(path)) > 100:
            raise HostIPCError("socket_path is too long")
        self._path = path
        self._service = service
        self._max_bytes = max_message_bytes
        self._timeout_seconds = float(timeout_seconds)
        self._socket_mode = socket_mode

    def _check_parent(self) -> None:
        parent = self._path.parent
        try:
            meta = parent.lstat()
        except OSError as exc:
            raise HostIPCError("socket parent is unavailable") from exc
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != os.getuid()
            or (meta.st_mode & 0o022) != 0
        ):
            raise HostIPCError("socket parent must be owned and not group/world writable")

    def _listen(self) -> tuple[socket.socket, int]:
        self._check_parent()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        created_inode: int | None = None
        try:
            listener.bind(str(self._path))  # Fails rather than replacing an existing path.
            created_inode = self._path.lstat().st_ino
            os.chmod(self._path, self._socket_mode)
            listener.listen(16)
            return listener, created_inode
        except BaseException:
            listener.close()
            if created_inode is not None:
                try:
                    meta = self._path.lstat()
                    if stat.S_ISSOCK(meta.st_mode) and meta.st_ino == created_inode:
                        self._path.unlink()
                except FileNotFoundError:
                    pass
            raise

    def _cleanup(self, listener: socket.socket, inode: int) -> None:
        listener.close()
        try:
            meta = self._path.lstat()
            if stat.S_ISSOCK(meta.st_mode) and meta.st_ino == inode:
                self._path.unlink()
        except FileNotFoundError:
            pass

    def _handle(self, connection: socket.socket) -> None:
        handle_connection(
            connection,
            self._service,
            max_message_bytes=self._max_bytes,
            timeout_seconds=self._timeout_seconds,
        )

    def serve_once(self, *, ready: threading.Event | None = None) -> None:
        listener, inode = self._listen()
        try:
            if ready is not None:
                ready.set()
            connection, _ = listener.accept()
            with connection:
                self._handle(connection)
        finally:
            self._cleanup(listener, inode)

    def serve_forever(self, stop: threading.Event, *, ready: threading.Event | None = None) -> None:
        """Run until explicit host-owned stop event; no background threads."""
        listener, inode = self._listen()
        listener.settimeout(0.5)
        try:
            if ready is not None:
                ready.set()
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    self._handle(connection)
        finally:
            self._cleanup(listener, inode)


class QualifiedUnixAuthorityServer(UnixAuthorityServer):
    """Host-launched, per-message kernel-credential authorization endpoint.

    Requires a trusted immutable plan pinned to dedicated model UID/PID/start
    evidence and a separate service OS identity. The plan is verified at
    startup, *before* socket creation. Model-side UID/SID/PID claims are never
    parsed as authority. Linux-only; no unqualified Windows/TCP fallback.

    The host may pre-provision the Unix socket's group through its directory,
    or explicitly bind it to a dedicated model group at startup. Group access
    is not identity admission: exact UID and live PID/start must still match.
    """

    def __init__(
        self,
        socket_path: str | Path,
        service: UnifiedAuthorizationService,
        *,
        plan: HostPeerIsolationPlan,
        socket_group_id: int | None = None,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
        timeout_seconds: float = 5.0,
    ) -> None:
        if type(plan) is not HostPeerIsolationPlan or plan.platform != "linux":
            raise PeerIsolationDenied("qualified Unix endpoint requires host Linux plan")
        if type(service) is not UnifiedAuthorizationService:
            raise HostIPCError(
                "qualified Unix endpoint requires coherent unified authorization service"
            )
        if service._unqualified_in_process_fixture:
            raise HostIPCError(
                "qualified Unix endpoint requires independently isolated provider RPC"
            )
        if service._authority.bindings is not plan.bindings:
            raise HostIPCError("qualified service and peer admission use different host snapshots")
        if socket_group_id is not None and (
            type(socket_group_id) is not int or socket_group_id < 0
        ):
            raise ValueError("socket_group_id must be a host-provisioned integer")
        super().__init__(
            socket_path,
            service,
            max_message_bytes=max_message_bytes,
            timeout_seconds=timeout_seconds,
            socket_mode=0o660,
        )
        self._peer_plan = plan
        self._socket_gid = socket_group_id

    def _listen(self) -> tuple[socket.socket, int]:
        self._peer_plan.assert_host_process_identity()
        listener, inode = super()._listen()
        try:
            # Linux passes SO_PASSCRED to accepted sockets. Set it on the
            # listener BEFORE accept: a model may write immediately after
            # connecting, before the daemon enters its per-peer reader.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            if self._socket_gid is not None:
                meta = self._path.lstat()
                if not stat.S_ISSOCK(meta.st_mode) or meta.st_ino != inode:
                    raise HostIPCError("qualified socket identity changed")
                os.chown(self._path, -1, self._socket_gid, follow_symlinks=False)
        except BaseException:
            self._cleanup(listener, inode)
            raise
        return listener, inode

    def _handle(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(self._timeout_seconds)
            principal, request = receive_authenticated_linux_frame(
                connection, self._peer_plan, max_message_bytes=self._max_bytes
            )
            response = _execute_request(self._service, principal.peer_key, request)
        except Exception:
            response = _DENIED
        try:
            connection.sendall(response)
        except (OSError, TimeoutError):
            pass
