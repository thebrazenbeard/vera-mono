import hashlib

from vera_core import (
    IndependentBehaviorReviewAssessment,
    IndependentBehaviorReviewReceipt,
    QualifiedVeraRuntime,
    RegimeReturnMetrics,
    RegimeReturnQualificationResult,
)


ITEMS_DIGEST = "a" * 64
ARTIFACT_JSON = '{"schema":"REGIME_RETURN_MEASUREMENT_TEST"}'
ARTIFACT_DIGEST = hashlib.sha256(ARTIFACT_JSON.encode("utf-8")).hexdigest()
RECEIPT_DIGEST = "b" * 64


def _measurement(state="PARTIAL"):
    return RegimeReturnQualificationResult(
        metrics=RegimeReturnMetrics(
            intervening_regime_count=3,
            first_return_surprise=0.9,
            second_step_mse=0.01,
            baseline_second_step_mse=0.8,
            second_step_baseline_advantage=0.79,
            original_late_mse=0.001,
            old_task_degradation=0.009,
        ),
        packet={
            "schema": "VERA_AGI_EVALUATION_PACKET_V1",
            "subject": {
                "repository": "thebrazenbeard/vera-mono",
                "exact_head": "1" * 40,
                "runtime_binding": "LOCAL_TEST_RUNTIME",
            },
            "probe": {
                "probe_id": "regime-return",
                "family": "REGIME_RETURN",
                "held_out": True,
                "curator_independence": "INDEPENDENT_MODEL",
                "items_digest": ITEMS_DIGEST,
            },
            "contamination": {
                "training_overlap": "NONE_KNOWN",
                "post_disclosure_tuning": False,
                "developer_item_access": False,
                "tool_access": [],
            },
            "results": {
                "attempted": 3,
                "passed": 2,
                "failed": 1,
                "raw_artifact_digest": ARTIFACT_DIGEST,
                "negative_results_preserved": True,
            },
            "dimension_states": {
                "RETENTION_AND_INTERFERENCE": state,
            },
            "independent_review": None,
            "claim_ceiling": "REGIME_RETURN_MEASUREMENT_ONLY_NOT_AGI",
        },
        qualification_artifact_json=ARTIFACT_JSON,
        qualification_artifact_digest=ARTIFACT_DIGEST,
    )


def _assessment(*, passed=True, receipt_digest=RECEIPT_DIGEST):
    return IndependentBehaviorReviewAssessment(
        task_id="task",
        consumer_id="consumer",
        probe_id="regime-return",
        review_id="review",
        latest_status="PASS" if passed else "FAIL",
        latest_receipt_digest=receipt_digest,
        transport_available=True,
        behavior_effect_current=True,
        current_behavior_effect_receipt_digest="c" * 64,
        current_authority_subject_digest="d" * 64,
        current_review_subject_digest="e" * 64,
        current_authority_evidence_digest="f" * 64,
        current_review_evidence_digest="0" * 64,
        current_verdict="PASS" if passed else "FAIL",
        current_authority_current=True,
        current_operationally_separate=True,
        current_signatures_valid=True,
        current_matches_receipt=True,
        passed=passed,
        reason="live-current" if passed else "failed",
    )


def _receipt(*, items_digest=ITEMS_DIGEST, result_digest=ARTIFACT_DIGEST):
    return IndependentBehaviorReviewReceipt(
        sequence=1,
        task_id="task",
        consumer_id="consumer",
        probe_id="regime-return",
        review_id="review",
        status="PASS",
        payload={
            "schema": "VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_RECEIPT_V1",
            "requirement": {
                "held_out_probe_set_digest": items_digest,
            },
            "observation": {
                "result_digest": result_digest,
                "verdict": "PASS",
            },
        },
        predecessor_digest="9" * 64,
        receipt_digest=RECEIPT_DIGEST,
    )


class _Store:
    def __init__(self, receipt):
        self.receipt = receipt

    def latest(self, task_id, consumer_id, probe_id, review_id):
        assert (task_id, consumer_id, probe_id, review_id) == (
            "task",
            "consumer",
            "regime-return",
            "review",
        )
        return self.receipt


class _Runtime:
    def __init__(self, assessment, receipt):
        self._assessment = assessment
        self.independent_behavior_reviews = _Store(receipt)

    def assess_independent_behavior_review(
        self,
        task_id,
        consumer_id,
        probe_id,
        review_id,
    ):
        assert (task_id, consumer_id, probe_id, review_id) == (
            "task",
            "consumer",
            "regime-return",
            "review",
        )
        return self._assessment


def _promote(runtime, measurement=None):
    return QualifiedVeraRuntime.promote_regime_return_qualification(
        runtime,
        measurement or _measurement(),
        task_id="task",
        consumer_id="consumer",
        probe_id="regime-return",
        review_id="review",
    )


def test_live_review_promotes_bound_regime_return_measurement():
    result = _promote(_Runtime(_assessment(), _receipt()))

    assert result.promoted is True
    assert result.packet["dimension_states"] == {
        "RETENTION_AND_INTERFERENCE": "PASS",
    }
    assert result.packet["independent_review"]["receipt_digest"] == RECEIPT_DIGEST
    assert result.packet["independent_review"]["live_current"] is True


def test_regime_promotion_rejects_review_of_different_hidden_cut():
    result = _promote(
        _Runtime(
            _assessment(),
            _receipt(items_digest="8" * 64),
        )
    )

    assert result.promoted is False
    assert "held-out" in result.reason


def test_regime_promotion_rejects_review_of_different_artifact():
    result = _promote(
        _Runtime(
            _assessment(),
            _receipt(result_digest="7" * 64),
        )
    )

    assert result.promoted is False
    assert "qualification artifact" in result.reason


def test_regime_promotion_rejects_historical_review():
    result = _promote(
        _Runtime(
            _assessment(passed=False),
            _receipt(),
        )
    )

    assert result.promoted is False
    assert "live-current" in result.reason


def test_failed_regime_measurement_cannot_be_rescued():
    result = _promote(
        _Runtime(_assessment(), _receipt()),
        measurement=_measurement("FAIL"),
    )

    assert result.promoted is False
    assert "measurement state" in result.reason
    assert result.packet["dimension_states"]["RETENTION_AND_INTERFERENCE"] == "FAIL"


def test_regime_promotion_rejects_receipt_not_matching_current_assessment():
    result = _promote(
        _Runtime(
            _assessment(receipt_digest="6" * 64),
            _receipt(),
        )
    )

    assert result.promoted is False
    assert "current review receipt" in result.reason
