"""Source-level Windows provider pipe contract, NOT a physical Win32 probe."""

from __future__ import annotations

from hashlib import sha256
import json
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes

from vera_core.host_authz.provider_custody import HostDispatchSigner
from vera_core.host_authz.provider_rpc import _ACK_CONTEXT, _ACK_SCHEMA, _WIRE_SCHEMA, _b64
from vera_core.host_authz.service import ProviderAcknowledgement, ProviderDispatch
from vera_core.host_authz.unified_authority import WitnessEventReceipt
from vera_core.host_authz.windows_provider_rpc import (
    _NativeWindowsProviderAPI,
    WindowsProviderCustodyRPCClient,
    WindowsProviderCustodyRPCServer,
    WindowsProviderRPCUnavailable,
    build_provider_pipe_security_descriptor,
)


PIPE = r"\\.\pipe\VeraProviderAuthz-test"
PROVIDER_SID = "S-1-5-21-100-200-300-1001"
HOST_SID = "S-1-5-21-100-200-300-1002"
PROVIDER_PID = 2468
PROVIDER_CREATED = 133728000000000000
HOST_PID = 2220
HOST_CREATED = 133728000000000001


def _command(*, effect="e" * 64):
    payload = {"value": "inspect"}
    dispatch = ProviderDispatch(
        effect_id=effect, grant_id="grant-a", provider_id="provider-a",
        provider_instance_id="instance-a", operation="inspect",
        request_digest=sha256(canonical_json_bytes(payload)).hexdigest(),
        claim_sequence=1, participant_id="participant-a", purpose="inspection",
        request_payload=payload,
    )
    host_key = Ed25519PrivateKey.generate()
    signer = HostDispatchSigner(host_key, host_id="host-a", epoch=1,
                                trusted_clock=lambda: 1000)
    return dispatch, signer.sign(dispatch), host_key.public_key().public_bytes_raw()


def _ack(dispatch, provider_signer):
    initial = ProviderAcknowledgement(
        effect_id=dispatch.effect_id, provider_id=dispatch.provider_id,
        provider_instance_id=dispatch.provider_instance_id,
        claim_sequence=dispatch.claim_sequence,
        request_digest=dispatch.request_digest,
        provider_receipt_digest="f" * 64, receipt_signature=b"",
    )
    signature = provider_signer.sign(_ACK_CONTEXT + canonical_json_bytes(initial.signed_body()))
    return ProviderAcknowledgement(
        effect_id=initial.effect_id,
        provider_id=initial.provider_id,
        provider_instance_id=initial.provider_instance_id,
        claim_sequence=initial.claim_sequence,
        request_digest=initial.request_digest,
        provider_receipt_digest=initial.provider_receipt_digest,
        receipt_signature=signature,
    )


def _ack_bytes(ack):
    return canonical_json_bytes({
        "schema": _ACK_SCHEMA, "ok": True,
        "ack": {**ack.signed_body(), "signature": _b64(ack.receipt_signature)},
    })


class ClientAPI:
    def __init__(self, response, identity=(PROVIDER_SID, PROVIDER_PID, PROVIDER_CREATED)):
        self.response = response
        self.identity = identity
        self.actions = []
        self.handle = object()

    def open_client(self, name, timeout):
        self.actions.append("open")
        assert name == PIPE and 100 <= timeout <= 5000
        return self.handle

    def authenticated_provider(self, handle):
        self.actions.append("kernel-provider")
        assert handle is self.handle
        return self.identity

    def write_message(self, handle, payload, timeout):
        self.actions.append("write")
        assert handle is self.handle
        self.request = payload

    def read_message(self, handle, max_size, timeout):
        self.actions.append("read")
        assert handle is self.handle and max_size == 65537
        return self.response

    def close(self, handle):
        self.actions.append("close")
        assert handle is self.handle


