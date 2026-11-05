"""Restricted Windows named-pipe entry point for the host authorization service.

Source-only until tested on Windows with real dedicated model account SIDs,
service credentials, pipe DACL readback, process isolation and provider custody.
Native construction currently fails closed: provider custody RPC uses Linux
AF_UNIX/SO_PEERCRED only, and no qualified Windows provider transport exists.
No TCP or caller-provided identity fallback exists. The native implementation
uses overlapped I/O for bounded connect/read/write; CreateNamedPipe's default
timeout does *not* bound a synchronous ConnectNamedPipe.

References (Microsoft Win32 primary documentation):
  CreateNamedPipeW / PIPE_REJECT_REMOTE_CLIENTS / FILE_FLAG_FIRST_PIPE_INSTANCE
  Named Pipe Security and Access Rights
  ImpersonateNamedPipeClient / RevertToSelf
  Synchronous and Overlapped Pipe I/O / CancelIoEx
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import re
import sys
from types import MappingProxyType
from typing import Any

from .ipc import _decode_request
from .windows_peer import (
    WindowsPeerUnavailable,
    authenticated_named_pipe_peer,
    principal_key_for_sid,
)


class WindowsPipeUnavailable(PermissionError):
    """A secure named-pipe endpoint or client could not be established."""


class WindowsProviderTransportUnavailable(WindowsPipeUnavailable):
    """Physical Windows provider custody transport has not been qualified."""


_PIPE_RE = re.compile(r"\\\\\.\\pipe\\VeraHostAuthz-[A-Za-z0-9_-]{1,60}\Z", re.ASCII)
_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,15}[0-9]+\Z", re.ASCII)
_FORBIDDEN_MODEL_SIDS = frozenset({
    "S-1-0-0", "S-1-1-0", "S-1-5-2", "S-1-5-7", "S-1-5-11",
    "S-1-5-18", "S-1-5-19", "S-1-5-20", "S-1-5-32-544",
    "S-1-5-32-545",
})
_FORBIDDEN_HOST_SIDS = frozenset({
    "S-1-0-0", "S-1-1-0", "S-1-5-2", "S-1-5-7", "S-1-5-11",
    "S-1-5-19", "S-1-5-20", "S-1-5-32-544", "S-1-5-32-545",
})
_DENIED_RESPONSE = b'{"ok":false,"error":"denied"}\n'
_MAX_RESPONSE = 8192


def build_pipe_security_descriptor(host_sid: str, client_sids: tuple[str, ...]) -> str:
    """Protected, explicit DACL: only host full; model SIDs data read/write.

    Client access mask 0x00120003 grants READ_CONTROL, SYNCHRONIZE,
    FILE_READ_DATA and FILE_WRITE_DATA, but NOT FILE_CREATE_PIPE_INSTANCE
    (0x0004). Host launcher must separately establish each dedicated SID;
    broad groups, service identities and same-SID model reuse are rejected.
    """
    if (
        type(host_sid) is not str
        or _SID_RE.fullmatch(host_sid) is None
        or host_sid in _FORBIDDEN_HOST_SIDS
    ):
        raise WindowsPipeUnavailable("invalid host SID")
    if type(client_sids) is not tuple or not client_sids:
        raise WindowsPipeUnavailable("explicit distinct model client SIDs required")
    if len(client_sids) > 32:
        raise WindowsPipeUnavailable("too many client principals")
    seen: set[str] = set()
    for sid in client_sids:
        if (
            type(sid) is not str
            or _SID_RE.fullmatch(sid) is None
            or sid in _FORBIDDEN_MODEL_SIDS
            or sid == host_sid
            or sid in seen
        ):
            raise WindowsPipeUnavailable("invalid, shared or privileged client SID")
        principal_key_for_sid(sid)
        seen.add(sid)
    # NU = NETWORK, AN = ANONYMOUS; P = protected DACL/no inheritance.
    return (
        "D:P(D;;GA;;;NU)(D;;GA;;;AN)"
        + f"(A;;FA;;;{host_sid})"
        + "".join(f"(A;;0x00120003;;;{sid})" for sid in client_sids)
    )


def _require_coherent_service(service: Any, client_keys: frozenset[str]) -> None:
    """Native listener must never expose the legacy in-process callback path.

    This is a construction guard, not verification that the Windows launcher
    has actually isolated the host, external witness and provider processes.
    """
    from .bindings import HostBindingSnapshot
    from .provider_rpc import ProviderCustodyRPCClient
    from .unified_authority import UnifiedHostAuthority
    from .unified_service import UnifiedAuthorizationService

    if type(service) is not UnifiedAuthorizationService:
        raise WindowsPipeUnavailable(
            "native listener requires exact coherent UnifiedAuthorizationService"
        )
    if service._unqualified_in_process_fixture is not False:
        raise WindowsPipeUnavailable("in-process provider fixture forbidden")
    authority = service._authority
    if type(authority) is not UnifiedHostAuthority:
        raise WindowsPipeUnavailable("coherent service needs exact host authority")
    bindings = getattr(authority, "bindings", None)
    if type(bindings) is not HostBindingSnapshot:
        raise WindowsPipeUnavailable("coherent service lacks exact host bindings")
    if set(bindings.principals) != client_keys:
        raise WindowsPipeUnavailable("named-pipe DACL and host principals differ")
    clients = service._clients
    if (
        type(clients) is not MappingProxyType
        or set(clients) != set(bindings.providers)
        or any(type(client) is not ProviderCustodyRPCClient for client in clients.values())
    ):
        raise WindowsPipeUnavailable("coherent service needs isolated provider RPC clients")


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class _NativeWindowsPipeAPI:
    """Host-only Win32 adapter. Never instantiated on non-Windows systems."""

    ERROR_IO_PENDING = 997
    ERROR_PIPE_CONNECTED = 535
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 258
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise WindowsPipeUnavailable("Windows API unavailable")
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.a = ctypes.WinDLL("advapi32", use_last_error=True)
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
        ]
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        self.k.LocalFree.argtypes = [ctypes.c_void_p]
        self.k.LocalFree.restype = ctypes.c_void_p
        self.k.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, ctypes.POINTER(_SECURITY_ATTRIBUTES),
        ]
        self.k.CreateNamedPipeW.restype = wintypes.HANDLE
        self.k.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
        self.k.ConnectNamedPipe.restype = wintypes.BOOL
        self.k.ReadFile.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(_OVERLAPPED),
        ]
        self.k.ReadFile.restype = wintypes.BOOL
        self.k.WriteFile.argtypes = self.k.ReadFile.argtypes
        self.k.WriteFile.restype = wintypes.BOOL
        self.k.GetOverlappedResult.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED),
            ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
        ]
        self.k.GetOverlappedResult.restype = wintypes.BOOL
        self.k.CreateEventW.argtypes = [
            ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
        ]
        self.k.CreateEventW.restype = wintypes.HANDLE
        self.k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.k.WaitForSingleObject.restype = wintypes.DWORD
        self.k.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
        self.k.CancelIoEx.restype = wintypes.BOOL
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k.CloseHandle.restype = wintypes.BOOL
        self.k.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        self.k.DisconnectNamedPipe.restype = wintypes.BOOL

    def create_pipe(self, name: str, sddl: str, max_bytes: int) -> int:
        descriptor = ctypes.c_void_p()
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise WindowsPipeUnavailable("explicit pipe DACL conversion failed")
        attrs = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), descriptor, False)
        try:
            handle = self.k.CreateNamedPipeW(
                name,
                0x00000003 | 0x00080000 | 0x40000000,  # DUPLEX, FIRST, OVERLAPPED
                0x00000004 | 0x00000002 | 0x00000008,  # MESSAGE, READMODE, REJECT_REMOTE
                1, max_bytes, max_bytes, 5000, ctypes.byref(attrs),
            )
        finally:
            self.k.LocalFree(descriptor)
        if handle in (None, 0, self.INVALID_HANDLE_VALUE):
            raise WindowsPipeUnavailable("restricted named pipe creation failed")
        return int(handle)

    def _overlapped_event(self) -> tuple[_OVERLAPPED, int]:
        event = self.k.CreateEventW(None, True, False, None)
        if event in (None, 0, self.INVALID_HANDLE_VALUE):
            raise WindowsPipeUnavailable("overlapped event creation failed")
        overlap = _OVERLAPPED()
        overlap.hEvent = event
        return overlap, int(event)

    def _await(self, handle: int, overlap: _OVERLAPPED, timeout_ms: int) -> int:
        wait = self.k.WaitForSingleObject(overlap.hEvent, timeout_ms)
        count = wintypes.DWORD()
        if wait == self.WAIT_TIMEOUT:
            self.k.CancelIoEx(handle, ctypes.byref(overlap))
            # An overlapped structure cannot be freed while kernel I/O may
            # still write into it. Failure to drain cancellation is fatal.
            drained = self.k.WaitForSingleObject(overlap.hEvent, 1000)
            if drained != self.WAIT_OBJECT_0:
                os._exit(71)
            raise WindowsPipeUnavailable("named pipe operation timed out")
        if wait != self.WAIT_OBJECT_0:
            self.k.CancelIoEx(handle, ctypes.byref(overlap))
            drained = self.k.WaitForSingleObject(overlap.hEvent, 1000)
            if drained != self.WAIT_OBJECT_0:
                os._exit(71)
            raise WindowsPipeUnavailable("named pipe wait failed")
        if not self.k.GetOverlappedResult(
            handle, ctypes.byref(overlap), ctypes.byref(count), False
        ):
            raise WindowsPipeUnavailable("named pipe overlapped operation failed")
        return int(count.value)

    def connect(self, handle: int, timeout_ms: int) -> None:
        overlap, event = self._overlapped_event()
        try:
            if self.k.ConnectNamedPipe(handle, ctypes.byref(overlap)):
                return
            last_error = ctypes.get_last_error()
            if last_error == self.ERROR_PIPE_CONNECTED:
                return
            if last_error != self.ERROR_IO_PENDING:
                raise WindowsPipeUnavailable("named pipe connection failed")
            self._await(handle, overlap, timeout_ms)
        finally:
            self.k.CloseHandle(event)

    def read_message(self, handle: int, max_bytes: int, timeout_ms: int) -> bytes:
        buffer = ctypes.create_string_buffer(max_bytes)
        count = wintypes.DWORD()
        overlap, event = self._overlapped_event()
        try:
            if self.k.ReadFile(
                handle, buffer, max_bytes, ctypes.byref(count), ctypes.byref(overlap)
            ):
                size = count.value
            elif ctypes.get_last_error() == self.ERROR_IO_PENDING:
                size = self._await(handle, overlap, timeout_ms)
            else:
                raise WindowsPipeUnavailable("named pipe read failed")
            if size <= 0 or size >= max_bytes:
                raise WindowsPipeUnavailable("empty or oversized client message")
            return bytes(buffer.raw[:size])
        finally:
            self.k.CloseHandle(event)

    def authenticated_peer(self, handle: int) -> str:
        return authenticated_named_pipe_peer(handle, client_message_read=True)

    def write_message(self, handle: int, response: bytes, timeout_ms: int) -> None:
        payload = ctypes.create_string_buffer(response)
        count = wintypes.DWORD()
        overlap, event = self._overlapped_event()
        try:
            if self.k.WriteFile(
                handle, payload, len(response), ctypes.byref(count), ctypes.byref(overlap)
            ):
                sent = count.value
            elif ctypes.get_last_error() == self.ERROR_IO_PENDING:
                sent = self._await(handle, overlap, timeout_ms)
            else:
                raise WindowsPipeUnavailable("named pipe write failed")
            if sent != len(response):
                raise WindowsPipeUnavailable("partial named pipe reply")
        finally:
            self.k.CloseHandle(event)

    def disconnect(self, handle: int) -> None:
        self.k.DisconnectNamedPipe(handle)

    def close(self, handle: int) -> None:
        self.k.CloseHandle(handle)


class WindowsAuthorityPipeServer:
    """Bounded one-request host pipe, no issuer/provider/admin RPC endpoints.

    This server is source-only and deliberately does not own or mint grants,
    consent, signatures, provider credentials, or an antirollback witness.
    The host must isolate the service process and provision private SIDs.
    `_api` exists only to run synthetic API tests on non-Windows platforms;
    a host launcher must not supply a non-native adapter in production.
    """

    def __init__(
        self,
        pipe_name: str,
        host_sid: str,
        client_sids: tuple[str, ...],
        service: Any,
        *,
        timeout_ms: int = 5000,
        max_message_bytes: int = 65536,
        _api: Any | None = None,
    ) -> None:
        if type(pipe_name) is not str or _PIPE_RE.fullmatch(pipe_name) is None:
            raise WindowsPipeUnavailable("pipe name must be local restricted namespace")
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 5000:
            raise ValueError("timeout_ms must be a bounded exact int")
        if type(max_message_bytes) is not int or not 256 <= max_message_bytes <= 65536:
            raise ValueError("max_message_bytes must be 256..65536")
        sddl = build_pipe_security_descriptor(host_sid, client_sids)
        self._pipe_name = pipe_name
        self._sddl = sddl
        self._client_keys = frozenset("sid:" + sid for sid in client_sids)
        self._service = service
        self._timeout_ms = timeout_ms
        self._max_bytes = max_message_bytes
        if _api is not None and sys.platform == "win32":
            raise WindowsPipeUnavailable(
                "native Windows listener cannot accept a substituted API"
            )
        if _api is None:
            _require_coherent_service(service, self._client_keys)
            if sys.platform == "win32":
                raise WindowsProviderTransportUnavailable(
                    "native Windows provider custody RPC unavailable; "
                    "Linux AF_UNIX client is not a Windows transport"
                )
        self._api = _NativeWindowsPipeAPI() if _api is None else _api

    def serve_once(self) -> None:
        api = self._api
        handle = api.create_pipe(self._pipe_name, self._sddl, self._max_bytes)
        connected = False
        try:
            api.connect(handle, self._timeout_ms)
            connected = True
            message = api.read_message(handle, self._max_bytes + 1, self._timeout_ms)
            peer_key = api.authenticated_peer(handle)
            response = _DENIED_RESPONSE
            try:
                if (
                    type(peer_key) is str
                    and peer_key in self._client_keys
                    and type(message) is bytes
                    and 1 <= len(message) <= self._max_bytes
                    and message.endswith(b"\n")
                    and b"\n" not in message[:-1]
                ):
                    grant, provider, operation, payload = _decode_request(message[:-1])
                    receipt = self._service.execute(
                        peer_key=peer_key,
                        signed_grant=grant,
                        provider_id=provider,
                        operation=operation,
                        request_payload=payload,
                    )
                    public = receipt.public_body()
                    if type(public) is dict:
                        encoded = (json.dumps(
                            {"ok": True, "receipt": public},
                            ensure_ascii=False, allow_nan=False,
                            sort_keys=True, separators=(",", ":"),
                        ) + "\n").encode("utf-8")
                        if len(encoded) <= _MAX_RESPONSE:
                            response = encoded
            except Exception:
                # Never disclose authority, participant, provider or key info.
                pass
            api.write_message(handle, response, self._timeout_ms)
        finally:
            try:
                if connected:
                    api.disconnect(handle)
            finally:
                api.close(handle)
