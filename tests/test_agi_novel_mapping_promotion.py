from dataclasses import replace
import hashlib

from vera_core import (
    IndependentBehaviorReviewAssessment,
    IndependentBehaviorReviewReceipt,
    NovelMappingMetrics,
    NovelMappingQualificationResult,
    QualifiedVeraRuntime,
)


ITEMS_DIGEST = "a" * 64
ARTIFACT_JSON = '{"schema":"NOVEL_MAPPING_MEASUREMENT_TEST"}'
ARTIFACT_DIGEST = hashlib.sha256(ARTIFACT_JSON.encode("utf-8")).hexdigest()
RECEIPT_DIGEST = "b" * 64


def _measurement(states=None):
    states = states or {
        "NOVEL_TASK_TRANSFER": "PARTIAL",
        "LEARNING_EFFICIENCY": "PARTIAL",
    }
    return NovelMappingQualificationResult(
        metrics=NovelMappingMetrics(
            learner_mse_curve=(1.0, 0.1),
            baseline_mse_curve=(1.0, 1.0),
            late_mse=0.1,
            baseline_late_mse=1.0,
            samples_to_threshold=2,
            baseline_delta=0.9,
            baseline_ratio=10.0,
        ),
        packet={
            "schema": "VERA_AGI_EVALUATION_PACKET_V1",
            "subject": {
                "repository": "thebrazenbeard/vera-mono",
                "exact_head": "1" * 40,
                "runtime_binding": "LOCAL_TEST_RUNTIME",
            },
            "probe": {
                "probe_id": "novel-map",
                "family": "NOVEL_MAPPING",
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
                "attempted": 2,
                "passed": 1,
                "failed": 1,
                "raw_artifact_digest": ARTIFACT_DIGEST,
                "negative_results_preserved": True,
            },
            "dimension_states": dict(states),
            "independent_review": None,
            "claim_ceiling": "NOVEL_MAPPING_MEASUREMENT_ONLY",
        },
        qualification_artifact_json=ARTIFACT_JSON,
        qualification_artifact_digest=ARTIFACT_DIGEST,
    )


def _assessment(*, passed=True, receipt_digest=RECEIPT_DIGEST):
    return IndependentBehaviorReviewAssessment(
        task_id="task",
        consumer_id="consumer",
        probe_id="novel-map",
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
        probe_id="novel-map",
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
            "novel-map",
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
            "novel-map",
            "review",
        )
        return self._assessment


def _promote(runtime, measurement=None):
    return QualifiedVeraRuntime.promote_novel_mapping_qualification(
        runtime,
        measurement or _measurement(),
        task_id="task",
        consumer_id="consumer",
        probe_id="novel-map",
        review_id="review",
    )


def test_runtime_promotes_only_live_review_bound_to_cut_and_measurement():
    result = _promote(_Runtime(_assessment(), _receipt()))

    assert result.promoted is True
    assert result.packet["dimension_states"] == {
        "NOVEL_TASK_TRANSFER": "PASS",
        "LEARNING_EFFICIENCY": "PASS",
    }
    assert result.packet["independent_review"]["receipt_digest"] == RECEIPT_DIGEST
    assert result.packet["independent_review"]["live_current"] is True


def test_promotion_rejects_review_of_different_held_out_cut():
    result = _promote(
        _Runtime(
            _assessment(),
            _receipt(items_digest="8" * 64),
        )
    )

    assert result.promoted is False
    assert "held-out" in result.reason
    assert result.packet["dimension_states"]["NOVEL_TASK_TRANSFER"] == "PARTIAL"


def test_promotion_rejects_review_of_different_measurement_artifact():
    result = _promote(
        _Runtime(
            _assessment(),
            _receipt(result_digest="7" * 64),
        )
    )

    assert result.promoted is False
    assert "qualification artifact" in result.reason
    assert result.packet["dimension_states"]["LEARNING_EFFICIENCY"] == "PARTIAL"


def test_promotion_rejects_historical_or_noncurrent_review():
    result = _promote(
        _Runtime(
            _assessment(passed=False),
            _receipt(),
        )
    )

    assert result.promoted is False
    assert "live-current" in result.reason


def test_promotion_rejects_receipt_not_matching_current_assessment():
    result = _promote(
        _Runtime(
            _assessment(receipt_digest="6" * 64),
            _receipt(),
        )
    )

    assert result.promoted is False
    assert "current review receipt" in result.reason


def test_failed_measurement_cannot_be_rescued_by_independent_review():
    measurement = _measurement(
        {
            "NOVEL_TASK_TRANSFER": "FAIL",
            "LEARNING_EFFICIENCY": "PARTIAL",
        }
    )
    result = _promote(
        _Runtime(_assessment(), _receipt()),
        measurement=measurement,
    )

    assert result.promoted is False
    assert "measurement state" in result.reason
    assert result.packet["dimension_states"]["NOVEL_TASK_TRANSFER"] == "FAIL"
