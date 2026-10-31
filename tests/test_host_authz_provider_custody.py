"""Synthetic provider-process custody tests; no production trust root is assumed."""

from __future__ import annotations

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import base64
import json
import multiprocessing
import os
import sys
from pathlib import Path
import shutil

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.provider_custody import (
    HostDispatchSigner,
    ProviderCustodyDenied,
    ProviderCustodyWorker,
)
from vera_core.host_authz.service import ProviderDispatch, ProviderAcknowledgement
from vera_core.host_authz.unified_authority import (
    WitnessEventReceipt,
    RECEIPT_SCHEMA,
    SIGNATURE_CONTEXT,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="provider custody's protected fence and process tests require Linux/POSIX",
)

TEST_NOW = lambda: 2000  # synthetic clock; not a production trusted time source
TEST_START_SIGNER = Ed25519PrivateKey.generate()


def start_lease_for(command=None, *, signing_key=None, **changes):
    """Synthetic independent signed START oracle, not live witness proof."""
    command = command or instruction()
    signing_key = signing_key or TEST_START_SIGNER
    event = {
        "kind": "START",
        "grant_id": command.grant_id,
        "effect_id": command.effect_id,
        "scope_digest": "",
        "host_id": "host-1", "epoch": 4,
        "peer_key": "verified-peer",
        "model_id": "model-1",
        "adapter_id": "adapter-1",
        "runtime_id": "runtime-1",
        "subject_id": "subject-1",
        "participant_id": command.participant_id,
        "purpose": command.purpose,
        "operation": command.operation,
        "claim_sequence": command.claim_sequence,
        "provider_id": command.provider_id,
        "provider_instance_id": command.provider_instance_id,
        "request_digest": command.request_digest,
        "not_before": 1990,
        "expires_at": 2020,
        "issued_at": 1995,
        "start_deadline": 2010,
    }
    event.update(changes)
    if "scope_digest" not in changes:
        event["scope_digest"] = sha256(canonical_json_bytes({field: event[field] for field in (
            "participant_id", "purpose", "model_id", "adapter_id", "runtime_id",
            "subject_id", "host_id", "provider_id", "provider_instance_id",
        )})).hexdigest()
    event_wire = canonical_json_bytes(event)
    body = {
        "host_id": "host-1", "issuer_id": "synthetic-witness", "epoch": 4,
        "leader_epoch": 9,
        "challenge": "synthetic-challenge", "kind": "START", "sequence": 7,
        "approved": True, "event_digest": sha256(event_wire).hexdigest(),
    }
    signature = signing_key.sign(SIGNATURE_CONTEXT + canonical_json_bytes(body))
    raw = canonical_json_bytes({
        "schema": RECEIPT_SCHEMA, "body": body,
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
    })
    return WitnessEventReceipt(raw, body, event_wire)


def trusted_dispatch(worker, signed, *, command=None, start_lease=None):
    return worker.dispatch(signed, start_lease=start_lease or start_lease_for(command))


class SyntheticGlobalEffectWitness:
    """In-memory only; intentionally not durable independent infrastructure."""

    def __init__(self):
        self.seen = set()

    def reserve_provider_effect(
        self, *, host_id, epoch, provider_id, provider_instance_id,
        effect_id, claim_sequence, request_digest, grant_id,
        participant_id, purpose, operation,
    ):
        identity = (host_id, epoch, provider_id, provider_instance_id, effect_id)
        if identity in self.seen:
            return False
        self.seen.add(identity)
        return True


def instruction(effect_id="effect-1", **changes):
    payload = {"operation": "inspect", "value": 7}
    base = ProviderDispatch(
        effect_id=effect_id,
        grant_id="grant-1",
        provider_id="provider-1",
        provider_instance_id="provider-instance-1",
        operation="inspect",
        request_digest=sha256(canonical_json_bytes(payload)).hexdigest(),
        claim_sequence=41,
        participant_id="participant-1",
        purpose="approved inspection",
        request_payload=payload,
    )
    return replace(base, **changes)


