"""Guard the qualified host boundary against legacy daemon reintroduction.

The old one-shot IPC entry point is retained for characterization tests, not
for installation. These tests do not prove a host has uninstalled a legacy
listener; that requires physical process/socket readback.
"""

from __future__ import annotations

import ast
from pathlib import Path
import socket
import sys
import threading

import pytest

from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.ipc import HostIPCError, QualifiedUnixAuthorityServer, UnixAuthorityServer
from vera_core.host_authz.peer_isolation import HostPeerIsolationPlan, LinuxProcessPin, PeerIsolationDenied
from vera_core.host_authz.service import HostAuthorizationService


class _ArbitraryCallback:
    def execute(self, **kwargs):
        raise AssertionError("legacy callback must never be reached")


def _synthetic_host_plan() -> HostPeerIsolationPlan:
    principal = PrincipalBinding(
        "uid:65534", "model-a", "adapter-a", "runtime-a", "subject-a",
        frozenset({"provider-a"}),
    )
    bindings = HostBindingSnapshot(
        "host-a", "issuer-a", 1, {principal.peer_key: principal},
        {"provider-a": ProviderBinding("provider-a", "provider-instance-a", frozenset({"inspect"}))},
    )
    return HostPeerIsolationPlan(
        "uid:0", bindings, {principal.peer_key: LinuxProcessPin(1234, 65534, 12)},
    )


def test_qualified_endpoint_rejects_arbitrary_callback_and_legacy_service(tmp_path):
    plan = _synthetic_host_plan()
    endpoint = tmp_path / "qualified.sock"
    for service in (_ArbitraryCallback(), object.__new__(HostAuthorizationService)):
        with pytest.raises(HostIPCError, match="unified authorization service"):
            QualifiedUnixAuthorityServer(endpoint, service, plan=plan)
        assert not endpoint.exists()


def test_unprovisioned_kernel_peer_has_no_authority():
    plan = _synthetic_host_plan()
    with pytest.raises(PeerIsolationDenied, match="kernel credentials do not match"):
        plan.principal_for_kernel_peer("uid:65535", pid=1234, start_ticks=12)


@pytest.mark.skipif(sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"),
                    reason="legacy Unix socket seam is Linux-only")
def test_legacy_persistent_listener_fails_before_socket_bind(tmp_path):
    tmp_path.chmod(0o700)
    endpoint = tmp_path / "legacy.sock"
    server = UnixAuthorityServer(endpoint, _ArbitraryCallback())
    with pytest.raises(HostIPCError, match="legacy persistent authorization listener disabled"):
        server.serve_forever(threading.Event())
    assert not endpoint.exists()


def test_no_production_source_constructs_unqualified_legacy_server():
    """Source audit guard, not proof of absent installed old binaries."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for source in (root / "packages").rglob("*.py"):
        parsed = ast.parse(source.read_text(encoding="utf-8-sig"))
        for node in ast.walk(parsed):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = called.id if isinstance(called, ast.Name) else (
                called.attr if isinstance(called, ast.Attribute) else None
            )
            if name == "UnixAuthorityServer":
                offenders.append(f"{source.relative_to(root)}:{node.lineno}")
    assert offenders == [], f"unqualified listener constructed by source: {offenders}"
