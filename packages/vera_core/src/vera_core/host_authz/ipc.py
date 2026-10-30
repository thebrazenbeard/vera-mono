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
    except Exception:
        response = _DENIED
    try:
        connection.sendall(response)
    except (OSError, TimeoutError):
        pass


class UnixAuthorityServer:
    """Synchronous bounded Unix server; no privilege or grant admin RPCs.

    `socket_path` must be inside a pre-provisioned host-owned directory whose
    permissions prevent group/world writes. The server refuses an existing
    path and only unlinks the exact socket inode it created. Production host
    provisioning, UID isolation and provider custody require separate tests.
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

    def serve_once(self, *, ready: threading.Event | None = None) -> None:
        listener, inode = self._listen()
        try:
            if ready is not None:
                ready.set()
            connection, _ = listener.accept()
            with connection:
                handle_connection(
                    connection,
                    self._service,
                    max_message_bytes=self._max_bytes,
                    timeout_seconds=self._timeout_seconds,
                )
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
                    handle_connection(
                        connection,
                        self._service,
                        max_message_bytes=self._max_bytes,
                        timeout_seconds=self._timeout_seconds,
                    )
        finally:
            self._cleanup(listener, inode)