def client(api, host_key, provider_signer):
    if sys.platform == "win32":
        pytest.skip("synthetic RPC adapters are prohibited on native Windows")
    return WindowsProviderCustodyRPCClient(
        PIPE, host_sid=HOST_SID, provider_sid=PROVIDER_SID,
        provider_pid=PROVIDER_PID, provider_created=PROVIDER_CREATED,
        provider_id="provider-a", provider_instance_id="instance-a",
        host_id="host-a", epoch=1,
        receipt_public_key_bytes=provider_signer.public_key().public_bytes_raw(),
        host_command_public_key_bytes=host_key,
        witness_start_public_key=b"w" * 32, witness_leader_epoch=9,
        _api=api,
    )


LEASE = WitnessEventReceipt(raw=b"witness-signed", event=b"signed-start", body={})


def test_provider_pipe_dacl_has_exact_distinct_sids_and_no_create_right():
    sddl = build_provider_pipe_security_descriptor(PROVIDER_SID, HOST_SID)
    assert sddl == (
        "D:P(D;;GA;;;NU)(D;;GA;;;AN)"
        f"(A;;FA;;;{PROVIDER_SID})(A;;0x00120003;;;{HOST_SID})"
    )
    assert "WD" not in sddl and "AU" not in sddl and "0x00120007" not in sddl


@pytest.mark.parametrize("bad", ["", "pipe-name", r"\\remote\pipe\VeraProviderAuthz-test",
                                r"\\.\pipe\Other", r"\\.\pipe\VeraProviderAuthz-.."])
def test_provider_endpoint_rejects_nonlocal_or_invalid_name(bad):
    with pytest.raises(WindowsProviderRPCUnavailable):
        WindowsProviderCustodyRPCClient(
            bad, host_sid=HOST_SID, provider_sid=PROVIDER_SID,
            provider_pid=PROVIDER_PID, provider_created=PROVIDER_CREATED,
            provider_id="provider-a", provider_instance_id="instance-a",
            host_id="host-a", epoch=1, receipt_public_key_bytes=b"a" * 32,
            host_command_public_key_bytes=b"b" * 32,
            witness_start_public_key=b"c" * 32, witness_leader_epoch=9,
            _api=ClientAPI(b""),
        )


@pytest.mark.parametrize("bad", ["S-1-1-0", "S-1-5-7", "S-1-5-11", "S-1-5-18",
                                "S-1-5-32-544", "not-a-SID", "S-1-5-20"])
def test_provider_pipe_rejects_shared_or_privileged_provider_sid(bad):
    with pytest.raises(WindowsProviderRPCUnavailable):
        build_provider_pipe_security_descriptor(bad, HOST_SID)


def test_provider_pipe_rejects_same_host_and_provider_sid():
    with pytest.raises(WindowsProviderRPCUnavailable):
        build_provider_pipe_security_descriptor(PROVIDER_SID, PROVIDER_SID)


def test_native_client_requests_only_the_exact_data_rights_granted_by_dacl():
    class Kernel:
        def WaitNamedPipeW(self, name, timeout):
            assert name == PIPE and timeout == 5000
            return True

        def CreateFileW(self, name, rights, sharing, attrs, disposition, flags, template):
            assert name == PIPE
            assert rights == 0x00120003  # NO 0x4 FILE_CREATE_PIPE_INSTANCE
            assert sharing == 0 and attrs is None and disposition == 3
            assert flags == 0x40110000  # OVERLAPPED | SQOS_PRESENT | IDENTIFICATION
            assert template is None
            return 4096

    # This is not a native transport probe: test the argument contract only.
    adapter = object.__new__(_NativeWindowsProviderAPI)
    adapter.k = Kernel()
    assert adapter.open_client(PIPE, 5000) == 4096


def test_client_verifies_kernel_server_before_sending_and_exact_signed_ack():
    dispatch, command, host_key = _command()
    signer = Ed25519PrivateKey.generate()
    api = ClientAPI(_ack_bytes(_ack(dispatch, signer)))
    bound = client(api, host_key, signer)
    got = bound.dispatch(command, start_lease=LEASE)
    assert got.effect_id == dispatch.effect_id
    assert api.actions == ["open", "kernel-provider", "write", "read", "close"]
    raw = json.loads(api.request)
    assert set(raw) == {"schema", "command", "start_receipt", "start_event"}
    assert raw["schema"] == _WIRE_SCHEMA
    assert "provider_signer" not in raw and "provider_sid" not in raw


