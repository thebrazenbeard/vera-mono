"""Two real kernel-authenticated model UIDs share a reachable host socket.

Only the signed model-A grant is issued. Model B must not use it even though
model B is also registered, has permission for the same provider, and can
connect to the authority endpoint. The witness/provider remain test fixtures,
not production custody or independent physical-effect verification.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import threading

import pytest

from vera_core.host_authz.bindings import (
    HostBindingSnapshot, PrincipalBinding, ProviderBinding,
)
from vera_core.host_authz.ipc import QualifiedUnixAuthorityServer
from vera_core.host_authz.peer_isolation import (
    HostPeerIsolationPlan, LinuxProcessPin, PeerIsolationDenied,
    read_linux_process_identity,
)

from test_host_authz_ipc_hardened import _frame, _test_unified_service


_LINUX = (
    os.name == "posix" and hasattr(socket, "SO_PEERCRED")
    and hasattr(os, "fork") and hasattr(os, "setuid")
)


def _model_child(endpoint: Path, *, uid: int, gid: int, request_count: int):
    request_r, request_w = os.pipe()
    response_r, response_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(request_w)
            os.close(response_r)
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
            for _ in range(request_count):
                request = os.read(request_r, 8192)
                if not request.endswith(b"\n"):
                    os._exit(91)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.settimeout(5)
                    conn.connect(str(endpoint))
                    conn.sendall(request)
                    response = conn.recv(4096)
                os.write(response_w, response)
            os._exit(0)
        except BaseException:
            os._exit(92)
    os.close(request_r)
    os.close(response_w)
    return pid, request_w, response_r


@pytest.mark.skipif(not _LINUX, reason="Linux SO_PEERCRED and fork required")
def test_two_registered_kernel_models_cannot_transfer_one_grant_or_effect(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("requires ephemeral, distinct test UIDs launched by root")

    socket_dir = Path(tempfile.mkdtemp(prefix="host-authz-two-model-", dir="/tmp"))
    socket_dir.chmod(0o711)
    endpoint = socket_dir / "authority.sock"
    # Model B deliberately shares the socket-access group with model A. This
    # makes the kernel peer-identity/grant binding the exercised control.
    children = {
        "A": _model_child(endpoint, uid=65534, gid=65534, request_count=2),
        "B": _model_child(endpoint, uid=65532, gid=65534, request_count=3),
    }
    effects = None
    try:
        pins = {}
        for name, uid in (("A", 65534), ("B", 65532)):
            pid = children[name][0]
            for _ in range(100):
                try:
                    actual_uid, started = read_linux_process_identity(pid)
                    if actual_uid == uid:
                        break
                except PeerIsolationDenied:
                    pass
                threading.Event().wait(0.01)
            else:
                pytest.fail(f"model {name} never acquired dedicated test UID")
            pins[f"uid:{uid}"] = LinuxProcessPin(pid, uid, started)

        a = PrincipalBinding("uid:65534", "model-a", "adapter-a", "runtime-a",
                             "subject-a", frozenset({"provider-a"}))
        b = PrincipalBinding("uid:65532", "model-b", "adapter-b", "runtime-b",
                             "subject-b", frozenset({"provider-a"}))
        bindings = HostBindingSnapshot(
            "test-host", "test-issuer", 1,
            {a.peer_key: a, b.peer_key: b},
            {"provider-a": ProviderBinding("provider-a", "provider-instance-a",
                                            frozenset({"inspect"}))},
        )
        plan = HostPeerIsolationPlan("uid:0", bindings, pins)
        service, signed_grant, effects = _test_unified_service(tmp_path, plan)

        def send_one(model, *, frame=None):
            server = QualifiedUnixAuthorityServer(
                endpoint, service, plan=plan, socket_group_id=65534,
            )
            ready = threading.Event()
            server_thread = threading.Thread(
                target=server.serve_once, kwargs={"ready": ready}, daemon=True,
            )
            server_thread.start()
            assert ready.wait(3), "authority listener failed to start"
            os.write(children[model][1], frame or _frame(signed_grant))
            response = json.loads(os.read(children[model][2], 4096))
            server_thread.join(3)
            assert not server_thread.is_alive(), "authority listener did not exit"
            return response

        # If B is rejected only because a grant was already spent, it would
        # succeed first. B must fail before A consumes anything.
        b_before = send_one("B")
        assert b_before["ok"] is False
        assert service._authority.read("test-grant") is None
        assert len(effects) == 0

        # The model can put arbitrary claimed identity text in its message;
        # the IPC parser must not treat it as the authenticated peer identity.
        forged_body = json.loads(_frame(signed_grant))
        forged_body["peer_key"] = "uid:65534"
        forged_frame = (json.dumps(forged_body, sort_keys=True,
                                   separators=(",", ":")) + "\n").encode()
        b_claimed_a = send_one("B", frame=forged_frame)
        assert b_claimed_a["ok"] is False
        assert service._authority.read("test-grant") is None
        assert len(effects) == 0

        a_first = send_one("A")
        assert a_first["ok"] is True
        assert a_first["receipt"]["state"] == "ACKNOWLEDGED"
        assert service._authority.read("test-grant").state == "COMPLETED"
        assert len(effects) == 1

        b_after = send_one("B")
        a_replay = send_one("A")
        assert b_after["ok"] is False
        assert a_replay["ok"] is False
        assert len(effects) == 1
    finally:
        if effects is not None:
            effects.close()
        for pid, request_w, response_r in children.values():
            os.close(request_w)
            os.close(response_r)
            _, status = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        endpoint.unlink(missing_ok=True)
        socket_dir.rmdir()
