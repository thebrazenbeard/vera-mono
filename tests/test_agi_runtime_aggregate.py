from vera_core import (
    AGIPacketReviewBinding,
    IndependentBehaviorReviewAssessment,
    IndependentBehaviorReviewReceipt,
    QualifiedVeraRuntime,
)


HEAD = "1" * 40


def _packet(
    *,
    probe_id,
    family,
    dimensions,
    receipt_digest,
    items_digest,
    artifact_digest,
):
    return {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": "thebrazenbeard/vera-mono",
            "exact_head": HEAD,
            "runtime_binding": "LOCAL_TEST_RUNTIME",
        },
        "probe": {
            "probe_id": probe_id,
            "family": family,
            "held_out": True,
            "curator_independence": "INDEPENDENT_MODEL",
            "items_digest": items_digest,
        },
        "contamination": {
            "training_overlap": "NONE_KNOWN",
            "post_disclosure_tuning": False,
            "developer_item_access": False,
            "tool_access": [],
        },
        "results": {
            "attempted": 4,
            "passed": 3,
            "failed": 1,
            "raw_artifact_digest": artifact_digest,
            "negative_results_preserved": True,
        },
        "dimension_states": dict(dimensions),
        "independent_review": {
            "status": "PASS",
            "receipt_digest": receipt_digest,
            "live_current": True,
            "qualification_artifact_digest": artifact_digest,
        },
        "claim_ceiling": "DIMENSION_RESEARCH_EVIDENCE_ONLY",
    }


def _assessment(binding, receipt_digest, *, passed=True):
    return IndependentBehaviorReviewAssessment(
        task_id=binding.task_id,
        consumer_id=binding.consumer_id,
        probe_id=binding.probe_id,
        review_id=binding.review_id,
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
        reason="live-current" if passed else "not current",
    )


def _receipt(binding, receipt_digest, *, items_digest, artifact_digest):
    return IndependentBehaviorReviewReceipt(
        sequence=1,
        task_id=binding.task_id,
        consumer_id=binding.consumer_id,
        probe_id=binding.probe_id,
        review_id=binding.review_id,
        status="PASS",
        payload={
            "schema": "VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_RECEIPT_V1",
            "requirement": {
                "held_out_probe_set_digest": items_digest,
            },
            "observation": {
                "result_digest": artifact_digest,
                "verdict": "PASS",
            },
        },
        predecessor_digest="9" * 64,
        receipt_digest=receipt_digest,
    )


class _Store:
    def __init__(self, receipts):
        self.receipts = receipts

    def latest(self, task_id, consumer_id, probe_id, review_id):
        return self.receipts[(task_id, consumer_id, probe_id, review_id)]


class _Runtime:
    def __init__(self, assessments, receipts):
        self.assessments = assessments
        self.independent_behavior_reviews = _Store(receipts)

    def assess_independent_behavior_review(
        self, task_id, consumer_id, probe_id, review_id
    ):
        return self.assessments[
            (task_id, consumer_id, probe_id, review_id)
        ]


def _bound_packet(index, family, dimensions):
    probe_id = f"probe-{index}"
    receipt_digest = f"{index:x}" * 64
    receipt_digest = receipt_digest[:64]
    items_digest = f"{(index + 6):x}" * 64
    items_digest = items_digest[:64]
    artifact_digest = f"{(index + 10):x}" * 64
    artifact_digest = artifact_digest[:64]
    binding = AGIPacketReviewBinding(
        probe_id=probe_id,
        task_id=f"task-{index}",
        consumer_id=f"consumer-{index}",
        review_id=f"review-{index}",
    )
    packet = _packet(
        probe_id=probe_id,
        family=family,
        dimensions=dimensions,
        receipt_digest=receipt_digest,
        items_digest=items_digest,
        artifact_digest=artifact_digest,
    )
    assessment = _assessment(binding, receipt_digest)
    receipt = _receipt(
        binding,
        receipt_digest,
        items_digest=items_digest,
        artifact_digest=artifact_digest,
    )
    key = (
        binding.task_id,
        binding.consumer_id,
        binding.probe_id,
        binding.review_id,
    )
    return packet, binding, key, assessment, receipt


def _runtime_for(*entries):
    assessments = {}
    receipts = {}
    for _, _, key, assessment, receipt in entries:
        assessments[key] = assessment
        receipts[key] = receipt
    return _Runtime(assessments, receipts)


