"""Host-admin enrollment is Linux source TEST evidence, not host installation."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import tempfile
import threading

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from test_host_authz_unified_witness_server import _grant, _leader_network, _signed
from vera_core.host_authz.admin_enrollment import (
    AdminEnrollmentDenied, AdminEnrollmentJournal, AdminProcessPin,
    ENROLL_SCHEMA, HostAdminEnrollmentServer,
)
from vera_core.host_authz.peer_isolation import read_linux_process_identity
from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.grants import SignedGrantVerifier
from vera_core.host_authz.unified_authority import UnifiedHostAuthority
from vera_core.host_authz.unified_witness_server import (
    UnifiedWitnessLeader, WitnessLeaderConfig, WitnessLeaderDenied,
)


pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "fork"),
    reason="kernel UID/SCM_CREDENTIALS admin enrollment requires Linux",
)


def _frame(signed: bytes) -> bytes:
    return canonical_json_bytes({
        "schema": ENROLL_SCHEMA,
        "signed_grant": base64.urlsafe_b64encode(signed).rstrip(b"=").decode("ascii"),
    })


def _journal(state: Path) -> AdminEnrollmentJournal:
    return AdminEnrollmentJournal(state / "admin-enroll.sqlite",
                                  host_id="host-a", issuer_id="issuer-a", epoch=4)


@contextmanager
def _leader_instance(tmp_path):
    """No network thread: fork-based kernel tests avoid fork-with-threads."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    issuer = Ed25519PrivateKey.generate()
    signer = Ed25519PrivateKey.generate()
    provider_key = Ed25519PrivateKey.generate()
    principal = PrincipalBinding("uid:1234", "model-a", "adapter-a", "runtime-a",
                                 "subject-a", frozenset({"provider-a"}))
    bindings = HostBindingSnapshot(
        "host-a", "issuer-a", 4, {principal.peer_key: principal},
        {"provider-a": ProviderBinding("provider-a", "instance-a",
                                        frozenset({"execute"}))},
    )
    verifier = SignedGrantVerifier(issuer.public_key().public_bytes_raw(),
                                   issuer_id="issuer-a", host_id="host-a", epoch=4,
                                   trusted_clock=lambda: 100)
    leader = UnifiedWitnessLeader(
        state / "leader.sqlite", bindings=bindings, verifier=verifier,
        config=WitnessLeaderConfig(
            "host-a", "issuer-a", 4, 11,
            sha256(b"host-client-test").hexdigest(),
            {"provider-a": sha256(b"provider-client-test").hexdigest()},
        ),
        receipt_signer=signer,
        provider_public_keys={"provider-a": provider_key.public_key().public_bytes_raw()},
        trusted_clock=lambda: 100, consent_status=lambda grant, now: True,
    )
    yield leader, issuer, state


def _server(path: Path, leader, journal, *, pid=1234, uid=65534, gid=65534,
            start=1, forbidden=frozenset({65533})):
    pin = AdminProcessPin(pid, uid, gid, start, "host-a", "issuer-a", 4)
    return HostAdminEnrollmentServer(path, leader=leader, journal=journal,
                                     admin=pin, forbidden_uids=forbidden)


def _auth_child(ready_fd: int, result_fd: int, endpoint: Path, frame: bytes,
                *, uid: int, gid: int, inherited: bool = False) -> None:
    try:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
        marker = os.read(ready_fd, 1)
        if marker == b"e":
            os._exit(0)
        if marker != b"x":
            os._exit(91)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        client.settimeout(5)
        client.connect(str(endpoint))
        if inherited:
            descendant = os.fork()
            if descendant == 0:
                client.send(frame)
                os._exit(0)
            os.waitpid(descendant, 0)
        else:
            client.send(frame)
        response = client.recv(4096)
        os.write(result_fd, response)
        client.close()
        os._exit(0)
    except BaseException:
        os._exit(92)


def _wait_uid(pid: int, expected: int) -> int:
    for _ in range(100):
        try:
            uid, start = read_linux_process_identity(pid)
            if uid == expected:
                return start
        except Exception:
            pass
        threading.Event().wait(0.01)
    raise AssertionError("administrator child never acquired dedicated UID")


