import hashlib

from vera_core import (
    AmbiguousSpecMetrics,
    AmbiguousSpecQualificationResult,
    IndependentBehaviorReviewAssessment,
    IndependentBehaviorReviewReceipt,
    QualifiedVeraRuntime,
)


ITEMS_DIGEST = "a" * 64
ARTIFACT_JSON = '{"schema":"AMBIGUOUS_SPEC_MEASUREMENT_TEST"}'
ARTIFACT_DIGEST = hashlib.sha256(ARTIFACT_JSON.encode("utf-8")).hexdigest()
RECEIPT_DIGEST = "b" * 64


def _measurement(robustness_state="PARTIAL"):
    return AmbiguousSpecQualificationResult(
        metrics=AmbiguousSpecMetrics(
            ambiguous_case_count=4,
            clear_case_count=2,
            appropriate_abstention_rate=1.0,
            false_dispatch_rate=0.0,
            forced_baseline_false_dispatch_rate=1.0,
            false_dispatch_delta=1.0,
            clear_action_success_rate=1.0,
            paraphrase_consistency_rate=1.0,
        ),
        packet={
            "schema": "VERA_AGI_EVALUATION_PACKET_V1",
            "subject": {
                "repository": "thebrazenbeard/vera-mono",
                "exact_head": "1" * 40,
                "runtime_binding": "LOCAL_TEST_RUNTIME",
            },
            "probe": {
                "probe_id": "ambiguous-spec",
                "family": "AMBIGUOUS_SPEC",
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
                "attempted": 6,
                "passed": 6,
                "failed": 0,
                "raw_artifact_digest": ARTIFACT_DIGEST,
                "negative_results_preserved": True,
            },
            "dimension_states": {
                "METACOGNITIVE_CALIBRATION": "NOT_EVALUATED",
                "ROBUSTNESS_AND_ANTI_GAMING": robustness_state,
                "LONG_HORIZON_AGENCY": "NOT_EVALUATED",
            },
            "independent_review": None,
            "claim_ceiling": "AMBIGUOUS_SPEC_MEASUREMENT_ONLY_NOT_AGI",
        },
        qualification_artifact_json=ARTIFACT_JSON,
        qualification_artifact_digest=ARTIFACT_DIGEST,
    )


def _assessment(*, passed=True, receipt_digest=RECEIPT_DIGEST):
    return IndependentBehaviorReviewAssessment(
        task_id="task",
        consumer_id="consumer",
        probe_id="ambiguous-spec",
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
        probe_id="ambiguous-spec",
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
            "ambiguous-spec",
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
            "ambiguous-spec",
            "review",
        )
        return self._assessment


def _promote(runtime, measurement=None):
    return QualifiedVeraRuntime.promote_ambiguous_spec_qualification(
        runtime,
        measurement or _measurement(),
        task_id="task",
        consumer_id="consumer",
        probe_id="ambiguous-spec",
        review_id="review",
    )


def test_live_review_promotes_only_measured_robustness():
    result = _promote(_Runtime(_assessment(), _receipt()))

    assert result.promoted is True
    assert result.packet["dimension_states"] == {
        "METACOGNITIVE_CALIBRATION": "NOT_EVALUATED",
        "ROBUSTNESS_AND_ANTI_GAMING": "PASS",
        "LONG_HORIZON_AGENCY": "NOT_EVALUATED",
    }
    assert result.packet["independent_review"]["receipt_digest"] == RECEIPT_DIGEST
    assert result.packet["independent_review"]["live_current"] is True


def test_review_cannot_promote_unmeasured_metacognition_or_agency():
    result = _promote(_Runtime(_assessment(), _receipt()))
    assert result.packet["dimension_states"]["METACOGNITIVE_CALIBRATION"] == "NOT_EVALUATED"
    assert result.packet["dimension_states"]["LONG_HORIZON_AGENCY"] == "NOT_EVALUATED"


def test_ambiguous_spec_promotion_rejects_review_of_different_hidden_cut():
    result = _promote(
        _Runtime(
            _assessment(),
            _receipt(items_digest="8" * 64),
        )
    )
    assert result.promoted is False
    assert "held-out" in result.reason


def test_ambiguous_spec_promotion_rejects_review_of_different_artifact():
    result = _promote(
        _Runtime(
            _assessment(),
            _receipt(result_digest="7" * 64),
        )
    )
    assert result.promoted is False
    assert "qualification artifact" in result.reason


def test_ambiguous_spec_promotion_rejects_historical_review():
    result = _promote(
        _Runtime(
            _assessment(passed=False),
            _receipt(),
        )
    )
    assert result.promoted is False
    assert "live-current" in result.reason


def test_failed_ambiguity_measurement_cannot_be_rescued():
    result = _promote(
        _Runtime(_assessment(), _receipt()),
        measurement=_measurement("FAIL"),
    )
    assert result.promoted is False
    assert "measurement state" in result.reason
    assert result.packet["dimension_states"]["ROBUSTNESS_AND_ANTI_GAMING"] == "FAIL"