def test_runtime_aggregate_accepts_current_reviewed_pass_packet():
    entry = _bound_packet(
        1,
        "NOVEL_MAPPING",
        {
            "NOVEL_TASK_TRANSFER": "PASS",
            "LEARNING_EFFICIENCY": "PASS",
        },
    )
    packet, binding, *_ = entry
    runtime = _runtime_for(entry)

    aggregate = QualifiedVeraRuntime.aggregate_agi_qualification(
        runtime,
        [packet],
        subject_head=HEAD,
        review_bindings=(binding,),
        claim_ceiling="RUNTIME_VERIFIED_AGGREGATE_NOT_AGI",
    )

    assert aggregate["dimension_states"]["NOVEL_TASK_TRANSFER"] == "PASS"
    assert aggregate["dimension_states"]["LEARNING_EFFICIENCY"] == "PASS"
    assert aggregate["aggregate_state"] == "PARTIALLY_EVALUATED"
    assert aggregate["independent_review_state"] == "NOT_REVIEWED"


def test_runtime_aggregate_rejects_pass_packet_without_review_binding():
    entry = _bound_packet(
        2,
        "NOVEL_MAPPING",
        {"NOVEL_TASK_TRANSFER": "PASS"},
    )
    packet = entry[0]
    runtime = _runtime_for(entry)

    try:
        QualifiedVeraRuntime.aggregate_agi_qualification(
            runtime,
            [packet],
            subject_head=HEAD,
            review_bindings=(),
            claim_ceiling="RUNTIME_VERIFIED_AGGREGATE_NOT_AGI",
        )
    except ValueError as exc:
        assert "review binding" in str(exc)
    else:
        raise AssertionError("unbound PASS packet entered runtime aggregate")


def test_runtime_aggregate_rejects_family_dimension_overclaim():
    entry = _bound_packet(
        3,
        "NOVEL_MAPPING",
        {
            "NOVEL_TASK_TRANSFER": "PASS",
            "CROSS_DOMAIN_BREADTH": "PASS",
        },
    )
    packet, binding, *_ = entry
    runtime = _runtime_for(entry)

    try:
        QualifiedVeraRuntime.aggregate_agi_qualification(
            runtime,
            [packet],
            subject_head=HEAD,
            review_bindings=(binding,),
            claim_ceiling="RUNTIME_VERIFIED_AGGREGATE_NOT_AGI",
        )
    except ValueError as exc:
        assert "outside registered family scope" in str(exc)
    else:
        raise AssertionError("family overclaim entered runtime aggregate")


def test_runtime_aggregate_rejects_stale_or_mismatched_review_receipt():
    entry = list(
        _bound_packet(
            4,
            "NOVEL_MAPPING",
            {"NOVEL_TASK_TRANSFER": "PASS"},
        )
    )
    packet, binding, key, _, receipt = entry
    entry[3] = _assessment(binding, "5" * 64)
    runtime = _runtime_for(tuple(entry))

    try:
        QualifiedVeraRuntime.aggregate_agi_qualification(
            runtime,
            [packet],
            subject_head=HEAD,
            review_bindings=(binding,),
            claim_ceiling="RUNTIME_VERIFIED_AGGREGATE_NOT_AGI",
        )
    except ValueError as exc:
        assert "current review receipt" in str(exc)
    else:
        raise AssertionError("stale review receipt entered runtime aggregate")


def test_dimension_reviews_do_not_self_award_global_independent_state():
    entries = (
        _bound_packet(
            5,
            "COMPOSITIONAL_TRANSFER",
            {
                "CROSS_DOMAIN_BREADTH": "PASS",
                "NOVEL_TASK_TRANSFER": "PASS",
            },
        ),
        _bound_packet(
            6,
            "NOVEL_MAPPING",
            {"LEARNING_EFFICIENCY": "PASS"},
        ),
        _bound_packet(
            7,
            "REGIME_RETURN",
            {"RETENTION_AND_INTERFERENCE": "PASS"},
        ),
        _bound_packet(
            8,
            "AMBIGUOUS_SPEC",
            {
                "LONG_HORIZON_AGENCY": "PASS",
                "METACOGNITIVE_CALIBRATION": "PASS",
                "ROBUSTNESS_AND_ANTI_GAMING": "PASS",
            },
        ),
        _bound_packet(
            9,
            "EXTERNAL_ENVIRONMENT",
            {"EXTERNAL_GENERALIZATION": "PASS"},
        ),
    )
    packets = [entry[0] for entry in entries]
    bindings = tuple(entry[1] for entry in entries)
    runtime = _runtime_for(*entries)

    aggregate = QualifiedVeraRuntime.aggregate_agi_qualification(
        runtime,
        packets,
        subject_head=HEAD,
        review_bindings=bindings,
        claim_ceiling="RUNTIME_VERIFIED_AGGREGATE_NOT_AGI",
    )

    assert all(
        aggregate["dimension_states"][dimension] == "PASS"
        for dimension in aggregate["required_dimensions"]
    )
    assert aggregate["aggregate_state"] == "SURVIVES_CURRENT_CONTRACT"
    assert aggregate["independent_review_state"] == "NOT_REVIEWED"
