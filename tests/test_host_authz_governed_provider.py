"""Source composition of independent provider custody and Vera's real gateway.

The fixtures are synthetic: they do not qualify OS custody or a live provider.
"""

from __future__ import annotations

import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from vera_core import HmacProviderAuthority, LifecycleActionDenied, OutboundTrustError
from vera_core.host_authz.governed_provider import (
    GovernedProviderDenied,
    GovernedProviderExecutor,
    build_governed_provider_worker,
)
from vera_core.host_authz.provider_custody import HostDispatchSigner, ProviderCustodyDenied
from vera_memory import AdmissionRequest, MemoryClass
from test_host_authz_provider_custody import (
    SyntheticGlobalEffectWitness, TEST_START_SIGNER, start_lease_for,
)
from test_host_authz_qualified_bridge import (
    INSTANCE, PROVIDER, _instruction, _runtime,
)
from test_qualified_runtime import StubProviderTransport


def _executor(tmp_path):
    runtime, authority, transport, _ = _runtime(tmp_path)
    executor = GovernedProviderExecutor(
        runtime=runtime, authority=authority,
        provider_id=PROVIDER, provider_instance_id=INSTANCE,
    )
    return runtime, authority, transport, executor


def test_adapter_uses_canonical_lifecycle_trust_fence_and_audit(tmp_path):
    runtime, _, transport, executor = _executor(tmp_path)
    command = _instruction(effect_id="governed-adapter-1")
    result = executor(command)
    mechanical = f"provider:{PROVIDER}:{command.effect_id}"
    assert transport.calls == [("inspect", command.request_payload)]
    assert result["schema"] == "HOST_AUTHZ_GOVERNED_PROVIDER_OUTCOME_V1"
    assert result["mechanical_effect_id"] == mechanical
    assert result["fence_state"] == "COMMITTED"
    assert result["result_digest"] == runtime.fence.read(mechanical).result_digest
    assert runtime.audit.latest(mechanical).event_type == "COMMITTED"
    assert runtime.assess_provider_effect(command.effect_id).terminal
    with pytest.raises(Exception):
        executor(command)
    assert len(transport.calls) == 1


def test_bound_transport_or_authority_replaced_denies_before_effect(tmp_path):
    runtime, authority, transport, executor = _executor(tmp_path)
    runtime.provider_execution_transports[PROVIDER] = StubProviderTransport(PROVIDER)
    with pytest.raises(GovernedProviderDenied, match="changed"):
        executor(_instruction(effect_id="retarget-transport"))
    assert transport.calls == []
    runtime.provider_execution_transports[PROVIDER] = transport
    runtime.effects._provider_authority_verifiers[PROVIDER] = HmacProviderAuthority(
        "different-issuer", PROVIDER, b"x" * 32,
    )
    with pytest.raises(GovernedProviderDenied, match="changed"):
        executor(_instruction(effect_id="retarget-issuer"))
    assert transport.calls == []
    runtime.effects._provider_authority_verifiers[PROVIDER] = authority


def test_instance_request_and_source_provider_substitution_denied(tmp_path):
    _, _, transport, executor = _executor(tmp_path)
    with pytest.raises(GovernedProviderDenied, match="different instance"):
        executor(_instruction(provider_instance_id="other-instance"))
    altered = _instruction(effect_id="digest-tamper")
    altered.request_payload["record"] = "tampered"
    with pytest.raises(GovernedProviderDenied, match="digest"):
        executor(altered)
    with pytest.raises(GovernedProviderDenied, match="identity"):
        GovernedProviderExecutor(
            runtime=_runtime(tmp_path / "other")[0],
            authority=_runtime(tmp_path / "another")[1],
            provider_id="source:repo", provider_instance_id=INSTANCE,
        )
    assert transport.calls == []


def test_canonical_lifecycle_change_blocks_provider_transport(tmp_path):
    runtime, _, transport, executor = _executor(tmp_path)
    runtime.lifecycle.memory.admit(
        AdmissionRequest(
            record_id="unaccepted-change", text="invalidate accepted state",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test", authority_ref="authority:test",
            privacy_ref="privacy:test", provenance_refs=("source:test",),
            operation_id="op-unaccepted", project_id="vera-mono",
            governed_identity_id="vera",
        ),
        expected_head=runtime.lifecycle.memory.current_head,
    )
    with pytest.raises(LifecycleActionDenied):
        executor(_instruction(effect_id="blocked-lifecycle"))
    assert transport.calls == []


