"""Actual Linux process/IPC admission, not a production host installation."""

from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import tempfile
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from portfolio_runtime.lantern.canonical import canonical_json_bytes

import pytest

from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.grants import (
    ApprovedGrant, SignedGrantVerifier, SIGNATURE_CONTEXT as GRANT_CONTEXT,
    SIGNED_GRANT_SCHEMA,
)
from vera_core.host_authz.ipc import HostIPCError, QualifiedUnixAuthorityServer
from vera_core.host_authz.provider_custody import HostDispatchSigner, ProviderCustodyWorker
from vera_core.host_authz.provider_rpc import ProviderCustodyRPCClient, ProviderCustodyRPCServer
from vera_core.host_authz.peer_isolation import (
    HostPeerIsolationPlan, LinuxProcessPin, PeerIsolationDenied,
    read_linux_process_identity,
)
from vera_core.host_authz.unified_authority import (
    RECEIPT_SCHEMA, SIGNATURE_CONTEXT, UnifiedHostAuthority,
)
from vera_core.host_authz.unified_service import UnifiedAuthorizationService


class Receipt:
    def public_body(self):
        return {"state": "fixture-ack", "grant_id": "synthetic"}


class RecordingService:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return Receipt()


def _canonical(body):
    return canonical_json_bytes(body)