def setup(tmp_path, *, execute=None, witness="synthetic", host_signer=None,
          provider_signer=None, provider_clock=TEST_NOW):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    host_signer = host_signer or Ed25519PrivateKey.generate()
    provider_signer = provider_signer or Ed25519PrivateKey.generate()
    signer = HostDispatchSigner(host_signer, host_id="host-1", epoch=4, trusted_clock=TEST_NOW)
    witness = SyntheticGlobalEffectWitness() if witness == "synthetic" else witness
    effects = []

    def default_execute(command):
        effects.append(command)
        return {"status": "ok", "value": 7}

    worker = ProviderCustodyWorker(
        state_path=tmp_path / "provider-effects.sqlite",
        provider_id="provider-1",
        provider_instance_id="provider-instance-1",
        host_id="host-1",
        epoch=4,
        host_command_public_key=host_signer.public_key().public_bytes_raw(),
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=provider_signer,
        effect_witness=witness,
        execute=default_execute if execute is None else execute,
        trusted_clock=provider_clock,
    )
    return signer, worker, effects, provider_signer, witness


def test_valid_host_signed_command_goes_through_provider_fence_and_receipt(tmp_path):
    signer, worker, effects, provider_signer, _ = setup(tmp_path)
    acknowledgement = trusted_dispatch(worker, signer.sign(instruction()))
    assert type(acknowledgement) is ProviderAcknowledgement
    assert acknowledgement.effect_id == "effect-1"
    assert acknowledgement.provider_instance_id == "provider-instance-1"
    assert len(effects) == 1
    assert worker.status("effect-1") == "COMMITTED"
    provider_signer.public_key().verify(
        acknowledgement.receipt_signature,
        b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0"
        + canonical_json_bytes(acknowledgement.signed_body()),
    )
    with pytest.raises(InvalidSignature):
        Ed25519PrivateKey.generate().public_key().verify(
            acknowledgement.receipt_signature,
            b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0"
            + canonical_json_bytes(acknowledgement.signed_body()),
        )


def test_start_lease_is_mandatory_even_for_valid_host_signed_dispatch(tmp_path):
    signer, worker, effects, _, _ = setup(tmp_path)
    with pytest.raises(ProviderCustodyDenied, match="START lease required"):
        worker.dispatch(signer.sign(instruction()))
    assert effects == []
    assert worker.status("effect-1") is None


def test_start_lease_that_expires_during_external_fence_cannot_reach_physical_provider(tmp_path):
    times = iter((2000, 2000, 2011))
    signer, worker, effects, _, _ = setup(tmp_path, provider_clock=lambda: next(times, 2011))
    signed = signer.sign(instruction())
    with pytest.raises(ProviderCustodyDenied, match="ambiguous"):
        trusted_dispatch(worker, signed)
    assert effects == []
    # The external reservation has already been consumed; late retry is not safe.
    assert worker.status("effect-1") == "AMBIGUOUS"
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(worker, signed)
    assert effects == []


@pytest.mark.parametrize("event_change", [
    {"grant_id": "different-grant"},
    {"claim_sequence": 42},
    {"participant_id": "participant-2"},
    {"purpose": "different purpose"},
    {"operation": "unauthorized operation"},
    {"provider_id": "provider-2"},
    {"provider_instance_id": "provider-instance-2"},
    {"request_digest": "f" * 64},
    {"effect_id": "other-effect"},
    {"epoch": 5},
    {"host_id": "host-2"},
    {"expires_at": 2000},
    {"not_before": 2001},
    {"issued_at": 2001, "start_deadline": 2015},
    {"issued_at": 1900, "start_deadline": 1930},
    {"issued_at": 1900, "start_deadline": 2001},
    {"issued_at": 1990, "start_deadline": 2020},
])
def test_witness_signed_start_lease_cross_scope_or_expiry_denied(tmp_path, event_change):
    signer, worker, effects, _, _ = setup(tmp_path)
    with pytest.raises(ProviderCustodyDenied, match="START"):
        trusted_dispatch(worker, signer.sign(instruction()),
                         start_lease=start_lease_for(**event_change))
    assert effects == []
    assert worker.status("effect-1") is None


def test_witness_lease_is_bound_to_signature_event_preimage_and_pinned_signer(tmp_path):
    signer, worker, effects, _, _ = setup(tmp_path)
    valid = start_lease_for()
    impostor = start_lease_for(signing_key=Ed25519PrivateKey.generate())
    payload = json.loads(valid.event)
    payload["subject_id"] = "other-subject"
    mutated_event = WitnessEventReceipt(valid.raw, valid.body, canonical_json_bytes(payload))
    mutated_receipt = WitnessEventReceipt(valid.raw + b" ", valid.body, valid.event)
    for invalid in (impostor, mutated_event, mutated_receipt):
        with pytest.raises(ProviderCustodyDenied, match="START"):
            trusted_dispatch(worker, signer.sign(instruction()), start_lease=invalid)
    assert effects == []
    assert worker.status("effect-1") is None