@pytest.mark.skipif(sys.platform != "linux", reason="provider custody fence requires a Linux-owned private state file")
def test_provider_process_factory_fences_and_receipts_only_after_gateway_commit(tmp_path):
    runtime, authority, transport, _ = _executor(tmp_path)
    provider_state = tmp_path / "provider-private"
    provider_state.mkdir(mode=0o700)
    provider_state.chmod(0o700)
    now = lambda: 2000
    host_key, provider_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    worker = build_governed_provider_worker(
        state_path=provider_state / "effects.sqlite",
        runtime=runtime, provider_authority=authority,
        provider_id=PROVIDER, provider_instance_id=INSTANCE,
        host_id="host-1", epoch=4,
        host_command_public_key=host_key.public_key().public_bytes_raw(),
        receipt_signer=provider_key,
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9, effect_witness=SyntheticGlobalEffectWitness(),
        trusted_clock=now,
    )
    assert type(worker._execute) is GovernedProviderExecutor
    signer = HostDispatchSigner(host_key, host_id="host-1", epoch=4,
                                trusted_clock=now)
    command = _instruction(effect_id="provider-real-gateway")
    signed = signer.sign(command)
    ack = worker.dispatch(signed, start_lease=start_lease_for(command))
    assert ack.effect_id == command.effect_id
    assert runtime.fence.read(f"provider:{PROVIDER}:{command.effect_id}").state.value == "COMMITTED"
    assert runtime.audit.latest(f"provider:{PROVIDER}:{command.effect_id}").event_type == "COMMITTED"
    assert len(transport.calls) == 1
    assert worker.status(command.effect_id) == "COMMITTED"
    with pytest.raises(ProviderCustodyDenied):
        worker.dispatch(signed, start_lease=start_lease_for(command))
    assert len(transport.calls) == 1


def test_canonical_transport_error_is_unknown_without_retry(tmp_path):
    runtime, _, transport, executor = _executor(tmp_path)

    def fail(*_):
        raise RuntimeError("synthetic provider crashed after handoff")

    transport.execute = fail
    with pytest.raises(RuntimeError, match="synthetic provider"):
        executor(_instruction(effect_id="ambiguous-provider"))
    assessment = runtime.assess_provider_effect("ambiguous-provider")
    assert assessment.recovery_required
    assert not assessment.dispatch_candidate_allowed


@pytest.mark.skipif(sys.platform != "linux", reason="provider custody fence requires a Linux-owned private state file")
def test_worker_preserves_ambiguous_status_after_governed_transport_failure(tmp_path):
    runtime, authority, transport, _ = _executor(tmp_path)
    provider_state = tmp_path / "provider-unknown"
    provider_state.mkdir(mode=0o700)
    provider_state.chmod(0o700)
    now = lambda: 2000
    host_key = Ed25519PrivateKey.generate()
    worker = build_governed_provider_worker(
        state_path=provider_state / "effects.sqlite",
        runtime=runtime, provider_authority=authority,
        provider_id=PROVIDER, provider_instance_id=INSTANCE,
        host_id="host-1", epoch=4,
        host_command_public_key=host_key.public_key().public_bytes_raw(),
        receipt_signer=Ed25519PrivateKey.generate(),
        witness_start_public_key=TEST_START_SIGNER.public_key().public_bytes_raw(),
        witness_leader_epoch=9, effect_witness=SyntheticGlobalEffectWitness(),
        trusted_clock=now,
    )

    def fail(*_):
        raise RuntimeError("synthetic provider failed after canonical handoff")

    transport.execute = fail
    command = _instruction(effect_id="provider-ambiguous-gateway")
    signed = HostDispatchSigner(host_key, host_id="host-1", epoch=4,
                                trusted_clock=now).sign(command)
    with pytest.raises(ProviderCustodyDenied, match="provider"):
        worker.dispatch(signed, start_lease=start_lease_for(command))
    assert worker.status(command.effect_id) == "AMBIGUOUS"
    state = runtime.assess_provider_effect(command.effect_id)
    assert state.recovery_required and not state.dispatch_candidate_allowed
    with pytest.raises(ProviderCustodyDenied, match="reserved"):
        worker.dispatch(signed, start_lease=start_lease_for(command))


def test_untrusted_provider_cannot_construct_governed_runtime(tmp_path):
    with pytest.raises(OutboundTrustError):
        _runtime(tmp_path, trusted=False)
