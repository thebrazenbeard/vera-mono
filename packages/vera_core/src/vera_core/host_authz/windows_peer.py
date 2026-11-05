"""Windows named-pipe client identity extraction; not a pipe server.

This module is intentionally fail-closed. It is useful only after a dedicated
privileged host service has securely created a LOCAL named pipe with an
explicit restrictive DACL, read one client message, and kept untrusted model
code out of the host process. A model and another model sharing one Windows
account SID remain indistinguishable: the host must provision separate OS
principals (or independently qualified isolation and attestation).

Windows API references:
* ImpersonateNamedPipeClient / RevertToSelf (Microsoft Win32)
* OpenThreadToken / GetTokenInformation(TokenUser) (Microsoft Win32)
* Named Pipe Security and Access Rights (Microsoft Win32)

This source has not been run or qualified on Lappy or VN1. Never substitute a
caller-supplied SID, process name, model ID, or local TCP bearer token.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import sys


class WindowsPeerUnavailable(PermissionError):
    """No authentic Windows peer identity was established."""


_SID_RE = re.compile(r"S-1-(?:[0-9]+-){1,15}[0-9]+\Z", re.ASCII)
_DENIED_SIDS = frozenset({
    "S-1-0-0",   # Null SID
    "S-1-5-7",   # Anonymous Logon
    "S-1-5-18",  # LocalSystem: not a model principal
    "S-1-5-19",  # LocalService: shared service identity
    "S-1-5-20",  # NetworkService: shared service identity
})
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


def principal_key_for_sid(sid: str) -> str:
    """Canonical host peer key, not an authentication mechanism by itself."""
    if (
        type(sid) is not str
        or len(sid) > 184
        or _SID_RE.fullmatch(sid) is None
        or sid in _DENIED_SIDS
    ):
        raise WindowsPeerUnavailable("invalid or anonymous Windows SID")
    return f"sid:{sid}"


def authenticated_named_pipe_peer(
    server_pipe_handle: int, *, client_message_read: bool
) -> str:
    """Return kernel token-derived client SID after a server-side pipe read.

    CRITICAL: ImpersonateNamedPipeClient uses the *last message read* on the
    named pipe; callers must invoke this on the same dedicated request thread
    immediately following a successful ReadFile and prior to any privileged
    work. Failure at any stage denies access. RevertToSelf failure is fatal to
    the process, per Microsoft guidance: remaining impersonated is unsafe.

    This function only authenticates a SID. Pipe creation, DACL, remote-client
    rejection, complete request framing, unique model-account provisioning,
    and service/provider custody are separate deployment prerequisites.
    """
    if type(server_pipe_handle) is not int or server_pipe_handle <= 0:
        raise WindowsPeerUnavailable("invalid server pipe handle")
    if client_message_read is not True:
        raise WindowsPeerUnavailable("client message was not read")
    if sys.platform != "win32":
        raise WindowsPeerUnavailable("Windows native token API unavailable")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentThread.argtypes = []
    kernel32.GetCurrentThread.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.ImpersonateNamedPipeClient.argtypes = [wintypes.HANDLE]
    advapi32.ImpersonateNamedPipeClient.restype = wintypes.BOOL
    advapi32.RevertToSelf.argtypes = []
    advapi32.RevertToSelf.restype = wintypes.BOOL
    advapi32.OpenThreadToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenThreadToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    if not advapi32.ImpersonateNamedPipeClient(wintypes.HANDLE(server_pipe_handle)):
        raise WindowsPeerUnavailable("named pipe client impersonation failed")

    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenThreadToken(
            # OpenAsSelf=True makes this access check as the host process,
            # allowing SecurityIdentification-level clients. The token
            # returned is STILL the impersonated client's token.
            kernel32.GetCurrentThread(), _TOKEN_QUERY, True, ctypes.byref(token)
        ):
            raise WindowsPeerUnavailable("client impersonation token unavailable")
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, _TOKEN_USER, None, 0, ctypes.byref(needed)
        )
        if not ctypes.sizeof(_TokenUser) <= needed.value <= 65536:
            raise WindowsPeerUnavailable("client token size is invalid")
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token, _TOKEN_USER, buffer, needed.value, ctypes.byref(needed)
        ):
            raise WindowsPeerUnavailable("client token user unavailable")
        user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        if not user.User.Sid:
            raise WindowsPeerUnavailable("client token lacks user SID")
        sid_string = ctypes.c_wchar_p()
        if not advapi32.ConvertSidToStringSidW(
            user.User.Sid, ctypes.byref(sid_string)
        ):
            raise WindowsPeerUnavailable("client SID conversion failed")
        try:
            return principal_key_for_sid(sid_string.value)
        finally:
            kernel32.LocalFree(ctypes.cast(sid_string, ctypes.c_void_p))
    finally:
        try:
            if token.value:
                kernel32.CloseHandle(token)
        finally:
            if not advapi32.RevertToSelf():
                # Microsoft requires shutdown if reversion fails: the thread
                # may still be running under an untrusted client token.
                os._exit(70)
