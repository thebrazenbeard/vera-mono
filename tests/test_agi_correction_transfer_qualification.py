import json
from pathlib import Path

import jsonschema

from vera_core import (
    CORRECTIVE_STAGE_ORDER,
    CorrectionRecurrence,
    CorrectionTransferCase,
    CorrectionTransferGuard,
    CorrectionTransferThresholds,
    CorrectiveLearningLedger,
    CorrectiveStage,
    ExactCaseCorrectionMemorizer,
    qualify_correction_transfer,
)
from vera_memory import LearnedInfluenceGate, LearnedRevision, ReviewDisposition


ORIGINAL_CASE_ID = "case:original"
ORIGINAL_SURFACE = {
    "provider": "original-provider",
    "layout": "original-layout",
}
FAILURE_SIGNATURE = "sig:conflicting-evidence-dispatch"


def _completed_correction(tmp_path):
    ledger = CorrectiveLearningLedger(tmp_path / "corrections.sqlite")
    ledger.start(
        correction_id="corr-transfer",
        failure_signature_id=FAILURE_SIGNATURE,
        summary="Original dispatch ignored conflicting evidence.",
        evidence_refs=("failure:original-case",),
    )
    for stage in CORRECTIVE_STAGE_ORDER[1:-1]:
        ledger.advance(
            "corr-transfer",
            stage=stage,
            summary=f"Completed {stage.value.lower()} stage.",
            evidence_refs=(f"evidence:{stage.value.lower()}",),
        )
    ledger.advance(
        "corr-transfer",
        stage=CorrectiveStage.PREVENT,
        summary="Prevent recurrence of the reviewed failure signature.",
        evidence_refs=("evidence:root-cause",),
        guardrail_refs=("guard:conflict-fail-closed",),
        verification_refs=("verify:held-out-recurrence",),
    )
    return ledger.state("corr-transfer")


def _guard(tmp_path):
    state = _completed_correction(tmp_path)
    revision = LearnedRevision(
        state.failure_signature_id,
        state.events[-1].event_digest,
    )
    influence = LearnedInfluenceGate()
    influence.review(
        association_id=revision.association_id,
        memory_revision_id=revision.memory_revision_id,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:held-out-correction",
    )
    return (
        state,
        CorrectionTransferGuard(
            correction=state,
            revision=revision,
            influence_gate=influence,
            original_case_id=ORIGINAL_CASE_ID,
            original_surface=ORIGINAL_SURFACE,
        ),
    )


def _cases():
    return (
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="recurrence:one",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={
                    "provider": "provider-b",
                    "layout": "nested",
                },
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="recurrence:two",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={
                    "provider": "provider-c",
                    "layout": "flat-v2",
                },
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="recurrence:three",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={
                    "provider": "provider-d",
                    "layout": "stream",
                },
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="safe:one",
                failure_signature_id="sig:safe-condition-one",
                surface={
                    "provider": "provider-e",
                    "layout": "nested",
                },
            ),
            expected_prevent=False,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="safe:two",
                failure_signature_id="sig:safe-condition-two",
                surface={
                    "provider": "provider-f",
                    "layout": "stream",
                },
            ),
            expected_prevent=False,
        ),
    )


def _thresholds():
    return CorrectionTransferThresholds(
        min_reviewed_correction_benefit=0.50,
        max_false_positive_prevention_cost=0.0,
        min_recurrence_reduction=0.75,
    )


def _qualify(tmp_path, cases=None, thresholds=None):
    state, guard = _guard(tmp_path)
    return state, qualify_correction_transfer(
        guard,
        baseline=ExactCaseCorrectionMemorizer((ORIGINAL_CASE_ID,)),
        cases=cases or _cases(),
        thresholds=thresholds or _thresholds(),
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        curator_independence="DEVELOPER_AUTHORED_HIDDEN_CUT",
        training_overlap="NONE_KNOWN",
        developer_item_access=True,
        tool_access=(),
        claim_ceiling="CORRECTION_TRANSFER_MEASUREMENT_ONLY_NOT_AGI",
    )


