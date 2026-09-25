from __future__ import annotations

import vera_core


def test_corrective_learning_survives_restart_and_enforces_full_cycle(tmp_path):
    assert hasattr(vera_core, "CorrectiveLearningLedger")

    path = tmp_path / "corrections.sqlite"
    ledger = vera_core.CorrectiveLearningLedger(path)
    ledger.start(
        correction_id="corr-1",
        failure_signature_id="failure-1",
        summary="Observed the concrete failure.",
        evidence_refs=("test:red",),
    )
    for stage in (
        vera_core.CorrectiveStage.UNDERSTAND,
        vera_core.CorrectiveStage.CALIBRATE,
        vera_core.CorrectiveStage.KNOW,
        vera_core.CorrectiveStage.UNLEARN,
    ):
        ledger.advance(
            "corr-1",
            stage=stage,
            summary=f"Completed {stage.value.lower()} stage.",
            evidence_refs=(f"evidence:{stage.value.lower()}",),
        )

    reopened = vera_core.CorrectiveLearningLedger(path)
    state = reopened.state("corr-1")
    assert state.current_stage is vera_core.CorrectiveStage.UNLEARN
    assert state.completed is False

    reopened.advance(
        "corr-1",
        stage=vera_core.CorrectiveStage.PREVENT,
        summary="Installed and verified a recurrence guard.",
        evidence_refs=("evidence:root-cause",),
        guardrail_refs=("guard:test-regression",),
        verification_refs=("verify:test-pass",),
    )
    final = vera_core.CorrectiveLearningLedger(path).state("corr-1")
    assert final.completed is True
    assert [event.stage for event in final.events] == list(vera_core.CORRECTIVE_STAGE_ORDER)


def test_state_directory_owns_corrective_learning_state(tmp_path):
    state = vera_core.VeraStateDirectory(
        tmp_path / "vera-state",
        project_id="vera-mono",
        identity_id="vera",
    )
    assert hasattr(state, "corrective_learning_ledger")

    state.corrective_learning_ledger().start(
        correction_id="corr-state-1",
        failure_signature_id="failure-state-1",
        summary="Bound the failure into Vera persistent state.",
        evidence_refs=("evidence:failure-state-1",),
    )

    reopened = vera_core.VeraStateDirectory(
        tmp_path / "vera-state",
        project_id="vera-mono",
        identity_id="vera",
    )
    correction = reopened.corrective_learning_ledger().state("corr-state-1")
    assert correction.current_stage is vera_core.CorrectiveStage.FLAG
    assert reopened.resume_context()["corrective_learning"]["open_count"] == 1


def test_corrective_learning_rejects_stage_skip_and_weak_prevention(tmp_path):
    ledger = vera_core.CorrectiveLearningLedger(tmp_path / "corrections.sqlite")
    ledger.start(
        correction_id="corr-guard",
        failure_signature_id="failure-guard",
        summary="Flagged.",
        evidence_refs=("evidence:flag",),
    )
    try:
        ledger.advance(
            "corr-guard",
            stage=vera_core.CorrectiveStage.KNOW,
            summary="Skipped ahead.",
            evidence_refs=("evidence:skip",),
        )
    except ValueError as exc:
        assert "advance exactly to UNDERSTAND" in str(exc)
    else:
        raise AssertionError("stage skipping must fail")

    for stage in vera_core.CORRECTIVE_STAGE_ORDER[1:-1]:
        ledger.advance(
            "corr-guard",
            stage=stage,
            summary=f"Completed {stage.value}.",
            evidence_refs=(f"evidence:{stage.value}",),
        )
    try:
        ledger.advance(
            "corr-guard",
            stage=vera_core.CorrectiveStage.PREVENT,
            summary="Claimed prevention without a verified guard.",
            evidence_refs=("evidence:prevent",),
        )
    except ValueError as exc:
        assert "guardrail_refs" in str(exc)
    else:
        raise AssertionError("unverified prevention must fail")


def test_corrective_learning_detects_durable_event_tamper(tmp_path):
    import sqlite3

    path = tmp_path / "corrections.sqlite"
    ledger = vera_core.CorrectiveLearningLedger(path)
    ledger.start(
        correction_id="corr-tamper",
        failure_signature_id="failure-tamper",
        summary="Original evidence-bound summary.",
        evidence_refs=("evidence:original",),
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE correction_events SET summary=? WHERE correction_id=?",
            ("tampered", "corr-tamper"),
        )
        db.commit()

    try:
        ledger.state("corr-tamper")
    except ValueError as exc:
        assert "event digest is invalid" in str(exc)
    else:
        raise AssertionError("tampered correction history must fail closed")