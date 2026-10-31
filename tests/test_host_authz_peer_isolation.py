"""Host model-principal isolation: source tests, not host deployment proof."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import tempfile

import pytest

from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.peer_isolation import (
    HostPeerIsolationPlan,
    LinuxProcessPin,
    PeerIsolationDenied,
    receive_authenticated_linux_frame,
    read_linux_process_identity,
)


def _principal(peer, model):
    return PrincipalBinding(peer, model, "adapter-" + model, "runtime-" + model,
                            "subject-" + model, frozenset({"p"}))


def _snapshot(*principals):
    return HostBindingSnapshot(
        "host-test", "issuer-test", 1,
        {p.peer_key: p for p in principals},
        {"p": ProviderBinding("p", "p-instance", frozenset({"inspect"}))},
    )


def _plan(*, service="uid:200", models=(("uid:1001", "a", 501),
                                         ("uid:1002", "b", 502))):
    peers = [_principal(key, model) for key, model, _ in models]
    pins = {key: LinuxProcessPin(pid, int(key[4:]), 123456 + pid)
            for key, _, pid in models}
    return HostPeerIsolationPlan(service, _snapshot(*peers), pins)


def test_two_os_principals_bind_two_distinct_models_without_transfer():
    plan = _plan()
    assert plan.principal_for_kernel_peer("uid:1001", pid=501, start_ticks=123957).model_id == "a"
    assert plan.principal_for_kernel_peer("uid:1002", pid=502, start_ticks=123958).model_id == "b"
    with pytest.raises(PeerIsolationDenied):
        plan.principal_for_kernel_peer("uid:1001", pid=502, start_ticks=123958)


def test_service_os_account_must_not_be_model_account():
    with pytest.raises(PeerIsolationDenied, match="service"):
        _plan(service="uid:1001")


def test_deployment_plan_cannot_claim_another_host_daemon_uid():
    plan = _plan(service="uid:999999")
    with pytest.raises(PeerIsolationDenied, match="daemon"):
        plan.assert_host_process_identity()


def test_same_model_cannot_be_assigned_multiple_os_accounts():
    first = _principal("uid:1001", "a")
    second = PrincipalBinding("uid:1002", "a", "adapter-other", "runtime-other",
                              "subject-other", frozenset({"p"}))
    snapshot = _snapshot(first, second)
    pins = {"uid:1001": LinuxProcessPin(501, 1001, 124001),
            "uid:1002": LinuxProcessPin(502, 1002, 124002)}
    with pytest.raises(PeerIsolationDenied, match="model"):
        HostPeerIsolationPlan("uid:200", snapshot, pins)


def test_pid_reuse_or_wrong_launch_pin_denied():
    plan = _plan()
    with pytest.raises(PeerIsolationDenied):
        plan.principal_for_kernel_peer("uid:1001", pid=501, start_ticks=123958)
    with pytest.raises(PeerIsolationDenied):
        plan.principal_for_kernel_peer("uid:1001", pid=999, start_ticks=123957)


def test_unsupported_identity_and_mixed_platform_denied():
    with pytest.raises(PeerIsolationDenied):
        HostPeerIsolationPlan("uid:200", _snapshot(
            _principal("uid:1001", "a"),
            _principal("sid:S-1-5-21-42", "b"),
        ), {"uid:1001": LinuxProcessPin(501, 1001, 124001),
            "sid:S-1-5-21-42": LinuxProcessPin(502, 1002, 124002)})
    with pytest.raises(PeerIsolationDenied):
        _plan(models=(("uid:0", "a", 501),))
    with pytest.raises(PeerIsolationDenied):
        HostPeerIsolationPlan(
            "uid:200", _snapshot(_principal("uid:1001", "a")),
            {"uid:1001": LinuxProcessPin(501, 1002, 124001)},
        )


@pytest.mark.skipif(sys.platform != "linux", reason="Linux /proc PID-start identity probe")
def test_linux_proc_reader_rejects_symlink_and_real_self_is_stable(tmp_path):
    root = tmp_path / "proc"
    root.symlink_to("/proc", target_is_directory=True)
    with pytest.raises(PeerIsolationDenied):
        read_linux_process_identity(os.getpid(), proc_root=root)
    uid, start_ticks = read_linux_process_identity(os.getpid())
    assert uid == os.getuid()
    assert start_ticks > 0


def _root_host_unprivileged_model(tmp_path, *, inherited: bool):
    """Ephemeral process credential drop; never changes an OS account."""
    if os.geteuid() != 0:
        pytest.skip("dedicated test model UID needs ephemeral root launcher")
    # pytest's /tmp/pytest-of-root ancestors are 0700 and unavailable after
    # the model drops privileges; use a narrow direct child of /tmp instead.
    test_dir = Path(tempfile.mkdtemp(prefix="host-authz-peer-", dir="/tmp"))
    test_dir.chmod(0o711)
    endpoint = test_dir / "peer.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.settimeout(5)
    # A queued first stream frame needs credential capture at send time,
    # before the host has accepted it and can inspect the peer's /proc pin.
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    listener.bind(str(endpoint))
    endpoint.chmod(0o666)
    listener.listen(1)
    queued_r, queued_w = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(queued_r)
            listener.close()
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(endpoint))
            if inherited:
                grandchild = os.fork()
                if grandchild == 0:
                    client.sendall(b'{"operation":"inspect"}\n')
                    os._exit(0)
                os.waitpid(grandchild, 0)
            else:
                client.sendall(b'{"operation":"inspect"}\n')
            os.write(queued_w, b"q")
            os.close(queued_w)
            client.recv(1)  # Stay alive while the host validates /proc.
            client.close()
            os._exit(0)
        except BaseException:
            os._exit(91)
    connection = None
    try:
        os.close(queued_w)
        # Ensure the model's first bytes arrived BEFORE accept; this must
        # remain valid rather than intermittently losing SCM_CREDENTIALS.
        assert os.read(queued_r, 1) == b"q"
        connection, _ = listener.accept()
        uid, start = read_linux_process_identity(child)
        assert uid == 65534
        peer = _principal("uid:65534", "fixture-model")
        plan = HostPeerIsolationPlan(
            "uid:0", _snapshot(peer),
            {peer.peer_key: LinuxProcessPin(child, 65534, start)},
        )
        plan.assert_host_process_identity()
        if inherited:
            with pytest.raises(PeerIsolationDenied, match="credential"):
                receive_authenticated_linux_frame(connection, plan)
        else:
            bound, frame = receive_authenticated_linux_frame(connection, plan)
            assert bound.model_id == "fixture-model"
            assert frame == b'{"operation":"inspect"}'
        connection.sendall(b"x")
    finally:
        os.close(queued_r)
        if connection is not None:
            connection.close()
        listener.close()
        pid, status = os.waitpid(child, 0)
        endpoint.unlink(missing_ok=True)
        test_dir.rmdir()
        assert pid == child and os.waitstatus_to_exitcode(status) == 0


@pytest.mark.skipif(os.name != "posix" or not hasattr(socket, "SO_PEERCRED"),
                    reason="Linux kernel peer credentials required")
def test_kernel_message_credential_matches_host_launched_pid(tmp_path):
    _root_host_unprivileged_model(tmp_path, inherited=False)


@pytest.mark.skipif(os.name != "posix" or not hasattr(socket, "SO_PEERCRED") or
                    not hasattr(os, "fork"), reason="Linux fork/SO_PEERCRED required")
def test_inherited_connected_fd_from_child_fails_per_message_credentials(tmp_path):
    _root_host_unprivileged_model(tmp_path, inherited=True)
