"""Synthetic host acceptance: not evidence of production consent authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import multiprocessing
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.grants import SignedGrantVerifier
from vera_core.host_authz.consent_admission import (
    ConsentAdmissionDenied, ConsentEffectUnknown, ConsentScope, ConsentAdmission,
)
from vera_core.host_authz.service import ProviderDispatch
from test_host_authz_service import _make, _sign

from vera_core.host_authz.consent_admission import ConsentScope, ConsentAdmission


requires_linux_posix_state = pytest.mark.skipif(
    sys.platform != "linux",
    reason="consent admission's durable store and flock need a Linux/POSIX host",
)


def test_scope_digest_is_exact_and_stable():
    scope = ConsentScope(
        participant_id="person-a", purpose="research", model_id="model-a",
        adapter_id="adapter-a", runtime_id="runtime-a", subject_id="subject-a",
        host_id="host-a", provider_id="provider-a", provider_instance_id="p-instance-a",
    )
    assert len(scope.digest) == 64
    assert scope.digest == ConsentScope(**scope.body()).digest


class SyntheticOnlyWitness:
    """Test oracle only; no independent host ownership or split-brain proof."""

    def __init__(self):
        self.calls = []
        self.allowed = True

    def attest_start(self, *, authority_id, epoch, sequence, grant_id, effect_id, scope_digest):
        self.calls.append(("START", sequence, grant_id, effect_id, scope_digest))
        return self.allowed

    def attest_scope_revoke(self, *, authority_id, epoch, sequence, scope_digest):
        self.calls.append(("REVOKE", sequence, scope_digest))
        return self.allowed


def setup(tmp_path, *, provider=None, witness=None):
    ctx = _make(tmp_path)
    payload = {"record": "synthetic"}
    token = _sign(ctx, payload)
    grant = ctx["service"].grant_verifier.verify(token)
    claim_digest = sha256(canonical_json_bytes({
        "schema": "HOST_AUTHZ_CLAIM_V1", "grant": grant.canonical_body(),
        "provider_instance_id": grant.provider_instance_id,
        "request_digest": grant.request_digest,
    })).hexdigest()
    record = ctx["ledger"].claim(
        grant.grant_id, claim_digest, datetime.fromtimestamp(2000, tz=UTC)
    )
    effect_id = sha256(canonical_json_bytes({
        "schema": "HOST_AUTHZ_EFFECT_ID_V1", "host_id": grant.host_id,
        "epoch": grant.epoch, "claim_sequence": record.sequence,
        "claim_digest": claim_digest, "grant_id": grant.grant_id,
    })).hexdigest()
    instruction = ProviderDispatch(
        effect_id=effect_id, grant_id=grant.grant_id,
        provider_id=grant.provider_id,
        provider_instance_id=grant.provider_instance_id,
        operation=grant.operation,
        request_digest=grant.request_digest,
        claim_sequence=record.sequence,
        participant_id=grant.participant_id, purpose=grant.purpose,
        request_payload=payload,
    )
    calls = []

    def default_provider(value):
        calls.append(value)
        return "host-observed-response-unverified"

    real_witness = witness if witness is not None else SyntheticOnlyWitness()
    coordinator = ConsentAdmission(
        tmp_path / "consent.sqlite", authority_id="host-a", epoch=7,
        grant_verifier=ctx["service"].grant_verifier,
        claim_ledger=ctx["ledger"], witness=real_witness,
        provider_execute=provider or default_provider,
    )
    return coordinator, token, instruction, calls, real_witness, ctx


@requires_linux_posix_state
def test_durable_start_precedes_handoff_and_cannot_replay(tmp_path):
    coordinator, token, instruction, calls, witness, _ = setup(tmp_path)
    assert coordinator.perform(token, instruction) == "host-observed-response-unverified"
    result = coordinator.read(instruction.effect_id)
    assert result.state == "RETURNED_UNVERIFIED"
    assert result.claim_sequence == instruction.claim_sequence
    assert result.scope_digest == ConsentScope.from_grant(
        coordinator._verifier.verify(token)
    ).digest
    assert len(calls) == 1
    assert witness.calls[0][0] == "START"
    with pytest.raises(ConsentAdmissionDenied, match="already started"):
        coordinator.perform(token, instruction)
    assert len(calls) == 1


@requires_linux_posix_state
def test_revocation_before_start_denies_effect(tmp_path):
    coordinator, token, instruction, calls, witness, _ = setup(tmp_path)
    scope = ConsentScope.from_grant(coordinator._verifier.verify(token))
    sequence = coordinator.revoke_scope(scope)
    assert sequence == 1
    assert coordinator.revoked(scope) is True
    with pytest.raises(ConsentAdmissionDenied, match="revoked"):
        coordinator.perform(token, instruction)
    assert coordinator.read(instruction.effect_id) is None
    assert not calls
    assert [item[0] for item in witness.calls] == ["REVOKE"]


@requires_linux_posix_state
def test_revocation_waits_for_started_provider_and_only_linearizes_later(tmp_path):
    started = threading.Event()
    release = threading.Event()
    finished = []

    def slow_provider(_instruction):
        started.set()
        assert release.wait(timeout=4)
        finished.append("called")
        return "returned"

    coordinator, token, instruction, _, witness, _ = setup(tmp_path, provider=slow_provider)
    scope = ConsentScope.from_grant(coordinator._verifier.verify(token))
    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatch = pool.submit(coordinator.perform, token, instruction)
        assert started.wait(3)
        revoke = pool.submit(coordinator.revoke_scope, scope)
        assert revoke.running()
        assert coordinator.revoked(scope) is False
        release.set()
        assert dispatch.result(timeout=4) == "returned"
        assert revoke.result(timeout=4) == 2
    assert finished == ["called"]
    assert [item[:2] for item in witness.calls] == [("START", 1), ("REVOKE", 2)]
    assert coordinator.revoked(scope)


@requires_linux_posix_state
def test_claim_ledger_revocation_cannot_overtake_started_provider(tmp_path):
    started = threading.Event()
    release = threading.Event()
    revocation_witness_entered = threading.Event()

    def slow_provider(_instruction):
        started.set()
        assert release.wait(timeout=4)
        return "returned"

    coordinator, token, instruction, _, _, ctx = setup(tmp_path, provider=slow_provider)
    original_attestation = ctx["ledger"]._witness.attest_revocation

    def observe_revocation(**kwargs):
        revocation_witness_entered.set()
        return original_attestation(**kwargs)

    ctx["ledger"]._witness.attest_revocation = observe_revocation
    with ThreadPoolExecutor(max_workers=2) as pool:
        dispatch = pool.submit(coordinator.perform, token, instruction)
        assert started.wait(3)
        revoke = pool.submit(ctx["ledger"].revoke, instruction.grant_id)
        assert revoke.running()
        # Revocation must not linearize while the physical handoff that
        # already STARTED still holds the consent/effect admission lock.
        assert not revocation_witness_entered.wait(timeout=0.15)
        assert ctx["ledger"].read(instruction.grant_id).revoked is False
        release.set()
        assert dispatch.result(timeout=4) == "returned"
        assert revoke.result(timeout=4).revoked is True
    assert coordinator.read(instruction.effect_id).state == "RETURNED_UNVERIFIED"


@requires_linux_posix_state
def test_failed_external_witness_denies_without_start(tmp_path):
    witness = SyntheticOnlyWitness()
    witness.allowed = False
    coordinator, token, instruction, calls, _, _ = setup(tmp_path, witness=witness)
    with pytest.raises(ConsentAdmissionDenied, match="witness denied"):
        coordinator.perform(token, instruction)
    assert coordinator.read(instruction.effect_id) is None
    assert not calls
    with pytest.raises(ConsentAdmissionDenied, match="witness denied"):
        coordinator.revoke_scope(ConsentScope.from_grant(coordinator._verifier.verify(token)))


@requires_linux_posix_state
def test_grant_that_expires_while_waiting_for_host_lock_denied(tmp_path, monkeypatch):
    coordinator, token, instruction, calls, _, ctx = setup(tmp_path)
    first_verified = threading.Event()
    actual_verify = SignedGrantVerifier.verify
    verify_calls = []

    def observed_verify(verifier, envelope):
        verify_calls.append(True)
        outcome = actual_verify(verifier, envelope)
        first_verified.set()
        return outcome

    monkeypatch.setattr(SignedGrantVerifier, "verify", observed_verify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with coordinator._host_lock():
            request = pool.submit(coordinator.perform, token, instruction)
            assert first_verified.wait(timeout=3)
            ctx["clock"]["value"] = 2200  # Expired after initial verification.
        with pytest.raises(ConsentAdmissionDenied, match="stale before physical START"):
            request.result(timeout=3)
    assert len(verify_calls) >= 2
    assert not calls
    assert coordinator.read(instruction.effect_id) is None


@requires_linux_posix_state
def test_witness_absent_fails_closed(tmp_path):
    coordinator, token, instruction, calls, _, ctx = setup(tmp_path)
    denied = ConsentAdmission(
        tmp_path / "other.sqlite", authority_id="host-a", epoch=7,
        grant_verifier=ctx["service"].grant_verifier,
        claim_ledger=ctx["ledger"], witness=None,
        provider_execute=lambda _: pytest.fail("dispatched without witness"),
    )
    with pytest.raises(ConsentAdmissionDenied, match="witness unavailable"):
        denied.perform(token, instruction)
    assert not calls


@requires_linux_posix_state
def test_claim_binding_and_effect_identity_tamper_denied(tmp_path):
    coordinator, token, instruction, calls, _, ctx = setup(tmp_path)
    for changed in (
        replace(instruction, effect_id="different-effect"),
        replace(instruction, claim_sequence=3),
        replace(instruction, request_payload={"record": "altered"}),
        replace(instruction, provider_instance_id="different-provider-instance"),
    ):
        with pytest.raises(ConsentAdmissionDenied):
            coordinator.perform(token, changed)
    assert not calls


@requires_linux_posix_state
def test_provider_exception_consumes_start_without_retry(tmp_path):
    calls = []

    def broken(_instruction):
        calls.append(True)
        raise OSError("provider may have acted before connection loss")

    coordinator, token, instruction, _, _, _ = setup(tmp_path, provider=broken)
    with pytest.raises(ConsentEffectUnknown):
        coordinator.perform(token, instruction)
    assert coordinator.read(instruction.effect_id).state == "AMBIGUOUS"
    with pytest.raises(ConsentAdmissionDenied, match="already started"):
        coordinator.perform(token, instruction)
    assert calls == [True]


@requires_linux_posix_state
def test_interrupted_provider_no_repeat(tmp_path):
    def interrupted(_instruction):
        raise KeyboardInterrupt()

    coordinator, token, instruction, _, _, _ = setup(tmp_path, provider=interrupted)
    with pytest.raises(KeyboardInterrupt):
        coordinator.perform(token, instruction)
    assert coordinator.read(instruction.effect_id).state == "AMBIGUOUS"
    with pytest.raises(ConsentAdmissionDenied):
        coordinator.perform(token, instruction)


@requires_linux_posix_state
def test_scope_revocation_is_exact_idempotent_and_model_isolated(tmp_path):
    coordinator, token, instruction, _, witness, _ = setup(tmp_path)
    scope = ConsentScope.from_grant(coordinator._verifier.verify(token))
    sequence = coordinator.revoke_scope(scope)
    assert coordinator.revoke_scope(scope) == sequence
    assert not coordinator.revoked(replace(scope, model_id="different-model"))
    assert [entry[0] for entry in witness.calls] == ["REVOKE"]


@requires_linux_posix_state
def test_host_owned_db_path_replacement_and_symlink_denied(tmp_path):
    coordinator, token, instruction, _, _, ctx = setup(tmp_path)
    saved = coordinator.path.with_suffix(".saved")
    coordinator.path.rename(saved)
    coordinator.path.symlink_to(saved)
    with pytest.raises(ConsentAdmissionDenied, match="identity changed"):
        coordinator.perform(token, instruction)
    with pytest.raises(ConsentAdmissionDenied):
        ConsentAdmission(
            coordinator.path, authority_id="host-a", epoch=7,
            grant_verifier=ctx["service"].grant_verifier,
            claim_ledger=ctx["ledger"], witness=SyntheticOnlyWitness(),
            provider_execute=lambda _: pytest.fail("unsafe file accepted"),
        )


@requires_linux_posix_state
def test_claim_ledger_replacement_before_physical_handoff_denied(tmp_path):
    coordinator, token, instruction, calls, _, ctx = setup(tmp_path)
    claim_path = ctx["ledger"].path
    saved = claim_path.with_suffix(".saved")
    claim_path.rename(saved)
    claim_path.symlink_to(saved)
    with pytest.raises(ConsentAdmissionDenied, match="storage was replaced"):
        coordinator.perform(token, instruction)
    assert coordinator.read(instruction.effect_id) is None
    assert not calls


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX flock qualification")
def test_cross_process_consent_revocation_waits_for_started_handoff(tmp_path):
    started = multiprocessing.get_context("fork").Event()
    release = multiprocessing.get_context("fork").Event()
    result = multiprocessing.get_context("fork").Queue()

    def provider(_instruction):
        started.set()
        if not release.wait(5):
            raise RuntimeError("test timed out")
        return "returned"

    coordinator, token, instruction, _, _, _ = setup(tmp_path, provider=provider)
    scope = ConsentScope.from_grant(coordinator._verifier.verify(token))

    def worker():
        try:
            result.put(("OK", coordinator.perform(token, instruction)))
        except BaseException as exc:
            result.put(("ERROR", type(exc).__name__))

    process = multiprocessing.get_context("fork").Process(target=worker)
    process.start()
    try:
        assert started.wait(3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            revoker = pool.submit(coordinator.revoke_scope, scope)
            assert revoker.running()
            assert not coordinator.revoked(scope)
            release.set()
            assert revoker.result(timeout=4) == 2
        assert result.get(timeout=4) == ("OK", "returned")
    finally:
        release.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0
    assert coordinator.revoked(scope)


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX process crash qualification")
def test_abrupt_host_crash_after_durable_start_never_redispatches(tmp_path):
    context = multiprocessing.get_context("fork")

    def fatal_after_started(_instruction):
        os._exit(66)  # Synthetic abrupt host crash; START must already be durable.

    coordinator, token, instruction, _, _, ctx = setup(tmp_path, provider=fatal_after_started)
    process = context.Process(target=coordinator.perform, args=(token, instruction))
    process.start()
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert process.exitcode == 66
    assert coordinator.read(instruction.effect_id).state == "STARTED"
    with pytest.raises(ConsentAdmissionDenied, match="already started"):
        coordinator.perform(token, instruction)
    assert ctx["ledger"].read(instruction.grant_id).state == "RESERVED"
