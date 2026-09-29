import pytest

from vera_core import (
    CORRECTIVE_STAGE_ORDER,
    CorrectionRecurrence,
    CorrectionTransferGuard,
    CorrectiveLearningLedger,
    CorrectiveStage,
    ExactCaseCorrectionMemorizer,
)
from vera_memory import (
    LearnedInfluenceBlocked,
    LearnedInfluenceGate,
    LearnedRevision,
    ReviewDisposition,
)


def _completed_correction(tmp_path):
    ledger = CorrectiveLearningLedger(tmp_path / "corrections.sqlite")
    ledger.start(
        correction_id="corr-unsafe-dispatch",
        failure_signature_id="sig:conflicting-evidence-dispatch",
        summary="Original dispatch ignored conflicting evidence.",
        evidence_refs=("failure:original-case",),
    )
    for stage in CORRECTIVE_STAGE_ORDER[1:-1]:
        ledger.advance(
            "corr-unsafe-dispatch",
            stage=stage,
            summary=f"Completed {stage.value.lower()} stage.",
            evidence_refs=(f"evidence:{stage.value.lower()}",),
        )
    ledger.advance(
        "corr-unsafe-dispatch",
        stage=CorrectiveStage.PREVENT,
        summary="Prevent dispatch when the failure signature recurs.",
        evidence_refs=("evidence:root-cause",),
        guardrail_refs=("guard:conflict-fail-closed",),
        verification_refs=("verify:held-out-recurrence",),
    )
    return ledger.state("corr-unsafe-dispatch")


def _revision(state):
    return LearnedRevision(
        state.failure_signature_id,
        state.events[-1].event_digest,
    )


def test_reviewed_correction_transfers_to_structurally_different_recurrence(tmp_path):
    state = _completed_correction(tmp_path)
    gate = LearnedInfluenceGate()
    revision = _revision(state)
    gate.review(
        association_id=revision.association_id,
        memory_revision_id=revision.memory_revision_id,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:independent-held-out",
    )

    guard = CorrectionTransferGuard(
        correction=state,
        revision=revision,
        influence_gate=gate,
        original_case_id="case:original",
        original_surface={
            "source": "original-provider",
            "shape": "original-field-layout",
        },
    )
    recurrence = CorrectionRecurrence(
        case_id="case:different-recurrence",
        failure_signature_id=state.failure_signature_id,
        surface={
            "source": "different-provider",
            "shape": "different-field-layout",
        },
    )

    decision = guard.decide(
        recurrence,
        cue_event_id="cue:different-recurrence",
    )

    assert recurrence.case_id != guard.original_case_id
    assert decision.case_distinct is True
    assert decision.surface_distinct is True
    assert decision.outcome == "PREVENT"
    assert decision.learned_influence is not None
    assert decision.learned_influence.review_evidence_ref == (
        "review:independent-held-out"
    )
    assert decision.authorization_effect == "NONE"


def test_exact_case_memorizer_does_not_fake_correction_transfer():
    baseline = ExactCaseCorrectionMemorizer(("case:original",))
    recurrence = CorrectionRecurrence(
        case_id="case:different-recurrence",
        failure_signature_id="sig:conflicting-evidence-dispatch",
        surface={"source": "different-provider"},
    )
    assert baseline.should_prevent(recurrence) is False


def test_unreviewed_revision_is_blocked_for_correction_transfer(tmp_path):
    state = _completed_correction(tmp_path)
    guard = CorrectionTransferGuard(
        correction=state,
        revision=_revision(state),
        influence_gate=LearnedInfluenceGate(),
        original_case_id="case:original",
    )
    recurrence = CorrectionRecurrence(
        case_id="case:recurrence",
        failure_signature_id=state.failure_signature_id,
        surface={"shape": "new"},
    )

    with pytest.raises(LearnedInfluenceBlocked, match="review"):
        guard.decide(recurrence, cue_event_id="cue:unreviewed")


def test_quarantined_revision_is_blocked_for_correction_transfer(tmp_path):
    state = _completed_correction(tmp_path)
    gate = LearnedInfluenceGate()
    revision = _revision(state)
    gate.review(
        association_id=revision.association_id,
        memory_revision_id=revision.memory_revision_id,
        disposition=ReviewDisposition.QUARANTINED,
        evidence_ref="review:contradiction",
    )
    guard = CorrectionTransferGuard(
        correction=state,
        revision=revision,
        influence_gate=gate,
        original_case_id="case:original",
    )

    with pytest.raises(LearnedInfluenceBlocked):
        guard.decide(
            CorrectionRecurrence(
                case_id="case:recurrence",
                failure_signature_id=state.failure_signature_id,
                surface={"shape": "new"},
            ),
            cue_event_id="cue:quarantined",
        )


def test_incomplete_correction_cannot_drive_transfer(tmp_path):
    ledger = CorrectiveLearningLedger(tmp_path / "corrections.sqlite")
    ledger.start(
        correction_id="corr-open",
        failure_signature_id="sig:open",
        summary="Observed failure.",
        evidence_refs=("failure:open",),
    )
    state = ledger.state("corr-open")

    with pytest.raises(ValueError, match="completed"):
        CorrectionTransferGuard(
            correction=state,
            revision=LearnedRevision(
                state.failure_signature_id,
                state.events[-1].event_digest,
            ),
            influence_gate=LearnedInfluenceGate(),
            original_case_id="case:original",
        )


def test_correction_revision_must_bind_completed_ledger_head(tmp_path):
    state = _completed_correction(tmp_path)

    with pytest.raises(ValueError, match="ledger head"):
        CorrectionTransferGuard(
            correction=state,
            revision=LearnedRevision(
                state.failure_signature_id,
                "not-the-completed-event-digest",
            ),
            influence_gate=LearnedInfluenceGate(),
            original_case_id="case:original",
        )


def test_different_failure_signature_is_allowed_without_false_positive(tmp_path):
    state = _completed_correction(tmp_path)
    gate = LearnedInfluenceGate()
    revision = _revision(state)
    gate.review(
        association_id=revision.association_id,
        memory_revision_id=revision.memory_revision_id,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:independent-held-out",
    )
    guard = CorrectionTransferGuard(
        correction=state,
        revision=revision,
        influence_gate=gate,
        original_case_id="case:original",
    )

    decision = guard.decide(
        CorrectionRecurrence(
            case_id="case:safe-control",
            failure_signature_id="sig:different-safe-condition",
            surface={"shape": "safe-control"},
        ),
        cue_event_id="cue:safe-control",
    )

    assert decision.outcome == "ALLOW"
    assert decision.learned_influence is None
    assert decision.authorization_effect == "NONE"