class TestWitness:
    """Synthetic signing witness: sufficient for test, NOT independent custody."""

    __test__ = False

    def __init__(self, private_key):
        self.key = private_key
        self.sequence = 0

    def allocate_event(self, request):
        raw = json.loads(request)
        self.sequence += 1
        body = {key: raw[key] for key in (
            "host_id", "issuer_id", "epoch", "challenge", "kind", "event_digest"
        )}
        body.update({"leader_epoch": 11, "sequence": self.sequence,
                     "approved": True})
        sig = self.key.sign(SIGNATURE_CONTEXT + _canonical(body))
        return _canonical({"schema": RECEIPT_SCHEMA, "body": body,
                           "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode()})


class TestEffectFence:
    """Single-process test fence, not the required external provider witness."""

    __test__ = False

    def __init__(self):
        self.spent = set()

    def reserve_provider_effect(self, **event):
        effect_id = event["effect_id"]
        if effect_id in self.spent:
            return False
        self.spent.add(effect_id)
        return True


_PAYLOAD = {"value": "synthetic"}


class ProviderEffectProbe:
    """Test-only monitor; provider executes in another UID/PID."""

    def __init__(self, pid, directory):
        self.pid = pid
        self.directory = directory

    def __len__(self):
        dbpath = self.directory / "effects.sqlite"
        if not dbpath.exists():
            return 0
        with sqlite3.connect(dbpath) as db:
            return db.execute("SELECT COUNT(*) FROM provider_effects WHERE state='COMMITTED'").fetchone()[0]

    def close(self):
        if self.pid > 0:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.waitpid(self.pid, 0)
            self.pid = -1
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()


def _test_unified_service(test_dir: Path, plan: HostPeerIsolationPlan):
    """Real unified service + distinct UID provider, synthetic witness only."""
    if os.geteuid() != 0:
        pytest.skip("qualified provider RPC fixture requires ephemeral UID isolation")
    store = test_dir / "private-host-store"
    store.mkdir(mode=0o700)
    issuer = Ed25519PrivateKey.generate()
    witness = Ed25519PrivateKey.generate()
    provider = Ed25519PrivateKey.generate()
    command = Ed25519PrivateKey.generate()
    now = lambda: 2000
    verifier = SignedGrantVerifier(
        issuer.public_key().public_bytes_raw(), issuer_id="test-issuer",
        host_id="test-host", epoch=1, trusted_clock=now,
    )
    authority = UnifiedHostAuthority(
        store / "authority.sqlite", bindings=plan.bindings,
        grant_verifier=verifier, witness=TestWitness(witness),
        witness_public_key=witness.public_key().public_bytes_raw(),
        leader_epoch=11,
        provider_public_keys={"provider-a": provider.public_key().public_bytes_raw()},
        trusted_clock=now, consent_status=lambda grant, timestamp: True,
    )
    signer = HostDispatchSigner(command, host_id="test-host", epoch=1,
                                trusted_clock=now)
    provider_dir = Path(tempfile.mkdtemp(prefix="host-authz-ipc-provider-", dir="/tmp"))
    os.chown(provider_dir, 65533, 65533)
    endpoint = provider_dir / "custody.sock"
    ready_r, ready_w = os.pipe()
    host_pid = os.getpid()
    _uid, host_start = read_linux_process_identity(host_pid)
    provider_pid = os.fork()
    if provider_pid == 0:
        try:
            os.close(ready_r)
            os.setgroups([])
            os.setgid(65533)
            os.setuid(65533)
            worker = ProviderCustodyWorker(
                state_path=provider_dir / "effects.sqlite", provider_id="provider-a",
                provider_instance_id="provider-instance-a", host_id="test-host", epoch=1,
                host_command_public_key=signer.public_key_bytes,
                receipt_signer=provider, effect_witness=TestEffectFence(),
                execute=lambda dispatch: {"ok": True, "pid": os.getpid()},
                trusted_clock=now,
                witness_start_public_key=witness.public_key().public_bytes_raw(),
                witness_leader_epoch=11,
            )
            class Ready:
                def set(self):
                    os.write(ready_w, b"R")
            ProviderCustodyRPCServer(endpoint, worker, host_pid=host_pid,
                                     host_uid=0, host_start=host_start).serve_once(ready=Ready())
            os._exit(0)
        except BaseException:
            os._exit(92)
    os.close(ready_w)
    if os.read(ready_r, 1) != b"R":
        os.close(ready_r)
        raise AssertionError("provider process failed to create authenticated socket")
    os.close(ready_r)
    provider_uid, provider_start = read_linux_process_identity(provider_pid)
    assert provider_uid == 65533
    client = ProviderCustodyRPCClient(
        endpoint, provider_pid=provider_pid, provider_uid=provider_uid,
        provider_start=provider_start, provider_id="provider-a",
        provider_instance_id="provider-instance-a", host_id="test-host", epoch=1,
        receipt_public_key_bytes=provider.public_key().public_bytes_raw(),
        host_command_public_key_bytes=signer.public_key_bytes,
        witness_start_public_key=witness.public_key().public_bytes_raw(),
        witness_leader_epoch=11,
    )
    effects = ProviderEffectProbe(provider_pid, provider_dir)
    service = UnifiedAuthorizationService(
        authority=authority, host_command_signer=signer,
        provider_clients={"provider-a": client},
    )
    grant = ApprovedGrant(
        grant_id="test-grant", issuer_id="test-issuer", host_id="test-host",
        epoch=1, peer_key="uid:65534", model_id="model-a",
        adapter_id="adapter-a", runtime_id="runtime-a", subject_id="subject-a",
        participant_id="participant-a", purpose="test observation",
        provider_id="provider-a", provider_instance_id="provider-instance-a",
        operation="inspect", request_digest=sha256(_canonical(_PAYLOAD)).hexdigest(),
        not_before=1900, expires_at=2100,
    )
    signature = issuer.sign(GRANT_CONTEXT + _canonical(grant.canonical_body()))
    signed = _canonical({"schema": SIGNED_GRANT_SCHEMA,
                         "grant": grant.canonical_body(),
                         "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode()})
    return service, signed, effects


def _plan(pid, start):
    p = PrincipalBinding("uid:65534", "model-a", "adapter-a", "runtime-a",
                         "subject-a", frozenset({"provider-a"}))
    bindings = HostBindingSnapshot(
        "test-host", "test-issuer", 1, {p.peer_key: p},
        {"provider-a": ProviderBinding("provider-a", "provider-instance-a",
                                       frozenset({"inspect"}))},
    )
    return HostPeerIsolationPlan(
        "uid:0", bindings, {p.peer_key: LinuxProcessPin(pid, 65534, start)}
    )


def _frame(signed_grant):
    return (json.dumps({
        "signed_grant_b64": base64.b64encode(signed_grant).decode(),
        "provider_id": "provider-a",
        "operation": "inspect",
        "request_payload": _PAYLOAD,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.skipif(os.name != "posix" or not hasattr(socket, "SO_PEERCRED") or
                    not hasattr(os, "fork"), reason="Linux kernel model credentials required")
@pytest.mark.parametrize("inherited,accepted", [(False, True), (True, False)])
def test_qualified_server_dedicated_model_uid_and_inherited_fd(tmp_path, inherited, accepted):
    if os.geteuid() != 0:
        pytest.skip("test needs an ephemeral unprivileged child launched by root")
    # A direct child of /tmp remains traversable after the model drops UID.
    test_dir = Path(tempfile.mkdtemp(prefix="host-authz-qualified-", dir="/tmp"))
    test_dir.chmod(0o711)
    endpoint = test_dir / "authority.sock"
    ready_r, ready_w = os.pipe()
    result_r, result_w = os.pipe()
    child = os.fork()
    if child == 0:
        try:
            os.close(ready_w)
            os.close(result_r)
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            frame = os.read(ready_r, 8192)
            if not frame.endswith(b"\n"):
                os._exit(91)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(5)
            client.connect(str(endpoint))
            if inherited:
                grandchild = os.fork()
                if grandchild == 0:
                    client.sendall(frame)
                    os._exit(0)
                os.waitpid(grandchild, 0)
            else:
                client.sendall(frame)
            reply = client.recv(4096)
            os.write(result_w, reply)
            client.close()
            os._exit(0)
        except BaseException:
            os._exit(92)
    os.close(ready_r)
    os.close(result_w)
    server_thread = None
    try:
        # Wait until child has dropped privileges but remains alive on ready pipe.
        for _ in range(100):
            try:
                uid, start = read_linux_process_identity(child)
                if uid == 65534:
                    break
            except PeerIsolationDenied:
                pass
            threading.Event().wait(0.01)
        assert uid == 65534
        plan = _plan(child, start)
        service, signed_grant, effects = _test_unified_service(tmp_path, plan)
        server = QualifiedUnixAuthorityServer(
            endpoint, service, plan=plan, socket_group_id=65534,
        )
        ready = threading.Event()
        server_thread = threading.Thread(target=server.serve_once,
                                         kwargs={"ready": ready}, daemon=True)
        server_thread.start()
        assert ready.wait(3)
        os.write(ready_w, _frame(signed_grant))
        reply = os.read(result_r, 4096)
        server_thread.join(3)
        assert not server_thread.is_alive()
        response = json.loads(reply)
        assert response["ok"] is accepted
        assert len(effects) == int(accepted)
        if accepted:
            assert response["receipt"]["state"] == "ACKNOWLEDGED"
            assert service._authority.read("test-grant").state == "COMPLETED"
    finally:
        if "effects" in locals():
            effects.close()
        os.close(ready_w)
        os.close(result_r)
        pid, status = os.waitpid(child, 0)
        assert pid == child and os.waitstatus_to_exitcode(status) == 0
        endpoint.unlink(missing_ok=True)
        test_dir.rmdir()


def test_qualified_server_must_have_host_plan(tmp_path):
    service = RecordingService()
    with pytest.raises((TypeError, ValueError, PermissionError)):
        QualifiedUnixAuthorityServer(tmp_path / "socket", service, plan=None)
    p = _plan(12345, 12)
    with pytest.raises((TypeError, ValueError, PermissionError, OSError),
                       match="unified authorization service"):
        QualifiedUnixAuthorityServer(tmp_path / "socket", service, plan=p)
    service, signed, effects = _test_unified_service(tmp_path, p)
    try:
        class ImpostorUnifiedService(UnifiedAuthorizationService):
            pass
        with pytest.raises(HostIPCError, match="unified authorization service"):
            QualifiedUnixAuthorityServer(tmp_path / "socket", object.__new__(ImpostorUnifiedService),
                                         plan=p)
        equivalent_but_other = _plan(12345, 12)
        with pytest.raises(HostIPCError, match="different host snapshots"):
            QualifiedUnixAuthorityServer(tmp_path / "socket", service,
                                         plan=equivalent_but_other)
        wrong_host = HostPeerIsolationPlan(
            "uid:123456", p.bindings, dict(p.process_pins)
        )
        server = QualifiedUnixAuthorityServer(tmp_path / "socket", service,
                                              plan=wrong_host)
        with pytest.raises(PeerIsolationDenied):
            server.serve_once()
        assert not (tmp_path / "socket").exists()
    finally:
        effects.close()
