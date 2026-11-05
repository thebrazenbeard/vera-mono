from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket
import sys
import threading

import pytest

from vera_core.host_authz.ipc import (
    UnixAuthorityServer,
    authenticated_peer_key,
    handle_connection,
)


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="SO_PEERCRED is Linux-only")


class _Receipt:
    def public_body(self):
        return {"effect_id": "e1", "state": "ACKNOWLEDGED"}


class _FakeService:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return _Receipt()


def _request(**updates):
    body = {
        "signed_grant_b64": base64.b64encode(b"signed-host-grant").decode("ascii"),
        "provider_id": "fixture-provider",
        "operation": "fixture-operation",
        "request_payload": {"value": 1},
    }
    body.update(updates)
    return (json.dumps(body, separators=(",", ":")) + "\n").encode("utf-8")


def _exchange(payload, *, service=None, max_message_bytes=65536):
    service = service or _FakeService()
    a, b = socket.socketpair()
    try:
        b.sendall(payload)
        handle_connection(a, service, max_message_bytes=max_message_bytes)
        answer = b.recv(65536)
        return json.loads(answer), service
    finally:
        a.close()
        b.close()


def test_kernel_peer_identity_not_request_text():
    service = _FakeService()
    answer, _ = _exchange(_request(), service=service)
    assert answer == {"ok": True, "receipt": {"effect_id": "e1", "state": "ACKNOWLEDGED"}}
    assert len(service.calls) == 1
    assert service.calls[0]["peer_key"] == f"uid:{os.getuid()}"
    assert service.calls[0]["signed_grant"] == b"signed-host-grant"
    assert service.calls[0]["request_payload"] == {"value": 1}


@pytest.mark.parametrize(
    "overrides",
    [
        {"peer_key": "uid:0"},
        {"model_id": "another-model"},
        {"subject_id": "victim"},
        {"issuer_id": "claimed-trusted"},
        {"host_id": "another-host"},
        {"consent": True},
        {"action": "mint_grant"},
        {"signed_grant_b64": "!invalid!"},
        {"provider_id": 123},
    ],
)
def test_caller_cannot_supply_authority_or_malformed_fields(overrides):
    service = _FakeService()
    answer, _ = _exchange(_request(**overrides), service=service)
    assert answer == {"ok": False, "error": "denied"}
    assert service.calls == []


def test_duplicate_json_fields_denied_before_service():
    service = _FakeService()
    payload = _request().replace(b'"provider_id":"fixture-provider"', b'"provider_id":"x","provider_id":"fixture-provider"')
    answer, _ = _exchange(payload, service=service)
    assert answer == {"ok": False, "error": "denied"}
    assert service.calls == []


def test_nested_duplicate_json_fields_denied_before_service():
    service = _FakeService()
    payload = _request().replace(b'"value":1', b'"value":1,"value":2')
    answer, _ = _exchange(payload, service=service)
    assert answer == {"ok": False, "error": "denied"}
    assert service.calls == []


def test_oversized_message_denied_without_service_call():
    service = _FakeService()
    answer, _ = _exchange(_request(request_payload={"text": "x" * 500}), service=service, max_message_bytes=100)
    assert answer == {"ok": False, "error": "denied"}
    assert service.calls == []


def test_noncanonical_or_multiple_request_frames_denied():
    service = _FakeService()
    answer, _ = _exchange(_request() + _request(), service=service)
    assert answer == {"ok": False, "error": "denied"}
    assert service.calls == []


def test_no_unsafe_nonlinux_fallback(monkeypatch):
    a, b = socket.socketpair()
    try:
        monkeypatch.setattr(sys, "platform", "win32")
        with pytest.raises(OSError):
            authenticated_peer_key(a)
    finally:
        a.close()
        b.close()


def test_real_unix_server_roundtrip(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "authority.sock"
    service = _FakeService()
    server = UnixAuthorityServer(path, service)
    ready = threading.Event()
    thread = threading.Thread(target=server.serve_once, kwargs={"ready": ready})
    thread.start()
    assert ready.wait(timeout=3)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(_request())
        answer = json.loads(client.recv(4096))
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert answer["ok"] is True
    assert not path.exists()
    assert len(service.calls) == 1


def test_existing_socket_path_never_unlinked(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "authority.sock"
    path.write_text("belongs to someone else", encoding="utf-8")
    server = UnixAuthorityServer(path, _FakeService())
    with pytest.raises((OSError, ValueError)):
        server.serve_once()
    assert path.read_text(encoding="utf-8") == "belongs to someone else"


def test_untrusted_group_writable_parent_denied(tmp_path):
    tmp_path.chmod(0o770)
    path = tmp_path / "authority.sock"
    server = UnixAuthorityServer(path, _FakeService())
    with pytest.raises(OSError):
        server.serve_once()
    assert not path.exists()


def test_failed_socket_permission_setup_does_not_leave_stale_socket(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    path = tmp_path / "authority.sock"
    server = UnixAuthorityServer(path, _FakeService())
    from vera_core.host_authz import ipc

    original_chmod = ipc.os.chmod

    def failed_chmod(target, mode):
        if str(target) == str(path):
            raise PermissionError("synthetic chmod denial")
        return original_chmod(target, mode)

    monkeypatch.setattr(ipc.os, "chmod", failed_chmod)
    with pytest.raises(PermissionError):
        server.serve_once()
    assert not path.exists()


class _LeakyService:
    def execute(self, **kwargs):
        raise RuntimeError("SECRET_INTERNAL_AUTHORIZATION_REASON")


def test_errors_do_not_disclose_internal_authority_details():
    response, _ = _exchange(_request(), service=_LeakyService())
    assert response == {"ok": False, "error": "denied"}
