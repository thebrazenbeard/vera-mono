"""Linux kernel-peer-to-provider authorization tests using real OS processes.

The child is a real UID-65534 process and never receives signing keys, host
bindings or provider objects. The host-side leader/fence are deliberately
synthetic: these are not qualifications of remote witness or provider custody.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import tempfile
import threading
from unittest.mock import patch

import pytest

from vera_core.host_authz.ipc import QualifiedUnixAuthorityServer
from vera_core.host_authz.peer_isolation import (
    PeerIsolationDenied, read_linux_process_identity,
)

# Reuse the independently exercised cryptographic fixture. This test adds a
# multi-request process lifecycle and an in-flight revocation, not a second
# fake implementation of the authorization protocol.
from test_host_authz_ipc_hardened import _frame, _plan, _test_unified_service


_LINUX = (
    os.name == "posix" and hasattr(socket, "SO_PEERCRED")
    and hasattr(os, "fork") and hasattr(os, "setuid")
)


@pytest.mark.skipif(not _LINUX, reason="requires real Linux kernel peer credentials")
@pytest.mark.parametrize("case", ["consumed-grant-replay", "revoke-before-start"])
def test_real_model_process_cannot_replay_or_overtake_revocation(tmp_path, case):
    if os.geteuid() != 0:
        pytest.skip("requires an ephemeral UID-65534 child launched by root")

    socket_dir = Path(tempfile.mkdtemp(prefix="host-authz-e2e-", dir="/tmp"))
    socket_dir.chmod(0o711)
    endpoint = socket_dir / "authority.sock"
    go_read, go_write = os.pipe()
    result_read, result_write = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(go_write)
            os.close(result_read)
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            # The child gets only the signed grant/request over this pipe,
            # never the host's verifier, signing keys, or provider worker.
            for _ in range(2 if case == "consumed-grant-replay" else 1):
                request = os.read(go_read, 8192)
                if not request.endswith(b"\n"):
                    os._exit(91)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(5)
                    connection.connect(str(endpoint))
                    connection.sendall(request)
                    response = connection.recv(4096)
                os.write(result_write, response)
            os._exit(0)
        except BaseException:
            os._exit(92)

    os.close(go_read)
    os.close(result_write)
    try:
        for _ in range(100):
            try:
                uid, started = read_linux_process_identity(child)
                if uid == 65534:
                    break
            except PeerIsolationDenied:
                pass
            threading.Event().wait(0.01)
        else:
            pytest.fail("unprivileged model child never became ready")

        plan = _plan(child, started)
        service, signed_grant, effects = _test_unified_service(tmp_path, plan)
        authority = service._authority
        grant = authority.grant_verifier.verify(signed_grant)
        original_start = authority.start

        def revoke_before_start(grant_id):
            authority.revoke_scope(grant)
            return original_start(grant_id)

        patcher = (
            patch.object(authority, "start", side_effect=revoke_before_start)
            if case == "revoke-before-start" else None
        )
        if patcher is not None:
            patcher.start()
        try:
            results = []
            for _ in range(2 if case == "consumed-grant-replay" else 1):
                server = QualifiedUnixAuthorityServer(
                    endpoint, service, plan=plan, socket_group_id=65534,
                )
                ready = threading.Event()
                server_thread = threading.Thread(
                    target=server.serve_once, kwargs={"ready": ready}, daemon=True,
                )
                server_thread.start()
                assert ready.wait(3), "host authorization listener did not start"
                os.write(go_write, _frame(signed_grant))
                results.append(json.loads(os.read(result_read, 4096)))
                server_thread.join(3)
                assert not server_thread.is_alive(), "host listener did not finish"
        finally:
            if patcher is not None:
                patcher.stop()

        if case == "consumed-grant-replay":
            assert [response["ok"] for response in results] == [True, False]
            assert results[0]["receipt"]["state"] == "ACKNOWLEDGED"
            assert authority.read(grant.grant_id).state == "COMPLETED"
            assert len(effects) == 1
        else:
            assert [response["ok"] for response in results] == [False]
            assert authority.read(grant.grant_id).state == "CLAIMED"
            assert len(effects) == 0
    finally:
        if "effects" in locals():
            effects.close()
        os.close(go_write)
        os.close(result_read)
        pid, status = os.waitpid(child, 0)
        assert pid == child and os.waitstatus_to_exitcode(status) == 0
        endpoint.unlink(missing_ok=True)
        socket_dir.rmdir()