def test_witness_leader_epoch_and_key_are_pinned_across_restart(tmp_path):
    signer, worker, _, provider_signer, witness = setup(tmp_path)
    base = {
        "state_path": worker.path,
        "host_id": "host-1", "epoch": 4,
        "provider_id": "provider-1", "provider_instance_id": "provider-instance-1",
        "host_command_public_key": signer.public_key_bytes,
        "receipt_signer": provider_signer,
        "effect_witness": witness,
        "execute": lambda _: None,
        "trusted_clock": TEST_NOW,
    }
    with pytest.raises(ProviderCustodyDenied, match="authority binding changed"):
        ProviderCustodyWorker(
            **base, witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
            witness_leader_epoch=10,
        )
    with pytest.raises(ProviderCustodyDenied, match="authority binding changed"):
        ProviderCustodyWorker(
            **base, witness_start_public_key=Ed25519PrivateKey.generate().public_key().public_bytes_raw(),
            witness_leader_epoch=9,
        )


def test_replay_denied_before_second_physical_effect_and_after_restart(tmp_path):
    signer, worker, effects, provider_signer, witness = setup(tmp_path)
    signed = signer.sign(instruction())
    trusted_dispatch(worker, signed)
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(worker, signed)
    assert len(effects) == 1
    restarted = ProviderCustodyWorker(
        state_path=tmp_path / "provider-effects.sqlite",
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        host_id="host-1", epoch=4,
        host_command_public_key=signer.public_key_bytes,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=provider_signer, effect_witness=witness,
        execute=lambda _: pytest.fail("restarted worker dispatched duplicate"),
        trusted_clock=TEST_NOW,
    )
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(restarted, signed)


def test_provider_fence_pins_host_epoch_and_exact_provider_instance_on_restart(tmp_path):
    signer, worker, _, provider_signer, witness = setup(tmp_path)
    for changes in (
        {"host_id": "different-host"},
        {"epoch": 5},
        {"provider_id": "different-provider"},
        {"provider_instance_id": "different-instance"},
    ):
        arguments = {
            "state_path": worker.path,
            "host_id": "host-1", "epoch": 4,
            "provider_id": "provider-1", "provider_instance_id": "provider-instance-1",
            "host_command_public_key": signer.public_key_bytes,
            "witness_start_public_key": TEST_START_SIGNER.public_key().public_bytes_raw(),
            "witness_leader_epoch": 9,
            "receipt_signer": provider_signer, "effect_witness": witness,
            "execute": lambda _: None,
            "trusted_clock": TEST_NOW,
        }
        arguments.update(changes)
        with pytest.raises(ProviderCustodyDenied):
            ProviderCustodyWorker(**arguments)


def test_parallel_same_effect_dispatches_only_one_physical_effect(tmp_path):
    signer, worker, effects, _, _ = setup(tmp_path)
    signed = signer.sign(instruction())

    def run():
        try:
            trusted_dispatch(worker, signed)
            return "done"
        except ProviderCustodyDenied:
            return "denied"

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: run(), range(32)))
    assert results.count("done") == 1
    assert results.count("denied") == 31
    assert len(effects) == 1


@pytest.mark.parametrize("change", [
    {"provider_id": "provider-2"},
    {"provider_instance_id": "provider-instance-2"},
    {"request_digest": "f" * 64},
    {"request_payload": {"operation": "inspect", "value": 999}},
])
def test_wrong_provider_or_mutated_payload_denied_before_effect(tmp_path, change):
    signer, worker, effects, _, _ = setup(tmp_path)
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(worker, signer.sign(instruction(**change)))
    assert not effects
    assert worker.status("effect-1") is None


def test_wrong_host_signer_and_bad_wire_cannot_execute(tmp_path):
    signer, worker, effects, _, _ = setup(tmp_path)
    for command in (HostDispatchSigner(Ed25519PrivateKey.generate(), host_id="host-1", epoch=4, trusted_clock=TEST_NOW).sign(instruction()),
                    b"not json", b"{}", signer.sign(instruction()) + b"x"):
        with pytest.raises(ProviderCustodyDenied):
            trusted_dispatch(worker, command)
    assert not effects