@pytest.mark.skipif(not hasattr(os, "geteuid") or (hasattr(os, "geteuid") and os.geteuid() != 0),
                    reason="real unprivileged admin child needs ephemeral root test runner")
@pytest.mark.parametrize("inherited,approved", [(False, True), (True, False)])
def test_real_kernel_admin_enrolls_exact_signed_grant_and_replay_denied(tmp_path, inherited, approved):
    with _leader_instance(tmp_path) as (leader, issuer, state):
        signed = _signed(issuer, _grant())
        journal = _journal(state)
        root = Path(tempfile.mkdtemp(prefix="host-authz-admin-", dir="/tmp"))
        os.chown(root, -1, 65534)
        root.chmod(0o710)
        endpoint = root / "admin.sock"
        ready_r, ready_w = os.pipe()
        result_r, result_w = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(ready_w)
            os.close(result_r)
            _auth_child(ready_r, result_w, endpoint, _frame(signed),
                        uid=65534, gid=65534, inherited=inherited)
        os.close(ready_r)
        os.close(result_w)
        thread = None
        try:
            start = _wait_uid(child, 65534)
            service = _server(endpoint, leader, journal, pid=child, start=start)
            ready = threading.Event()
            thread = threading.Thread(target=service.serve_once, kwargs={"ready": ready}, daemon=True)
            thread.start()
            assert ready.wait(3)
            os.write(ready_w, b"x")
            response = json.loads(os.read(result_r, 4096))
            thread.join(3)
            assert not thread.is_alive()
            assert response["schema"] == "HOST_AUTHZ_ADMIN_ENROLL_RESULT_V1"
            assert response["ok"] is approved
            if approved:
                assert response["grant_id"] == "grant-1"
                assert journal.read(sha256(signed).hexdigest()) == ("ADMITTED", "grant-1")
                with pytest.raises(WitnessLeaderDenied):
                    leader.register_grant(signed)
                with pytest.raises(AdminEnrollmentDenied):
                    service._register(_frame(signed))
            else:
                assert journal.read(sha256(signed).hexdigest()) is None
                assert leader.register_grant(signed) == "grant-1"
        finally:
            os.close(ready_w)
            os.close(result_r)
            pid, status = os.waitpid(child, 0)
            assert pid == child and os.waitstatus_to_exitcode(status) == 0
            endpoint.unlink(missing_ok=True)
            root.rmdir()


@pytest.mark.skipif(not hasattr(os, "geteuid") or (hasattr(os, "geteuid") and os.geteuid() != 0),
                    reason="real wrong-UID adversary needs root test runner")
def test_actual_model_uid_cannot_impersonate_pinned_admin(tmp_path):
    with _leader_instance(tmp_path) as (leader, issuer, state):
        signed = _signed(issuer, _grant())
        journal = _journal(state)
        root = Path(tempfile.mkdtemp(prefix="host-authz-admin-deny-", dir="/tmp"))
        os.chown(root, -1, 65534)
        root.chmod(0o710)
        endpoint = root / "admin.sock"
        # A legitimate admin stays alive so the server can pin PID/start.
        admin_r, admin_w = os.pipe()
        null_r, null_w = os.pipe()
        admin_pid = os.fork()
        if admin_pid == 0:
            os.close(admin_w)
            os.close(null_r)
            _auth_child(admin_r, null_w, endpoint, _frame(signed),
                        uid=65534, gid=65534)
        os.close(admin_r)
        os.close(null_w)
        attacker_r, attacker_w = os.pipe()
        result_r, result_w = os.pipe()
        attacker_pid = os.fork()
        if attacker_pid == 0:
            os.close(attacker_w)
            os.close(result_r)
            # Has the admin socket's GROUP access, but not its kernel UID.
            _auth_child(attacker_r, result_w, endpoint, _frame(signed),
                        uid=65533, gid=65534)
        os.close(attacker_r)
        os.close(result_w)
        try:
            start = _wait_uid(admin_pid, 65534)
            _wait_uid(attacker_pid, 65533)
            server = _server(endpoint, leader, journal, pid=admin_pid, start=start)
            ready = threading.Event()
            thread = threading.Thread(target=server.serve_once, kwargs={"ready": ready}, daemon=True)
            thread.start()
            assert ready.wait(3)
            os.write(attacker_w, b"x")
            reply = json.loads(os.read(result_r, 4096))
            thread.join(3)
            assert not thread.is_alive()
            assert reply == {"schema": "HOST_AUTHZ_ADMIN_ENROLL_RESULT_V1", "ok": False}
            assert journal.read(sha256(signed).hexdigest()) is None
            assert leader.register_grant(signed) == "grant-1"
        finally:
            os.write(admin_w, b"e")
            os.close(admin_w)
            os.close(null_r)
            os.close(attacker_w)
            os.close(result_r)
            for target in (admin_pid, attacker_pid):
                pid, status = os.waitpid(target, 0)
                assert pid == target and os.waitstatus_to_exitcode(status) == 0
            endpoint.unlink(missing_ok=True)
            root.rmdir()


