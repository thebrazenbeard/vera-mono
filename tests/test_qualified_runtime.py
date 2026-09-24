from coordination_bus import CoordinationBus, InMemoryCoordinationRepository
from vera_core import (
    HmacEffectReconciliationAuthority,
    HmacProviderAuthority,
    QualifiedVeraRuntime,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
PROVIDER = "example-provider"


def accepted_state(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    request = AdmissionRequest(
        record_id="m1",
        text="qualified runtime bootstrap",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id=PROJECT,
        governed_identity_id=IDENTITY,
    )
    admitted = lifecycle.memory.admit(
        request,
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def test_qualified_runtime_composes_state_bus_effects_and_recovery(tmp_path):
    state = accepted_state(tmp_path)
    provider = HmacProviderAuthority(
        "provider-authority",
        PROVIDER,
        b"p" * 32,
    )
    recovery = HmacEffectReconciliationAuthority(
        "recovery-authority",
        b"r" * 32,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={PROVIDER: provider},
        reconciliation_verifier=recovery,
        coordination_bus=CoordinationBus(InMemoryCoordinationRepository()),
    )
    assert runtime.coordination is not None
    assert runtime.recovery is not None
    assert runtime.lifecycle.effect_fence is not None
    assert runtime.lifecycle.effect_fence.path == runtime.fence.path

    permit = runtime.accepted_permit()
    payload = {"qualified": True}
    request_digest = runtime.effects.provider_request_digest(
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload=payload,
    )
    authority = provider.issue(
        effect_id="qualified-effect",
        operation="WRITE",
        request_digest=request_digest,
        lifecycle_permit_digest=permit.permit_digest,
    )
    result = runtime.effects.dispatch_provider_effect(
        permit=permit,
        effect_id="qualified-effect",
        provider_id=PROVIDER,
        operation="WRITE",
        request_payload=payload,
        authority=authority,
        execute=lambda: {"ok": True},
    )
    assert result.value == {"ok": True}
    assert runtime.resume_context()["effect_recovery_required"] is False


def test_qualified_runtime_does_not_invent_unconfigured_authority(tmp_path):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    assert runtime.coordination is None
    assert runtime.recovery is None
