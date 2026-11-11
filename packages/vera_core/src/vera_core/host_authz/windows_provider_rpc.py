"""Fail-closed Windows named-pipe transport for isolated provider custody.

This is a SOURCE CANDIDATE, not a deployed Windows authority. The provider
must be a separately provisioned OS account/process that owns its effect
credentials, durable one-use fence and provider ACK signing key. A host-side
RPC client owns ONLY public verification roots and an exact OS process pin.

Windows token SIDs, process IDs and creation FILETIMEs are obtained through
Win32; model-request JSON never supplies a trusted principal. The protected
one-instance local pipe denies anonymous/network clients and gives the exact
provider SID full control and exact host SID data-only access. Both sides
authenticate the opposite process through the kernel before dispatch.

No TCP fallback, caller-provided SID assertion or cross-platform native
fallback exists. Synthetic ``_api`` injection is available on non-Windows
test systems only, and is forbidden on native Windows. Real host deployment
also requires Windows-qualified provider fence and UnifiedHostAuthority
storage, neither of which exists in this source candidate.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from .provider_custody import COMMAND_CONTEXT, COMMAND_SCHEMA, ProviderCustodyWorker
from .provider_rpc import (
    _ACK_CONTEXT, _ACK_SCHEMA, _MAX_FRAME, _WIRE_SCHEMA,
    _b64, _decode, _unb64,
)
from .service import ProviderAcknowledgement
from .unified_authority import WitnessEventReceipt
from .windows_peer import authenticated_named_pipe_peer
from .windows_pipe import _NativeWindowsPipeAPI


class WindowsProviderRPCUnavailable(PermissionError):
    """Cannot establish a kernel-authenticated and bounded provider pipe."""


_PIPE_RE = re.compile(r"\\\\\.\\pipe\\VeraProviderAuthz-[A-Za-z0-9_-]{1,60}\Z", re.ASCII)
_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,15}[0-9]+\Z", re.ASCII)
_BROAD_SIDS = frozenset({
    "S-1-0-0", "S-1-1-0", "S-1-5-2", "S-1-5-7", "S-1-5-11",
    "S-1-5-19", "S-1-5-20", "S-1-5-32-544", "S-1-5-32-545",
})
_MAX_MESSAGE = min(_MAX_FRAME, 65536)


def _valid_sid(value: Any, *, provider: bool) -> str:
    if (type(value) is not str or len(value) > 184
            or _SID_RE.fullmatch(value) is None or value in _BROAD_SIDS
            or value == "S-1-5-18"):
        raise WindowsProviderRPCUnavailable("invalid dedicated process SID")
    return value


def _valid_pipe(name: Any) -> str:
    if type(name) is not str or _PIPE_RE.fullmatch(name) is None:
        raise WindowsProviderRPCUnavailable("provider pipe must be an exact local name")
    return name


def _pin(pid: Any, created: Any) -> tuple[int, int]:
    # Windows creation time is an absolute FILETIME, not a model-provided age.
    if (type(pid) is not int or pid < 4 or type(created) is not int
            or not 0 < created < (1 << 64)):
        raise WindowsProviderRPCUnavailable("provider OS process pin required")
    return pid, created


def build_provider_pipe_security_descriptor(provider_sid: str, host_sid: str) -> str:
    """Explicit protected provider DACL; host gets data-only, not pipe creation."""
    provider_sid = _valid_sid(provider_sid, provider=True)
    host_sid = _valid_sid(host_sid, provider=False)
    if provider_sid == host_sid:
        raise WindowsProviderRPCUnavailable("host and provider cannot share SID")
    return (
        "D:P(D;;GA;;;NU)(D;;GA;;;AN)"
        + f"(A;;FA;;;{provider_sid})"
        + f"(A;;0x00120003;;;{host_sid})"
    )


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


class _NativeWindowsProviderAPI(_NativeWindowsPipeAPI):
    """Real Win32 adapter; constructed only on native Windows, never on Linux."""

    def __init__(self) -> None:
        super().__init__()
        self.k.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        self.k.GetNamedPipeClientProcessId.restype = wintypes.BOOL
        self.k.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
        self.k.GetNamedPipeServerProcessId.restype = wintypes.BOOL
        self.k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.k.OpenProcess.restype = wintypes.HANDLE
        self.k.GetProcessTimes.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        self.k.GetProcessTimes.restype = wintypes.BOOL
        self.k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        self.k.WaitNamedPipeW.restype = wintypes.BOOL
        self.k.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        self.k.CreateFileW.restype = wintypes.HANDLE
        self.a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        self.a.OpenProcessToken.restype = wintypes.BOOL
        self.a.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ]
        self.a.GetTokenInformation.restype = wintypes.BOOL
        self.a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        self.a.ConvertSidToStringSidW.restype = wintypes.BOOL

    def _process_identity(self, pid: int) -> tuple[str, int, int]:
        # 0x1000 = PROCESS_QUERY_LIMITED_INFORMATION; 0x0008 = TOKEN_QUERY.
        process = self.k.OpenProcess(0x1000, False, pid)
        if not process:
            raise WindowsProviderRPCUnavailable("peer process cannot be inspected")
        token = wintypes.HANDLE()
        try:
            creation = wintypes.FILETIME()
            exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(3))
            if not self.k.GetProcessTimes(process, ctypes.byref(creation),
                                          ctypes.byref(exit_time), ctypes.byref(kernel_time),
                                          ctypes.byref(user_time)):
                raise WindowsProviderRPCUnavailable("peer process creation time unavailable")
            created = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
            if not self.a.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
                raise WindowsProviderRPCUnavailable("peer token cannot be inspected")
            needed = wintypes.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if not ctypes.sizeof(_TokenUser) <= needed.value <= 65536:
                raise WindowsProviderRPCUnavailable("peer token length invalid")
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.a.GetTokenInformation(token, 1, buffer, needed.value, ctypes.byref(needed)):
                raise WindowsProviderRPCUnavailable("peer token user unavailable")
            user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
            if not user.User.Sid:
                raise WindowsProviderRPCUnavailable("peer token lacks SID")
            converted = ctypes.c_wchar_p()
            if not self.a.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(converted)):
                raise WindowsProviderRPCUnavailable("peer token SID conversion failed")
            try:
                return converted.value, pid, created
            finally:
                self.k.LocalFree(ctypes.cast(converted, ctypes.c_void_p))
        finally:
            if token.value:
                self.k.CloseHandle(token)
            self.k.CloseHandle(process)

    def _pipe_process(self, handle: int, *, server: bool) -> tuple[str, int, int]:
        pid = wintypes.ULONG()
        fn = (self.k.GetNamedPipeServerProcessId if server else self.k.GetNamedPipeClientProcessId)
        if not fn(wintypes.HANDLE(handle), ctypes.byref(pid)) or pid.value < 4:
            raise WindowsProviderRPCUnavailable("kernel named-pipe peer PID unavailable")
        return self._process_identity(int(pid.value))

    def authenticated_host(self, handle: int) -> tuple[str, int, int]:
        # Impersonation is performed immediately after a complete ReadFile.
        token_sid = authenticated_named_pipe_peer(handle, client_message_read=True)
        process_sid, pid, created = self._pipe_process(handle, server=False)
        if token_sid != "sid:" + process_sid:
            raise WindowsProviderRPCUnavailable("pipe client token/process SID disagreement")
        return process_sid, pid, created

    def authenticated_provider(self, handle: int) -> tuple[str, int, int]:
        return self._pipe_process(handle, server=True)

    def current_process_identity(self) -> tuple[str, int, int]:
        return self._process_identity(os.getpid())

    def open_client(self, name: str, timeout_ms: int) -> int:
        if not self.k.WaitNamedPipeW(name, timeout_ms):
            raise WindowsProviderRPCUnavailable("provider named pipe unavailable")
        # Exact data read/write + READ_CONTROL/SYNCHRONIZE. GENERIC_WRITE
        # expands to FILE_APPEND_DATA (0x4), which is ALSO the named-pipe
        # FILE_CREATE_PIPE_INSTANCE right and deliberately excluded by DACL.
        # OPEN_EXISTING, OVERLAPPED, Identification SQOS.
        handle = self.k.CreateFileW(name, 0x00120003, 0, None, 3,
                                    0x40000000 | 0x00100000 | 0x00010000, None)
        if handle in (None, 0, self.INVALID_HANDLE_VALUE):
            raise WindowsProviderRPCUnavailable("provider pipe opening denied")
        return int(handle)


def _native_api(api: Any | None) -> Any:
    if sys.platform == "win32":
        if api is not None:
            raise WindowsProviderRPCUnavailable("native Windows forbids substituted API")
        return _NativeWindowsProviderAPI()
    if api is None:
        raise WindowsProviderRPCUnavailable("Windows provider RPC native API unavailable")
    return api


class WindowsProviderCustodyRPCServer:
    """Provider-owned one-request pipe; no model-visible identity or callback RPC."""

    def __init__(self, pipe_name: str, *, provider_sid: str, host_sid: str,
                 host_pid: int, host_created: int, worker: ProviderCustodyWorker,
                 timeout_ms: int = 5000, _api: Any | None = None):
        self.pipe_name = _valid_pipe(pipe_name)
        self.sddl = build_provider_pipe_security_descriptor(provider_sid, host_sid)
        self.provider_sid = provider_sid
        self.host_sid = host_sid
        self.host_pid, self.host_created = _pin(host_pid, host_created)
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 5000:
            raise WindowsProviderRPCUnavailable("provider timeout must be bounded")
        self.timeout_ms = timeout_ms
        self.api = _native_api(_api)
        if sys.platform == "win32" and type(worker) is not ProviderCustodyWorker:
            raise WindowsProviderRPCUnavailable("native provider needs exact custody worker")
        if sys.platform != "win32" and not hasattr(worker, "dispatch"):
            raise WindowsProviderRPCUnavailable("test provider needs dispatch interface")
        self.worker = worker

    def serve_once(self) -> None:
        api = self.api
        # Pipe creation alone does not prove its owner: another process could
        # pre-create the name with an equally restrictive-looking DACL.
        # Confirm actual OS token ownership before opening an effect listener.
        if api.current_process_identity()[0] != self.provider_sid:
            raise WindowsProviderRPCUnavailable("provider daemon is not under pinned SID")
        handle = api.create_pipe(self.pipe_name, self.sddl, _MAX_MESSAGE)
        connected = False
        try:
            api.connect(handle, self.timeout_ms)
            connected = True
            request = api.read_message(handle, _MAX_MESSAGE + 1, self.timeout_ms)
            peer = api.authenticated_host(handle)
            if (peer != (self.host_sid, self.host_pid, self.host_created)
                    or type(request) is not bytes or len(request) > _MAX_MESSAGE):
                raise WindowsProviderRPCUnavailable("provider command peer was not pinned host")
            response = canonical_json_bytes({"schema": _ACK_SCHEMA, "ok": False})
            try:
                body = _decode(request)
                if set(body) != {"schema", "command", "start_receipt", "start_event"} or body["schema"] != _WIRE_SCHEMA:
                    raise WindowsProviderRPCUnavailable("unknown provider RPC command")
                lease = WitnessEventReceipt(raw=_unb64(body["start_receipt"]),
                                            event=_unb64(body["start_event"]), body={})
                command = _unb64(body["command"])
                if sys.platform == "win32":
                    ack = ProviderCustodyWorker.dispatch(self.worker, command, start_lease=lease)
                else:
                    ack = self.worker.dispatch(command, start_lease=lease)
                if type(ack) is not ProviderAcknowledgement:
                    raise WindowsProviderRPCUnavailable("provider did not issue exact ACK")
                response = canonical_json_bytes({
                    "schema": _ACK_SCHEMA, "ok": True,
                    "ack": {**ack.signed_body(), "signature": _b64(ack.receipt_signature)},
                })
            except Exception:
                # Provider status is unknown after a rejected or interrupted
                # attempt. The authority must not replay this START lease.
                pass
            api.write_message(handle, response, self.timeout_ms)
        finally:
            try:
                if connected:
                    api.disconnect(handle)
            finally:
                api.close(handle)


class WindowsProviderCustodyRPCClient:
    """Host-owned pinned endpoint; provider private key is never present here."""

    __slots__ = ("pipe_name", "host_sid", "provider_sid", "provider_pid", "provider_created",
                 "provider_id", "provider_instance_id", "host_id", "epoch", "receipt_public_key_bytes",
                 "host_command_public_key_bytes", "witness_start_public_key", "witness_leader_epoch",
                 "timeout_ms", "_api", "_sealed")

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("provider endpoint binding is sealed")
        object.__setattr__(self, name, value)

    def __init__(self, pipe_name: str, *, host_sid: str, provider_sid: str,
                 provider_pid: int, provider_created: int, provider_id: str,
                 provider_instance_id: str, host_id: str, epoch: int,
                 receipt_public_key_bytes: bytes, host_command_public_key_bytes: bytes,
                 witness_start_public_key: bytes, witness_leader_epoch: int,
                 timeout_ms: int = 5000, _api: Any | None = None):
        self.pipe_name = _valid_pipe(pipe_name)
        build_provider_pipe_security_descriptor(provider_sid, host_sid)
        self.host_sid, self.provider_sid = host_sid, provider_sid
        self.provider_pid, self.provider_created = _pin(provider_pid, provider_created)
        if any(type(v) is not str or not v or v != v.strip() for v in
               (provider_id, provider_instance_id, host_id)):
            raise WindowsProviderRPCUnavailable("invalid pinned provider identity")
        if (type(epoch) is not int or epoch < 1 or type(witness_leader_epoch) is not int
                or witness_leader_epoch < 1):
            raise WindowsProviderRPCUnavailable("invalid pinned epochs")
        for key in (receipt_public_key_bytes, host_command_public_key_bytes, witness_start_public_key):
            if type(key) is not bytes or len(key) != 32:
                raise WindowsProviderRPCUnavailable("requires exact pinned Ed25519 roots")
        if type(timeout_ms) is not int or not 100 <= timeout_ms <= 5000:
            raise WindowsProviderRPCUnavailable("timeout must be bounded")
        self.provider_id, self.provider_instance_id = provider_id, provider_instance_id
        self.host_id, self.epoch = host_id, epoch
        self.receipt_public_key_bytes = receipt_public_key_bytes
        self.host_command_public_key_bytes = host_command_public_key_bytes
        self.witness_start_public_key = witness_start_public_key
        self.witness_leader_epoch = witness_leader_epoch
        self.timeout_ms = timeout_ms
        self._api = _native_api(_api)
        self._sealed = True

    def dispatch(self, signed_command: bytes, *, start_lease: WitnessEventReceipt) -> ProviderAcknowledgement:
        if type(signed_command) is not bytes or type(start_lease) is not WitnessEventReceipt:
            raise WindowsProviderRPCUnavailable("requires exact signed command and START lease")
        try:
            signed = _decode(signed_command)
            if set(signed) != {"schema", "body", "signature"} or signed["schema"] != COMMAND_SCHEMA:
                raise WindowsProviderRPCUnavailable("host command envelope invalid")
            command_body = signed["body"]
            if type(command_body) is not dict or type(command_body.get("dispatch")) is not dict:
                raise WindowsProviderRPCUnavailable("host command body invalid")
            Ed25519PublicKey.from_public_bytes(self.host_command_public_key_bytes).verify(
                _unb64(signed["signature"]), COMMAND_CONTEXT + canonical_json_bytes(command_body),
            )
            if (command_body.get("host_id") != self.host_id
                    or command_body.get("epoch") != self.epoch
                    or command_body["dispatch"].get("provider_id") != self.provider_id
                    or command_body["dispatch"].get("provider_instance_id") != self.provider_instance_id):
                raise WindowsProviderRPCUnavailable("host command does not bind provider identity")
        except (InvalidSignature, TypeError, ValueError) as exc:
            raise WindowsProviderRPCUnavailable("host command signature invalid") from exc
        request = canonical_json_bytes({
            "schema": _WIRE_SCHEMA, "command": _b64(signed_command),
            "start_receipt": _b64(start_lease.raw), "start_event": _b64(start_lease.event),
        })
        if len(request) > _MAX_MESSAGE:
            raise WindowsProviderRPCUnavailable("provider command exceeds native frame bound")
        api = self._api
        handle = api.open_client(self.pipe_name, self.timeout_ms)
        try:
            if api.authenticated_provider(handle) != (
                self.provider_sid, self.provider_pid, self.provider_created
            ):
                raise WindowsProviderRPCUnavailable("provider SID/PID/creation pin failed")
            api.write_message(handle, request, self.timeout_ms)
            raw = api.read_message(handle, _MAX_MESSAGE + 1, self.timeout_ms)
        finally:
            api.close(handle)
        response = _decode(raw)
        if (set(response) != {"schema", "ok", "ack"} or response.get("schema") != _ACK_SCHEMA
                or response.get("ok") is not True):
            raise WindowsProviderRPCUnavailable("provider effect outcome unavailable")
        body = response["ack"]
        fields = {"schema", "effect_id", "provider_id", "provider_instance_id",
                  "claim_sequence", "request_digest", "provider_receipt_digest", "signature"}
        if type(body) is not dict or set(body) != fields:
            raise WindowsProviderRPCUnavailable("provider ACK malformed")
        try:
            ack = ProviderAcknowledgement(
                effect_id=body["effect_id"], provider_id=body["provider_id"],
                provider_instance_id=body["provider_instance_id"],
                claim_sequence=body["claim_sequence"], request_digest=body["request_digest"],
                provider_receipt_digest=body["provider_receipt_digest"],
                receipt_signature=_unb64(body["signature"]),
            )
            Ed25519PublicKey.from_public_bytes(self.receipt_public_key_bytes).verify(
                ack.receipt_signature, _ACK_CONTEXT + canonical_json_bytes(ack.signed_body()))
        except (ValueError, TypeError, InvalidSignature) as exc:
            raise WindowsProviderRPCUnavailable("provider ACK was not signed by pinned key") from exc
        if (ack.provider_id, ack.provider_instance_id) != (self.provider_id, self.provider_instance_id):
            raise WindowsProviderRPCUnavailable("provider receipt identity substituted")
        dispatch = command_body["dispatch"]
        if any(getattr(ack, field) != dispatch.get(field) for field in (
            "effect_id", "claim_sequence", "request_digest"
        )):
            raise WindowsProviderRPCUnavailable("provider ACK did not bind host command")
        return ack
