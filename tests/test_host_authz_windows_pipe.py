"""Windows pipe policy/sequence tests; not physical Windows qualification."""

import base64
import json
from types import MappingProxyType

import pytest

from vera_core.host_authz.windows_pipe import (
    WindowsAuthorityPipeServer,
    WindowsPipeUnavailable,
    WindowsProviderTransportUnavailable,
    build_pipe_security_descriptor,
    _require_coherent_service,
)
from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.provider_rpc import ProviderCustodyRPCClient
from vera_core.host_authz.unified_authority import UnifiedHostAuthority
from vera_core.host_authz.unified_service import UnifiedAuthorizationService


HOST = "S-1-5-18"
MODEL_A = "S-1-5-21-100-200-300-1001"
MODEL_B = "S-1-5-21-100-200-300-1002"
PIPE = r"\\.\pipe\VeraHostAuthz-test"


class FakeAPI:
    def __init__(self, message: bytes, peer: str = "sid:" + MODEL_A):
        self.message = message
        self.peer = peer
        self.actions = []
        self.fail_at = None
        self.handle = object()

    def _record(self, action):
        self.actions.append(action)
        if action == self.fail_at:
            raise WindowsPipeUnavailable("synthetic failure")

    def create_pipe(self, name, sddl, max_bytes):
        self._record("create")
        assert name == PIPE
        assert sddl.startswith("D:P")
        assert max_bytes == 65536
        return self.handle

    def connect(self, handle, timeout_ms):
        self._record("connect")
        assert handle is self.handle and timeout_ms <= 5000

    def read_message(self, handle, max_bytes, timeout_ms):
        self._record("read")
        assert handle is self.handle and max_bytes == 65536 + 1
        return self.message

    def authenticated_peer(self, handle):
        self._record("authenticate")
        assert handle is self.handle
        return self.peer

    def write_message(self, handle, response, timeout_ms):
        self._record("write")
        self.response = response

    def disconnect(self, handle):
        self._record("disconnect")

    def close(self, handle):
        self._record("close")


class FakeService:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return type("Receipt", (), {"public_body": lambda _: {"state": "ACKNOWLEDGED"}})()


def payload(**extra):
    request = {
        "signed_grant_b64": base64.b64encode(b"signed-grant").decode(),
        "provider_id": "provider-a",
        "operation": "inspect",
        "request_payload": {"value": 1},
    }
    request.update(extra)
    return (json.dumps(request) + "\n").encode()


def server(api, service=None, **kw):
    service = service or FakeService()
    return WindowsAuthorityPipeServer(
        PIPE, HOST, (MODEL_A, MODEL_B), service,
        timeout_ms=5000, max_message_bytes=65536, _api=api, **kw,
    ), service


def test_explicit_protected_dacl_excludes_public_and_creation_rights():
    sddl = build_pipe_security_descriptor(HOST, (MODEL_A, MODEL_B))
    assert sddl.startswith("D:P(D;;GA;;;NU)(D;;GA;;;AN)")
    assert f"(A;;FA;;;{HOST})" in sddl
    assert f"(A;;0x00120003;;;{MODEL_A})" in sddl
    assert f"(A;;0x00120003;;;{MODEL_B})" in sddl
    assert "WD" not in sddl and "AU" not in sddl and "BA" not in sddl
    assert "0x00120007" not in sddl  # no FILE_CREATE_PIPE_INSTANCE


def test_real_message_read_precedes_kernel_peer_auth_and_service():
    api = FakeAPI(payload())
    endpoint, service = server(api)
    endpoint.serve_once()
    assert api.actions == ["create", "connect", "read", "authenticate", "write", "disconnect", "close"]
    assert service.calls[0]["peer_key"] == "sid:" + MODEL_A
    assert service.calls[0]["signed_grant"] == b"signed-grant"
    assert json.loads(api.response)["ok"] is True


def test_unbound_or_broad_sid_is_not_an_authority():
    for client in ("sid:S-1-5-21-100-200-300-9999", "sid:S-1-5-7", "sid:S-1-1-0"):
        api = FakeAPI(payload(), peer=client)
        endpoint, service = server(api)
        endpoint.serve_once()
        assert not service.calls
        assert json.loads(api.response)["ok"] is False


@pytest.mark.parametrize("bad", [
    r"\\attacker\pipe\VeraHostAuthz-test", r"\\.\pipe\Other",
    r"\\.\pipe\VeraHostAuthz-..", "VeraHostAuthz-test", "",
])
def test_reject_nonlocal_or_noncanonical_pipe_name(bad):
    with pytest.raises(WindowsPipeUnavailable):
        WindowsAuthorityPipeServer(bad, HOST, (MODEL_A,), FakeService(), _api=FakeAPI(payload()))


@pytest.mark.parametrize("client", [HOST, "S-1-5-7", "S-1-5-20", "S-1-1-0", "S-1-5-11"])
def test_reject_nonunique_or_privileged_model_sid(client):
    with pytest.raises(WindowsPipeUnavailable):
        build_pipe_security_descriptor(HOST, (client,))


@pytest.mark.parametrize("host", ["S-1-1-0", "S-1-5-11", "S-1-5-32-544", "S-1-5-7"])
def test_reject_broad_host_sid_that_would_grant_full_control(host):
    with pytest.raises(WindowsPipeUnavailable):
        build_pipe_security_descriptor(host, (MODEL_A,))