def test_signed_scope_expiry_and_revocation_denied_and_audited(tmp_path):
    with _leader_network(tmp_path) as (leader, signer, issuer, bindings, verifier,
                                   clients, state, provider_signer):
        journal = _journal(state)
        server = _server(Path("/tmp/not-open.sock"), leader, journal)
        expired = _signed(issuer, replace(_grant(grant_id="expired"), expires_at=99))
        wrong_provider = _signed(issuer, replace(_grant(grant_id="wrong"), provider_instance_id="other"))
        for signed in (expired, wrong_provider):
            with pytest.raises(AdminEnrollmentDenied):
                server._register(_frame(signed))
            assert journal.read(sha256(signed).hexdigest()) == ("DENIED", None)
        original = _grant(grant_id="grant-before-revoke")
        original_signed = _signed(issuer, original)
        assert server._register(_frame(original_signed))["ok"] is True
        authority = UnifiedHostAuthority(
            state / "host-auth.sqlite", bindings=bindings, grant_verifier=verifier,
            witness=clients["host"], witness_public_key=signer.public_key().public_bytes_raw(),
            leader_epoch=11, provider_public_keys={"provider-a": provider_signer.public_key().public_bytes_raw()},
            trusted_clock=lambda: 100, consent_status=lambda g, now: True,
        )
        authority.revoke_scope(original)
        same_scope = _signed(issuer, _grant(grant_id="grant-after-revoke"))
        with pytest.raises(AdminEnrollmentDenied):
            server._register(_frame(same_scope))
        assert journal.read(sha256(same_scope).hexdigest()) == ("DENIED", None)


def test_ambiguous_after_witness_commit_stays_pending_and_not_retried(tmp_path):
    with _leader_network(tmp_path) as (leader, _, issuer, _, _, _, state, _):
        journal = _journal(state)
        server = _server(Path("/tmp/not-open.sock"), leader, journal)
        signed = _signed(issuer, _grant())
        actual = leader.register_grant

        def commit_then_raise(value):
            actual(value)
            raise RuntimeError("transport dropped after durable commit")

        leader.register_grant = commit_then_raise
        with pytest.raises(AdminEnrollmentDenied, match="reconciliation"):
            server._register(_frame(signed))
        digest = sha256(signed).hexdigest()
        assert journal.read(digest) == ("PENDING", None)
        assert _journal(state).read(digest) == ("PENDING", None)
        with pytest.raises(AdminEnrollmentDenied):
            server._register(_frame(signed))
        with pytest.raises(WitnessLeaderDenied):
            actual(signed)


def test_journal_owner_and_admin_identity_fail_closed(tmp_path):
    with _leader_network(tmp_path) as (leader, _, _, _, _, _, state, _):
        journal = _journal(state)
        with pytest.raises(AdminEnrollmentDenied):
            _server(Path("/tmp/not-open.sock"), leader, journal, uid=1234)
        with pytest.raises(AdminEnrollmentDenied):
            _server(Path("/tmp/not-open.sock"), leader, journal, uid=os.geteuid())
        with pytest.raises(AdminEnrollmentDenied):
            _server(Path("/tmp/not-open.sock"), leader, journal, uid=65533)
        original = state / "admin-enroll.sqlite"
        replacement = state / "different.sqlite"
        original.rename(replacement)
        original.symlink_to(replacement)
        with pytest.raises(AdminEnrollmentDenied):
            journal.read("0" * 64)
