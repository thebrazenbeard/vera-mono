import pytest

from vera_assurance import EffectFence, EffectState
from vera_core import OutboundAuditError, OutboundExecutionAudit


REQUEST = "a" * 64
MECHANICAL = "b" * 64
AUTHORITY = "c" * 64
CURRENTNESS = "d" * 64
RESULT = "e" * 64
RECONCILIATION = "f" * 64


def authority_event(audit, effect_id="provider:test:e1"):
    audit.append(
        effect_id=effect_id,
        effect_kind="PROVIDER/test/WRITE",
        event_type="AUTHORITY_VERIFIED",
        payload={
            "request_digest": REQUEST,
            "mechanical_permit_digest": MECHANICAL,
            "authority_evidence_digest": AUTHORITY,
            "lifecycle_permit": {
                "permit_digest": CURRENTNESS,
            },
            "authority_details": {
                "kind": "PROVIDER",
                "authority_id": "issuer/test",
            },
        },
    )


def reserve(fence, effect_id="provider:test:e1"):
    return fence.reserve(
        effect_id=effect_id,
        request_digest=REQUEST,
        mechanical_permit_digest=MECHANICAL,
        authority_evidence_digest=AUTHORITY,
        currentness_evidence_digest=CURRENTNESS,
    )


def claim(fence, effect_id="provider:test:e1"):
    return fence.claim_dispatch(
        effect_id=effect_id,
        request_digest=REQUEST,
        mechanical_permit_digest=MECHANICAL,
        authority_evidence_digest=AUTHORITY,
        currentness_evidence_digest=CURRENTNESS,
    )


def test_restart_repairs_audit_after_reserve_crash_window(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    authority_event(audit)
    reserve(fence)

    consistency = audit.repair_from_fence(fence)

    assert [event.event_type for event in audit.events("provider:test:e1")] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
    ]
    assert consistency.repaired_effect_ids == ("provider:test:e1",)
    assert consistency.fence_effect_count == 1


def test_restart_repairs_all_mechanical_stages_through_commit(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    authority_event(audit)
    reserve(fence)
    claim(fence)
    fence.settle(
        "provider:test:e1",
        result_digest=RESULT,
        completion_known=True,
    )

    consistency = audit.repair_from_fence(fence)

    assert [event.event_type for event in audit.events("provider:test:e1")] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "COMMITTED",
    ]
    assert audit.latest("provider:test:e1").payload["result_digest"] == RESULT
    assert consistency.repaired_effect_ids == ("provider:test:e1",)


def test_restart_repairs_direct_reconciliation_after_crash(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    authority_event(audit)
    reserve(fence)
    claim(fence)
    fence.reconcile_unknown(
        "provider:test:e1",
        effect_occurred=False,
        result_digest=None,
        reconciliation_evidence_digest=RECONCILIATION,
    )

    consistency = audit.repair_from_fence(fence)

    assert [event.event_type for event in audit.events("provider:test:e1")] == [
        "AUTHORITY_VERIFIED",
        "RESERVED",
        "EXECUTING",
        "RECONCILED_NO_EFFECT",
    ]
    latest = audit.latest("provider:test:e1")
    assert latest.payload["reconciliation_evidence_digest"] == RECONCILIATION
    assert latest.payload["restart_reconstructed_from_effect_fence"] is True
    assert consistency.repaired_effect_ids == ("provider:test:e1",)


def test_authority_verified_without_fence_is_safe_but_visible(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    authority_event(audit, "provider:test:authority-only")

    consistency = audit.repair_from_fence(fence)

    assert consistency.authority_only_effect_ids == (
        "provider:test:authority-only",
    )
    assert consistency.fence_effect_count == 0
    assert consistency.audited_effect_count == 1


def test_unaudited_fence_effect_fails_qualified_integrity(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    reserve(fence, "provider:test:raw-bypass")

    with pytest.raises(OutboundAuditError, match="no qualified outbound audit"):
        audit.repair_from_fence(fence)


def test_audit_and_fence_evidence_mismatch_fails_closed(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    audit.append(
        effect_id="provider:test:e1",
        effect_kind="PROVIDER/test/WRITE",
        event_type="AUTHORITY_VERIFIED",
        payload={
            "request_digest": "9" * 64,
            "mechanical_permit_digest": MECHANICAL,
            "authority_evidence_digest": AUTHORITY,
            "lifecycle_permit": {"permit_digest": CURRENTNESS},
            "authority_details": {"kind": "PROVIDER"},
        },
    )
    reserve(fence)

    with pytest.raises(OutboundAuditError, match="request_digest"):
        audit.repair_from_fence(fence)


def test_repaired_audit_preserves_fence_terminal_state(tmp_path):
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    fence = EffectFence(tmp_path / "effects.sqlite")
    authority_event(audit)
    reserve(fence)
    claim(fence)
    fence.settle(
        "provider:test:e1",
        result_digest=None,
        completion_known=False,
    )

    consistency = audit.repair_from_fence(fence)

    assert fence.read("provider:test:e1").state is EffectState.ATTEMPTED_UNKNOWN
    assert audit.latest("provider:test:e1").event_type == "ATTEMPTED_UNKNOWN"
    assert consistency.repaired_effect_ids == ("provider:test:e1",)