@pytest.mark.parametrize("identity", [
    ("S-1-5-21-100-200-300-9999", PROVIDER_PID, PROVIDER_CREATED),
    (PROVIDER_SID, PROVIDER_PID + 1, PROVIDER_CREATED),
    (PROVIDER_SID, PROVIDER_PID, PROVIDER_CREATED + 1),
])
def test_client_denies_provider_identity_substitution_before_command(identity):
    dispatch, command, host_key = _command()
    signer = Ed25519PrivateKey.generate()
    api = ClientAPI(_ack_bytes(_ack(dispatch, signer)), identity)
    with pytest.raises(WindowsProviderRPCUnavailable, match="SID/PID/creation"):
        client(api, host_key, signer).dispatch(command, start_lease=LEASE)
    assert api.actions == ["open", "kernel-provider", "close"]


def test_client_rejects_forged_ack_even_if_pipe_identity_is_pinned():
    dispatch, command, host_key = _command()
    trusted = Ed25519PrivateKey.generate()
    attacker = Ed25519PrivateKey.generate()
    api = ClientAPI(_ack_bytes(_ack(dispatch, attacker)))
    with pytest.raises(WindowsProviderRPCUnavailable, match="pinned key"):
        client(api, host_key, trusted).dispatch(command, start_lease=LEASE)


def test_client_rejects_ack_replay_for_different_effect():
    original, _, host_key = _command(effect="e" * 64)
    substitute, command, _ = _command(effect="a" * 64)
    # Sign the substituted effect with the host key expected by the client.
    signer = Ed25519PrivateKey.generate()
    host_signer = HostDispatchSigner(
        Ed25519PrivateKey.generate(), host_id="host-a", epoch=1,
        trusted_clock=lambda: 1000,
    )
    command = host_signer.sign(substitute)
    api = ClientAPI(_ack_bytes(_ack(original, signer)))
    bound = client(api, host_signer.public_key_bytes, signer)
    with pytest.raises(WindowsProviderRPCUnavailable, match="ACK did not bind"):
        bound.dispatch(command, start_lease=LEASE)


def test_client_denies_mutated_host_signature_before_approaching_pipe():
    dispatch, command, host_key = _command()
    signer = Ed25519PrivateKey.generate()
    api = ClientAPI(_ack_bytes(_ack(dispatch, signer)))
    altered = bytearray(command)
    altered[-4] = ord("A") if altered[-4] != ord("A") else ord("B")
    with pytest.raises(WindowsProviderRPCUnavailable):
        client(api, host_key, signer).dispatch(bytes(altered), start_lease=LEASE)
    assert api.actions == []


class Worker:
    def __init__(self, ack=None, failure=None):
        self.ack = ack
        self.failure = failure
        self.calls = []

    def dispatch(self, command, *, start_lease):
        self.calls.append((command, start_lease))
        if self.failure:
            raise self.failure
        return self.ack


class ServerAPI:
    def __init__(self, request, identity=(HOST_SID, HOST_PID, HOST_CREATED),
                 self_identity=(PROVIDER_SID, PROVIDER_PID, PROVIDER_CREATED)):
        self.request, self.identity, self.self_identity = request, identity, self_identity
        self.actions = []
        self.handle = object()

    def current_process_identity(self):
        self.actions.append("self-token")
        return self.self_identity

    def create_pipe(self, name, sddl, size):
        self.actions.append("create")
        assert name == PIPE and sddl.startswith("D:P") and size == 65536
        return self.handle

    def connect(self, handle, timeout):
        self.actions.append("connect")

    def read_message(self, handle, size, timeout):
        self.actions.append("read")
        assert size == 65537
        return self.request

    def authenticated_host(self, handle):
        self.actions.append("kernel-host")
        return self.identity

    def write_message(self, handle, response, timeout):
        self.actions.append("write")
        self.response = response

    def disconnect(self, handle):
        self.actions.append("disconnect")

    def close(self, handle):
        self.actions.append("close")