def test_wrong_epoch_does_not_execute(tmp_path):
    key = Ed25519PrivateKey.generate()
    _, worker, effects, _, _ = setup(tmp_path, host_signer=key)
    wrong_epoch = HostDispatchSigner(key, host_id="host-1", epoch=5, trusted_clock=TEST_NOW)
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(worker, wrong_epoch.sign(instruction()))
    assert not effects


def test_stale_host_command_and_untrusted_provider_clock_denied_before_effect(tmp_path):
    key = Ed25519PrivateKey.generate()
    signer = HostDispatchSigner(key, host_id="host-1", epoch=4, trusted_clock=TEST_NOW)
    physical_calls = []
    worker = ProviderCustodyWorker(
        state_path=tmp_path / "stale.sqlite",
        host_id="host-1", epoch=4,
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        host_command_public_key=signer.public_key_bytes,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=Ed25519PrivateKey.generate(),
        effect_witness=SyntheticGlobalEffectWitness(),
        execute=lambda command: physical_calls.append(command),
        trusted_clock=lambda: 2100,
    )
    with pytest.raises(ProviderCustodyDenied, match="no longer valid"):
        trusted_dispatch(worker, signer.sign(instruction()))
    assert not physical_calls
    assert worker.status("effect-1") is None


def test_provider_state_directory_and_fence_file_must_be_host_owned(tmp_path):
    signer_key = Ed25519PrivateKey.generate()
    base = {
        "host_id": "host-1", "epoch": 4,
        "provider_id": "provider-1", "provider_instance_id": "provider-instance-1",
        "host_command_public_key": signer_key.public_key().public_bytes_raw(),
        "witness_start_public_key": TEST_START_SIGNER.public_key().public_bytes_raw(),
        "witness_leader_epoch": 9,
        "receipt_signer": Ed25519PrivateKey.generate(),
        "effect_witness": SyntheticGlobalEffectWitness(),
        "execute": lambda _: None, "trusted_clock": TEST_NOW,
    }
    missing = tmp_path / "missing" / "provider.sqlite"
    with pytest.raises(ProviderCustodyDenied, match="unprovisioned"):
        ProviderCustodyWorker(state_path=missing, **base)

    insecure = tmp_path / "insecure"
    insecure.mkdir()
    insecure.chmod(0o777)
    with pytest.raises(ProviderCustodyDenied, match="exclusively host-owned"):
        ProviderCustodyWorker(state_path=insecure / "provider.sqlite", **base)

    source = tmp_path / "source.txt"
    source.write_text("not a provider fence", encoding="utf-8")
    symlink = tmp_path / "provider-link.sqlite"
    symlink.symlink_to(source)
    with pytest.raises(ProviderCustodyDenied, match="mutable or unowned"):
        ProviderCustodyWorker(state_path=symlink, **base)


def test_absent_or_failing_external_effect_witness_denies(tmp_path):
    for i, witness in enumerate((None, FalseWitness(), ExceptionWitness())):
        signer, worker, effects, _, _ = setup(tmp_path / str(i), witness=witness)
        with pytest.raises(ProviderCustodyDenied):
            trusted_dispatch(worker, signer.sign(instruction()))
        assert not effects


class FalseWitness:
    def reserve_provider_effect(self, **_):
        return False


class ExceptionWitness:
    def reserve_provider_effect(self, **_):
        raise RuntimeError("remote trust point unavailable")


def test_provider_failure_is_ambiguous_and_never_reexecuted(tmp_path):
    calls = []

    def fail(command):
        calls.append(command)
        raise OSError("provider may already have committed")

    signer, worker, _, _, _ = setup(tmp_path, execute=fail)
    signed = signer.sign(instruction())
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(worker, signed)
    assert worker.status("effect-1") == "AMBIGUOUS"
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(worker, signed)
    assert len(calls) == 1