@pytest.mark.parametrize("fail_at", ["create", "connect", "read", "authenticate"])
def test_failure_before_auth_never_dispatches_and_closes(fail_at):
    api = FakeAPI(payload())
    api.fail_at = fail_at
    endpoint, service = server(api)
    with pytest.raises(WindowsPipeUnavailable):
        endpoint.serve_once()
    assert not service.calls
    if fail_at != "create":
        assert "close" in api.actions


@pytest.mark.parametrize("message", [
    b"\n", b"garbage\n", b"{}\n", b"{}\n{}\n", b"x" * 65537,
    payload(peer_key="sid:" + MODEL_A), payload(model_id="model-a"),
])
def test_untrusted_invalid_message_never_reaches_service(message):
    api = FakeAPI(message)
    endpoint, service = server(api)
    endpoint.serve_once()
    assert not service.calls
    assert json.loads(api.response)["ok"] is False


def test_cleanup_on_service_exception_and_no_leak():
    api = FakeAPI(payload())
    svc = FakeService()
    def broken(**_):
        raise RuntimeError("sensitive authority detail")
    svc.execute = broken
    endpoint, _ = server(api, service=svc)
    endpoint.serve_once()
    assert b"sensitive" not in api.response
    assert api.response == b'{"ok":false,"error":"denied"}\n'
    assert api.actions[-2:] == ["disconnect", "close"]


def test_native_windows_cannot_substitute_fake_api(monkeypatch):
    from vera_core.host_authz import windows_pipe
    monkeypatch.setattr(windows_pipe.sys, "platform", "win32")
    with pytest.raises(WindowsPipeUnavailable, match="substituted"):
        WindowsAuthorityPipeServer(
            PIPE, HOST, (MODEL_A,), FakeService(), _api=FakeAPI(payload())
        )


def test_native_listener_rejects_legacy_host_service(monkeypatch):
    from vera_core.host_authz import windows_pipe
    from vera_core.host_authz.service import HostAuthorizationService
    monkeypatch.setattr(windows_pipe.sys, "platform", "win32")
    # Reject the legacy service type even though it previously backed this pipe.
    with pytest.raises(WindowsPipeUnavailable, match="UnifiedAuthorizationService"):
        WindowsAuthorityPipeServer(PIPE, HOST, (MODEL_A,), FakeService())
    with pytest.raises(WindowsPipeUnavailable, match="UnifiedAuthorizationService"):
        _require_coherent_service(object.__new__(HostAuthorizationService), frozenset({"sid:" + MODEL_A}))


def coherent_fixture(*, fixture_mode=False, keys=(MODEL_A, MODEL_B), client_ids=("provider-a",)):
    principals = {
        "sid:" + sid: PrincipalBinding(
            "sid:" + sid, "model-" + str(i), "adapter-" + str(i),
            "runtime-" + str(i), "subject-" + str(i), frozenset({"provider-a"}),
        )
        for i, sid in enumerate(keys)
    }
    snapshot = HostBindingSnapshot(
        "host-a", "issuer-a", 1, principals,
        {"provider-a": ProviderBinding("provider-a", "provider-instance-a", frozenset({"inspect"}))},
    )
    authority = object.__new__(UnifiedHostAuthority)
    authority.bindings = snapshot
    service = object.__new__(UnifiedAuthorizationService)
    service._authority = authority
    service._unqualified_in_process_fixture = fixture_mode
    service._clients = MappingProxyType({p: object.__new__(ProviderCustodyRPCClient) for p in client_ids})
    return service


def test_coherent_unified_service_and_immutable_binding_snapshot_mock_contract():
    # This pure construction contract test does not prove Windows process isolation.
    service = coherent_fixture()
    _require_coherent_service(service, frozenset({"sid:" + MODEL_A, "sid:" + MODEL_B}))


def test_native_windows_server_fails_closed_without_windows_provider_rpc(monkeypatch):
    from vera_core.host_authz import windows_pipe
    monkeypatch.setattr(windows_pipe.sys, "platform", "win32")
    # Even a structurally coherent service must not open the named pipe while
    # provider custody speaks only Linux AF_UNIX / SO_PEERCRED.
    with pytest.raises(WindowsProviderTransportUnavailable, match="Linux AF_UNIX"):
        WindowsAuthorityPipeServer(
            PIPE, HOST, (MODEL_A, MODEL_B), coherent_fixture()
        )


def test_native_listener_rejects_in_process_fixture_even_with_exact_service():
    with pytest.raises(WindowsPipeUnavailable, match="in-process provider fixture"):
        _require_coherent_service(coherent_fixture(fixture_mode=True), frozenset({"sid:" + MODEL_A, "sid:" + MODEL_B}))


def test_coherent_service_must_bind_exact_dacl_subject_set():
    with pytest.raises(WindowsPipeUnavailable, match="DACL and host principals differ"):
        _require_coherent_service(coherent_fixture(keys=(MODEL_A,)), frozenset({"sid:" + MODEL_A, "sid:" + MODEL_B}))


@pytest.mark.parametrize("client_ids", [(), ("provider-a", "provider-b")])
def test_coherent_service_must_bind_provider_rpc_registry_exactly(client_ids):
    with pytest.raises(WindowsPipeUnavailable, match="isolated provider RPC"):
        _require_coherent_service(coherent_fixture(client_ids=client_ids), frozenset({"sid:" + MODEL_A, "sid:" + MODEL_B}))