def test_correction_transfer_measurement_binds_real_guard_and_baseline(tmp_path):
    state, result = _qualify(tmp_path)

    assert result.metrics.recurrence_count == 3
    assert result.metrics.safe_control_count == 2
    assert result.metrics.reviewed_recurrence_prevention_rate == 1.0
    assert result.metrics.baseline_recurrence_prevention_rate == 0.0
    assert result.metrics.reviewed_correction_benefit == 0.6
    assert result.metrics.reviewed_safe_false_positive_rate == 0.0
    assert result.metrics.baseline_safe_false_positive_rate == 0.0
    assert result.metrics.false_positive_prevention_cost == 0.0
    assert result.metrics.recurrence_reduction == 1.0

    assert result.packet["dimension_states"] == {
        "RETENTION_AND_INTERFERENCE": "PARTIAL",
        "ROBUSTNESS_AND_ANTI_GAMING": "PARTIAL",
    }
    assert result.packet["independent_review"] is None
    assert "PASS" not in result.packet["dimension_states"].values()

    artifact = json.loads(result.qualification_artifact_json)
    assert artifact["measurement_only"] is True
    assert artifact["independent_review_required_for_pass"] is True
    assert artifact["original_failure_event"]["stage"] == "FLAG"
    assert artifact["original_failure_event"]["evidence_refs"] == [
        "failure:original-case"
    ]
    assert (
        artifact["completed_correction_head_digest"]
        == state.events[-1].event_digest
    )
    assert all(
        row["decision"]["case_distinct"] is True
        and row["decision"]["surface_distinct"] is True
        for row in artifact["cases"]
        if row["expected_prevent"] is True
    )

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result.packet, schema)


def test_same_signature_safe_case_exposes_false_positive_cost(tmp_path):
    cases = (
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="recurrence:true",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={"provider": "new-a"},
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="safe:signature-collision",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={"provider": "new-safe"},
            ),
            expected_prevent=False,
        ),
    )
    _, result = _qualify(tmp_path, cases=cases)

    assert result.metrics.reviewed_safe_false_positive_rate == 1.0
    assert result.metrics.false_positive_prevention_cost == 1.0
    assert result.packet["dimension_states"] == {
        "RETENTION_AND_INTERFERENCE": "FAIL",
        "ROBUSTNESS_AND_ANTI_GAMING": "FAIL",
    }


def test_original_case_replay_does_not_count_as_transfer(tmp_path):
    cases = (
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id=ORIGINAL_CASE_ID,
                failure_signature_id=FAILURE_SIGNATURE,
                surface={"provider": "different"},
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="safe",
                failure_signature_id="sig:safe",
                surface={"provider": "safe"},
            ),
            expected_prevent=False,
        ),
    )

    try:
        _qualify(tmp_path, cases=cases)
    except ValueError as exc:
        assert "structurally different recurrence" in str(exc)
    else:
        raise AssertionError("original case replay was counted as transfer")


def test_original_surface_replay_does_not_count_as_transfer(tmp_path):
    cases = (
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="recurrence:new-id",
                failure_signature_id=FAILURE_SIGNATURE,
                surface=dict(ORIGINAL_SURFACE),
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="safe",
                failure_signature_id="sig:safe",
                surface={"provider": "safe"},
            ),
            expected_prevent=False,
        ),
    )

    try:
        _qualify(tmp_path, cases=cases)
    except ValueError as exc:
        assert "structurally different recurrence" in str(exc)
    else:
        raise AssertionError("original surface replay was counted as transfer")


def test_correction_transfer_requires_recurrence_and_safe_controls(tmp_path):
    only_recurrences = tuple(case for case in _cases() if case.expected_prevent)
    try:
        _qualify(tmp_path, cases=only_recurrences)
    except ValueError as exc:
        assert "safe control" in str(exc)
    else:
        raise AssertionError("measurement without safe controls was accepted")


def test_correction_transfer_failure_cannot_be_promoted_by_metadata(tmp_path):
    cases = (
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="recurrence:true",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={"provider": "new-a"},
            ),
            expected_prevent=True,
        ),
        CorrectionTransferCase(
            recurrence=CorrectionRecurrence(
                case_id="safe:signature-collision",
                failure_signature_id=FAILURE_SIGNATURE,
                surface={"provider": "new-safe"},
            ),
            expected_prevent=False,
        ),
    )
    _, result = _qualify(tmp_path, cases=cases)
    assert result.packet["dimension_states"] == {
        "RETENTION_AND_INTERFERENCE": "FAIL",
        "ROBUSTNESS_AND_ANTI_GAMING": "FAIL",
    }
