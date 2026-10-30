"""Cross-platform fail-closed Windows peer-auth source tests; NOT Windows probe."""

from __future__ import annotations

import ctypes

import pytest

from vera_core.host_authz import windows_peer


@pytest.mark.parametrize("sid", [
    "S-1-0-0",  # Null SID
    "S-1-5-7",  # Anonymous
    "S-1-5-18", "S-1-5-19", "S-1-5-20",  # Shared service accounts
    "S-1-5", "s-1-5-21-32", "S-1-5-21-32 ",
    "S-1-5-21-3\\n", "SID:S-1-5-21-3", 0, None,
])
def test_malformed_and_anonymous_windows_sids_denied(sid):
    with pytest.raises(windows_peer.WindowsPeerUnavailable):
        windows_peer.principal_key_for_sid(sid)


def test_canonical_windows_sid_to_host_principal_key():
    assert windows_peer.principal_key_for_sid("S-1-5-21-123-456-789-1001") == (
        "sid:S-1-5-21-123-456-789-1001"
    )


@pytest.mark.parametrize("handle", [None, 0, -1, "3", True])
def test_rejects_invalid_pipe_handle_before_native_api(handle):
    with pytest.raises(windows_peer.WindowsPeerUnavailable):
        windows_peer.authenticated_named_pipe_peer(
            handle, client_message_read=True
        )


def test_rejects_without_prior_server_read_even_on_windows(monkeypatch):
    monkeypatch.setattr(windows_peer.sys, "platform", "win32")
    with pytest.raises(windows_peer.WindowsPeerUnavailable, match="not read"):
        windows_peer.authenticated_named_pipe_peer(
            123, client_message_read=False
        )


def test_non_windows_does_not_fall_back_to_self_reported_identity():
    with pytest.raises(windows_peer.WindowsPeerUnavailable, match="unavailable"):
        windows_peer.authenticated_named_pipe_peer(
            123, client_message_read=True
        )


def test_windows_impersonation_failure_denies_without_opening_token(monkeypatch):
    monkeypatch.setattr(windows_peer.sys, "platform", "win32")

    class _Func:
        def __init__(self, value):
            self.value = value
            self.calls = 0

        def __call__(self, *args):
            self.calls += 1
            return self.value

    class FakeKernel32:
        GetCurrentThread = _Func(55)
        CloseHandle = _Func(1)
        LocalFree = _Func(0)

    class FakeAdvapi32:
        ImpersonateNamedPipeClient = _Func(0)
        RevertToSelf = _Func(1)
        OpenThreadToken = _Func(1)
        GetTokenInformation = _Func(1)
        ConvertSidToStringSidW = _Func(1)

    fake_kernel = FakeKernel32()
    fake_advapi = FakeAdvapi32()
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, use_last_error=True: (
            fake_kernel if name == "kernel32" else fake_advapi
        ),
        raising=False,
    )
    with pytest.raises(windows_peer.WindowsPeerUnavailable, match="impersonation failed"):
        windows_peer.authenticated_named_pipe_peer(
            123, client_message_read=True
        )
    assert fake_advapi.ImpersonateNamedPipeClient.calls == 1
    assert fake_advapi.OpenThreadToken.calls == 0


def test_no_production_windows_host_qualification_is_claimed():
    # This file intentionally does not simulate a successfully authenticated
    # Windows SID. That requires a real named-pipe server, strict DACL, two
    # separate model OS principals, and a verified Lappy/VN1 host probe.
    assert callable(windows_peer.authenticated_named_pipe_peer)


@pytest.mark.parametrize("revert_success", [True, False])
def test_token_query_failure_always_reverts_or_terminates(
    monkeypatch, revert_success
):
    monkeypatch.setattr(windows_peer.sys, "platform", "win32")

    class Func:
        def __init__(self, result):
            self.result = result
            self.calls = 0
            self.last_args = None

        def __call__(self, *args):
            self.calls += 1
            self.last_args = args
            return self.result

    class Module:
        pass

    kernel = Module()
    kernel.GetCurrentThread = Func(123)
    kernel.CloseHandle = Func(1)
    kernel.LocalFree = Func(0)
    advapi = Module()
    advapi.ImpersonateNamedPipeClient = Func(1)
    advapi.RevertToSelf = Func(1 if revert_success else 0)
    advapi.OpenThreadToken = Func(0)
    advapi.GetTokenInformation = Func(0)
    advapi.ConvertSidToStringSidW = Func(0)
    monkeypatch.setattr(
        ctypes,
        "WinDLL",
        lambda name, use_last_error=True: (
            kernel if name == "kernel32" else advapi
        ),
        raising=False,
    )

    class Terminated(Exception):
        pass

    def fatal_exit(exit_code):
        assert exit_code == 70
        raise Terminated

    monkeypatch.setattr(windows_peer.os, "_exit", fatal_exit)
    if revert_success:
        with pytest.raises(windows_peer.WindowsPeerUnavailable, match="token unavailable"):
            windows_peer.authenticated_named_pipe_peer(123, client_message_read=True)
    else:
        with pytest.raises(Terminated):
            windows_peer.authenticated_named_pipe_peer(123, client_message_read=True)
    assert advapi.RevertToSelf.calls == 1
    assert advapi.GetTokenInformation.calls == 0
    assert advapi.OpenThreadToken.last_args[2] is True
