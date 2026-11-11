"""Linux kernel/process checks for separately owned provider effect custody.

The mTLS leader is separately exercised by unified-witness tests. Here the
witness signer/fence are synthetic; this proves process transport behavior,
NOT a production-authorized host/witness installation.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import tempfile
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.bindings import HostBindingSnapshot, PrincipalBinding, ProviderBinding
from vera_core.host_authz.grants import ApprovedGrant, SignedGrantVerifier, SIGNATURE_CONTEXT as GRANT_CONTEXT, SIGNED_GRANT_SCHEMA
from vera_core.host_authz.peer_isolation import read_linux_process_identity
from vera_core.host_authz.provider_custody import HostDispatchSigner, ProviderCustodyWorker
from vera_core.host_authz.provider_rpc import (
    ProviderCustodyRPCClient, ProviderCustodyRPCServer, ProviderRPCDenied,
)
from vera_core.host_authz.service import AuthorizationDenied
from vera_core.host_authz.unified_authority import UnifiedHostAuthority, RECEIPT_SCHEMA, SIGNATURE_CONTEXT
from vera_core.host_authz.unified_service import UnifiedAuthorizationService


_NOW = 2000
_PAYLOAD = {"message": "one securely scoped effect"}


class SyntheticLeader:
    def __init__(self, key):
        self.key = key
        self.seq = 0

    def allocate_event(self, req):
        raw = json.loads(req)
        self.seq += 1
        body = {key: raw[key] for key in (
            "host_id", "issuer_id", "epoch", "challenge", "kind", "event_digest", "leader_epoch")}
        body.update(sequence=self.seq, approved=True)
        sig = self.key.sign(SIGNATURE_CONTEXT + canonical_json_bytes(body))
        return canonical_json_bytes({"schema": RECEIPT_SCHEMA, "body": body,
                                     "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode()})


class SyntheticEffectFence:
    def __init__(self):
        self.effects = set()

    def reserve_provider_effect(self, **fields):
        effect = fields["effect_id"]
        if effect in self.effects:
            return False
        self.effects.add(effect)
        return True


def _read(fd, size):
    body = bytearray()
    while len(body) < size:
        part = os.read(fd, size - len(body))
        if not part:
            raise AssertionError("provider child did not publish expected startup marker")
        body.extend(part)
    return bytes(body)


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "fork") or
                    not hasattr(socket, "SO_PEERCRED"),
                    reason="dedicated Linux provider OS principal needed")
def test_unified_service_uses_real_separate_provider_uid_and_signed_rpc(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("OS UID isolation requires ephemeral setuid from root")
    host_uid, host_pid = os.geteuid(), os.getpid()
    _uid, host_start = read_linux_process_identity(host_pid)
    test_dir = Path(tempfile.mkdtemp(prefix="host-authz-provider-rpc-", dir="/tmp"))
    test_dir.chmod(0o711)
    provider_dir = test_dir / "provider"
    provider_dir.mkdir(mode=0o700)
    os.chown(provider_dir, 65534, 65534)
    endpoint = provider_dir / "custody.sock"
    issuer_key, witness_key, command_key = (Ed25519PrivateKey.generate() for _ in range(3))
    signer = HostDispatchSigner(command_key, host_id="host-X", epoch=5,
                                trusted_clock=lambda: _NOW)
    ready_r, ready_w = os.pipe()
    provider_pid = os.fork()
    if provider_pid == 0:
        try:
            os.close(ready_r)
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
            provider_key = Ed25519PrivateKey.generate()
            worker = ProviderCustodyWorker(
                state_path=provider_dir / "fence.sqlite", provider_id="provider-X",
                provider_instance_id="instance-X", host_id="host-X", epoch=5,
                host_command_public_key=signer.public_key_bytes,
                receipt_signer=provider_key,
                witness_start_public_key=witness_key.public_key().public_bytes_raw(),
                witness_leader_epoch=11, effect_witness=SyntheticEffectFence(),
                execute=lambda command: {"ok": True, "provider_process": os.getpid()},
                trusted_clock=lambda: _NOW,
            )
            os.write(ready_w, provider_key.public_key().public_bytes_raw())
            class Ready:
                def set(self):
                    os.write(ready_w, b"R")
            ProviderCustodyRPCServer(endpoint, worker, host_pid=host_pid,
                                     host_uid=host_uid, host_start=host_start).serve_once(ready=Ready())
            os._exit(0)
        except BaseException:
            os._exit(92)
    os.close(ready_w)
    try:
        receipt_public = _read(ready_r, 32)
        assert _read(ready_r, 1) == b"R"
        provider_uid, provider_start = read_linux_process_identity(provider_pid)
        assert provider_uid == 65534 and provider_uid != host_uid
        client = ProviderCustodyRPCClient(
            endpoint, provider_pid=provider_pid, provider_uid=provider_uid,
            provider_start=provider_start, provider_id="provider-X",
            provider_instance_id="instance-X", host_id="host-X", epoch=5,
            receipt_public_key_bytes=receipt_public,
            host_command_public_key_bytes=signer.public_key_bytes,
            witness_start_public_key=witness_key.public_key().public_bytes_raw(),
            witness_leader_epoch=11,
        )
        principal = PrincipalBinding("uid:65533", "model-X", "adapter-X", "runtime-X", "subject-X",
                                     frozenset({"provider-X"}))
        bindings = HostBindingSnapshot("host-X", "issuer-X", 5,
                   {principal.peer_key: principal},
                   {"provider-X": ProviderBinding("provider-X", "instance-X", frozenset({"inspect"}))})
        verifier = SignedGrantVerifier(issuer_key.public_key().public_bytes_raw(),
                   issuer_id="issuer-X", host_id="host-X", epoch=5,
                   trusted_clock=lambda: _NOW)
        host_dir = tmp_path / "host-authority"
        host_dir.mkdir(mode=0o700)
        authority = UnifiedHostAuthority(host_dir / "events.sqlite", bindings=bindings,
                   grant_verifier=verifier, witness=SyntheticLeader(witness_key),
                   witness_public_key=witness_key.public_key().public_bytes_raw(),
                   leader_epoch=11, provider_public_keys={"provider-X": receipt_public},
                   trusted_clock=lambda: _NOW, consent_status=lambda grant, now: True)
        service = UnifiedAuthorizationService(
            authority=authority, host_command_signer=signer,
            provider_clients={"provider-X": client},
        )
        assert service._unqualified_in_process_fixture is False
        # A provider account shared with any model would let that model own
        # provider socket/state/key files. Must fail even with valid signatures.
        overlapping = PrincipalBinding("uid:65534", "model-X", "adapter-X", "runtime-X",
                                       "subject-X", frozenset({"provider-X"}))
        overlap_bindings = HostBindingSnapshot("host-X", "issuer-X", 5,
              {overlapping.peer_key: overlapping},
              {"provider-X": ProviderBinding("provider-X", "instance-X", frozenset({"inspect"}))})
        overlap_authority = UnifiedHostAuthority(host_dir / "overlap.sqlite",
              bindings=overlap_bindings, grant_verifier=verifier,
              witness=SyntheticLeader(witness_key),
              witness_public_key=witness_key.public_key().public_bytes_raw(),
              leader_epoch=11, provider_public_keys={"provider-X": receipt_public},
              trusted_clock=lambda: _NOW, consent_status=lambda grant, now: True)
        with pytest.raises(AuthorizationDenied, match="overlaps an admitted model"):
            UnifiedAuthorizationService(authority=overlap_authority,
                host_command_signer=signer, provider_clients={"provider-X": client})
        grant = ApprovedGrant(grant_id="grant-X", issuer_id="issuer-X", host_id="host-X", epoch=5,
                              peer_key="uid:65533", model_id="model-X", adapter_id="adapter-X",
                              runtime_id="runtime-X", subject_id="subject-X", participant_id="participant-X",
                              purpose="bounded test", provider_id="provider-X",
                              provider_instance_id="instance-X", operation="inspect",
                              request_digest=sha256(canonical_json_bytes(_PAYLOAD)).hexdigest(),
                              not_before=_NOW - 60, expires_at=_NOW + 60)
        signed = canonical_json_bytes({"schema": SIGNED_GRANT_SCHEMA,
                   "grant": grant.canonical_body(),
                   "signature": base64.urlsafe_b64encode(issuer_key.sign(
                       GRANT_CONTEXT + canonical_json_bytes(grant.canonical_body()))).rstrip(b"=").decode()})
        result = service.execute(peer_key="uid:65533", signed_grant=signed,
                  provider_id="provider-X", operation="inspect", request_payload=_PAYLOAD)
        assert result.state == "ACKNOWLEDGED"
        assert authority.read("grant-X").state == "COMPLETED"
        assert not hasattr(client, "_execute")
        with pytest.raises((AttributeError, TypeError)):
            client._execute = lambda _: "retargeted"
        os.waitpid(provider_pid, 0)
        provider_pid = -1
        # Source readback of provider-owned state shows a single physical fence.
        import sqlite3
        with sqlite3.connect(provider_dir / "fence.sqlite") as db:
            states = db.execute("SELECT state FROM provider_effects").fetchall()
        assert states == [("COMMITTED",)]
    finally:
        os.close(ready_r)
        if provider_pid > 0:
            import signal
            os.kill(provider_pid, signal.SIGTERM)
            os.waitpid(provider_pid, 0)
        if endpoint.exists():
            endpoint.unlink()
        for path in provider_dir.iterdir():
            path.unlink()
        provider_dir.rmdir()
        test_dir.rmdir()


def test_provider_rpc_fails_closed_without_pinned_distinct_process(tmp_path):
    # On Windows there is no SO_PEERCRED/SCM_CREDENTIALS backend; rejection of
    # the transport itself is the required fail-closed behavior.
    linux_credentials = (
        os.name == "posix"
        and all(hasattr(socket, name) for name in
                ("SO_PEERCRED", "SCM_CREDENTIALS", "SO_PASSCRED"))
    )
    with pytest.raises(ProviderRPCDenied, match="separate OS uid" if linux_credentials else "Linux-only"):
        ProviderCustodyRPCClient(tmp_path / "provider.sock", provider_pid=os.getpid(),
            provider_uid=os.geteuid() if linux_credentials else 0, provider_start=1, provider_id="p",
            provider_instance_id="i", host_id="h", epoch=1,
            receipt_public_key_bytes=b"x" * 32,
            host_command_public_key_bytes=b"y" * 32,
            witness_start_public_key=b"z" * 32, witness_leader_epoch=1)