def test_cloned_database_cannot_double_execute_with_shared_external_witness(tmp_path):
    signer, worker, effects, provider_signer, witness = setup(tmp_path / "original")
    clone_path = tmp_path / "clone" / "provider-effects.sqlite"
    clone_path.parent.mkdir(parents=True)
    clone_path.parent.chmod(0o700)
    shutil.copyfile(worker.path, clone_path)
    clone_path.chmod(0o600)
    signed = signer.sign(instruction())
    trusted_dispatch(worker, signed)
    clone_calls = []
    clone = ProviderCustodyWorker(
        state_path=clone_path, host_id="host-1", epoch=4,
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        host_command_public_key=signer.public_key_bytes,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=provider_signer, effect_witness=witness,
        execute=lambda command: clone_calls.append(command),
        trusted_clock=TEST_NOW,
    )
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(clone, signed)
    assert len(effects) == 1
    assert clone_calls == []


def _provider_child_worker(connection, state_path, signer_key, receipt_key, target):
    worker = ProviderCustodyWorker(
        state_path=state_path, host_id="host-1", epoch=4,
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        host_command_public_key=signer_key,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=receipt_key,
        effect_witness=SyntheticGlobalEffectWitness(),
        execute=lambda command: {"target": target["value"], "result": command.operation},
        trusted_clock=TEST_NOW,
    )
    connection.send("ready")
    signed = connection.recv_bytes()
    ack = trusted_dispatch(worker, signed)
    connection.send((ack.provider_receipt_digest, ack.receipt_signature))
    connection.close()


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires fork")
def test_separate_provider_process_is_not_retargeted_by_parent_python_object(tmp_path):
    context = multiprocessing.get_context("fork")
    target = {"value": "allowed-target"}
    signer_key = Ed25519PrivateKey.generate()
    provider_key = Ed25519PrivateKey.generate()
    signer = HostDispatchSigner(signer_key, host_id="host-1", epoch=4, trusted_clock=TEST_NOW)
    parent, child = context.Pipe()
    process = context.Process(
        target=_provider_child_worker,
        args=(child, tmp_path / "separate.sqlite", signer.public_key_bytes, provider_key, target),
    )
    process.start()
    child.close()
    try:
        assert parent.poll(3) and parent.recv() == "ready"
        target["value"] = "attacker-target"
        parent.send_bytes(signer.sign(instruction()))
        assert parent.poll(3)
        provider_result_digest, signature = parent.recv()
        assert len(signature) == 64
        assert provider_result_digest == sha256(canonical_json_bytes({
            "target": "allowed-target", "result": "inspect"
        })).hexdigest()
    finally:
        parent.close()
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
    assert process.exitcode == 0
    assert target["value"] == "attacker-target"


def _kill_after_effect_worker(signed, state_path, host_public_key, provider_signer, marker_path):
    def physical_effect(_command):
        Path(marker_path).write_text("physical effect happened", encoding="utf-8")
        os._exit(43)

    worker = ProviderCustodyWorker(
        state_path=state_path, host_id="host-1", epoch=4,
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        host_command_public_key=host_public_key,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=provider_signer,
        effect_witness=SyntheticGlobalEffectWitness(),
        execute=physical_effect,
        trusted_clock=TEST_NOW,
    )
    trusted_dispatch(worker, signed)


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires fork")
def test_process_crash_after_physical_effect_keeps_fence_and_denies_replay(tmp_path):
    signer_key = Ed25519PrivateKey.generate()
    provider_key = Ed25519PrivateKey.generate()
    signer = HostDispatchSigner(signer_key, host_id="host-1", epoch=4, trusted_clock=TEST_NOW)
    signed = signer.sign(instruction())
    state_path = tmp_path / "crashed.sqlite"
    marker_path = tmp_path / "physical.txt"
    process = multiprocessing.get_context("fork").Process(
        target=_kill_after_effect_worker,
        args=(signed, state_path, signer.public_key_bytes, provider_key, marker_path),
    )
    process.start()
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert process.exitcode == 43
    assert marker_path.read_text(encoding="utf-8") == "physical effect happened"
    restarted = ProviderCustodyWorker(
        state_path=state_path, host_id="host-1", epoch=4,
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        host_command_public_key=signer.public_key_bytes,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9,
        receipt_signer=provider_key,
        effect_witness=SyntheticGlobalEffectWitness(),
        execute=lambda _: pytest.fail("replay must not cause duplicate physical effect"),
        trusted_clock=TEST_NOW,
    )
    assert restarted.status("effect-1") == "RESERVED"
    with pytest.raises(ProviderCustodyDenied):
        trusted_dispatch(restarted, signed)