def _server(api, worker):
    if sys.platform == "win32":
        pytest.skip("synthetic RPC adapters are prohibited on native Windows")
    return WindowsProviderCustodyRPCServer(
        PIPE, provider_sid=PROVIDER_SID, host_sid=HOST_SID,
        host_pid=HOST_PID, host_created=HOST_CREATED,
        worker=worker, _api=api,
    )


def _request(command=b"host-signed", receipt=b"start-signed", event=b"start-event"):
    return canonical_json_bytes({
        "schema": _WIRE_SCHEMA, "command": _b64(command),
        "start_receipt": _b64(receipt), "start_event": _b64(event),
    })


def test_server_kernel_authentication_occurs_after_read_and_before_effect():
    dispatch, command, _ = _command()
    signer = Ed25519PrivateKey.generate()
    worker = Worker(ack=_ack(dispatch, signer))
    api = ServerAPI(_request(command=command))
    _server(api, worker).serve_once()
    assert api.actions == ["self-token", "create", "connect", "read", "kernel-host",
                           "write", "disconnect", "close"]
    assert len(worker.calls) == 1 and worker.calls[0][0] == command
    assert worker.calls[0][1].raw == b"start-signed"
    assert json.loads(api.response)["ok"] is True


@pytest.mark.parametrize("identity", [
    ("S-1-5-21-100-200-300-9999", HOST_PID, HOST_CREATED),
    (HOST_SID, HOST_PID + 1, HOST_CREATED),
    (HOST_SID, HOST_PID, HOST_CREATED + 1),
])
def test_server_denies_inherited_handle_or_host_token_substitution(identity):
    worker = Worker()
    api = ServerAPI(_request(), identity=identity)
    with pytest.raises(WindowsProviderRPCUnavailable, match="pinned host"):
        _server(api, worker).serve_once()
    assert not worker.calls
    assert api.actions[-2:] == ["disconnect", "close"]


def test_server_denies_wrong_provider_process_sid_before_pipe_creation():
    api = ServerAPI(_request(), self_identity=(HOST_SID, PROVIDER_PID, PROVIDER_CREATED))
    with pytest.raises(WindowsProviderRPCUnavailable, match="provider daemon"):
        _server(api, Worker()).serve_once()
    assert api.actions == ["self-token"]


def test_server_returns_denied_without_leaking_worker_exception():
    worker = Worker(failure=RuntimeError("secret provider credential"))
    api = ServerAPI(_request())
    _server(api, worker).serve_once()
    assert json.loads(api.response) == {"schema": _ACK_SCHEMA, "ok": False}
    assert b"secret" not in api.response


def test_native_platform_does_not_accept_injected_provider_api(monkeypatch):
    from vera_core.host_authz import windows_provider_rpc
    monkeypatch.setattr(windows_provider_rpc.sys, "platform", "win32")
    with pytest.raises(WindowsProviderRPCUnavailable, match="substituted API"):
        WindowsProviderCustodyRPCServer(
            PIPE, provider_sid=PROVIDER_SID, host_sid=HOST_SID,
            host_pid=HOST_PID, host_created=HOST_CREATED,
            worker=Worker(), _api=ServerAPI(_request()),
        )


def test_no_native_fallback_without_windows(monkeypatch):
    from vera_core.host_authz import windows_provider_rpc
    monkeypatch.setattr(windows_provider_rpc.sys, "platform", "linux")
    with pytest.raises(WindowsProviderRPCUnavailable, match="unavailable"):
        WindowsProviderCustodyRPCServer(
            PIPE, provider_sid=PROVIDER_SID, host_sid=HOST_SID,
            host_pid=HOST_PID, host_created=HOST_CREATED, worker=Worker(),
        )
