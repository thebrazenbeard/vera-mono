import json
from pathlib import Path

import jsonschema

from vera_core import aggregate_agi_qualification


REQUIRED = (
    "CROSS_DOMAIN_BREADTH",
    "NOVEL_TASK_TRANSFER",
    "LEARNING_EFFICIENCY",
    "RETENTION_AND_INTERFERENCE",
    "LONG_HORIZON_AGENCY",
    "METACOGNITIVE_CALIBRATION",
    "ROBUSTNESS_AND_ANTI_GAMING",
    "EXTERNAL_GENERALIZATION",
)


def _packet(head: str, states: dict[str, str]) -> dict[str, object]:
    return {
        "schema": "VERA_AGI_EVALUATION_PACKET_V1",
        "subject": {
            "repository": "thebrazenbeard/vera-mono",
            "exact_head": head,
            "runtime_binding": "LOCAL_TEST_RUNTIME",
        },
        "probe": {
            "probe_id": "probe",
            "family": "NOVEL_MAPPING",
            "held_out": True,
            "curator_independence": "INDEPENDENT_MODEL",
            "items_digest": "a" * 64,
        },
        "contamination": {
            "training_overlap": "NONE_KNOWN",
            "post_disclosure_tuning": False,
            "developer_item_access": False,
            "tool_access": [],
        },
        "results": {
            "attempted": 1,
            "passed": 1,
            "failed": 0,
            "raw_artifact_digest": "b" * 64,
            "negative_results_preserved": True,
        },
        "dimension_states": states,
        "independent_review": None,
        "claim_ceiling": "RESEARCH_ONLY",
    }


def test_aggregate_cannot_exceed_weakest_required_dimension():
    head = "4" * 40
    states = {dimension: "PASS" for dimension in REQUIRED}
    packets = [_packet(head, states)]

    result = aggregate_agi_qualification(
        packets,
        subject_head=head,
        independent_review_state="NOT_REVIEWED",
        claim_ceiling="AGGREGATE_RESEARCH_ONLY_NOT_AGI",
    )
    assert result["aggregate_state"] == "SURVIVES_CURRENT_CONTRACT"

    failed = _packet(head, {"NOVEL_TASK_TRANSFER": "FAIL"})
    result = aggregate_agi_qualification(
        [packets[0], failed],
        subject_head=head,
        independent_review_state="SURVIVES_INDEPENDENT_REVIEW",
        claim_ceiling="AGGREGATE_RESEARCH_ONLY_NOT_AGI",
    )
    assert result["dimension_states"]["NOVEL_TASK_TRANSFER"] == "FAIL"
    assert result["aggregate_state"] == "FAILS_CURRENT_CONTRACT"


def test_aggregate_missing_dimension_is_only_partially_evaluated():
    head = "5" * 40
    partial_states = {
        dimension: "PASS"
        for dimension in REQUIRED
        if dimension != "EXTERNAL_GENERALIZATION"
    }
    result = aggregate_agi_qualification(
        [_packet(head, partial_states)],
        subject_head=head,
        independent_review_state="NOT_REVIEWED",
        claim_ceiling="AGGREGATE_RESEARCH_ONLY_NOT_AGI",
    )

    assert result["dimension_states"]["EXTERNAL_GENERALIZATION"] == "NOT_EVALUATED"
    assert result["aggregate_state"] == "PARTIALLY_EVALUATED"


def test_independent_review_promotes_only_all_pass_aggregate():
    head = "6" * 40
    states = {dimension: "PASS" for dimension in REQUIRED}
    result = aggregate_agi_qualification(
        [_packet(head, states)],
        subject_head=head,
        independent_review_state="SURVIVES_INDEPENDENT_REVIEW",
        claim_ceiling="AGGREGATE_RESEARCH_ONLY_NOT_AGI",
    )
    assert (
        result["aggregate_state"]
        == "SURVIVES_CURRENT_CONTRACT_INDEPENDENTLY_REVIEWED"
    )

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_AGGREGATE_QUALIFICATION_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result, schema)


def test_aggregate_rejects_mixed_subject_heads():
    head = "7" * 40
    try:
        aggregate_agi_qualification(
            [
                _packet(head, {"NOVEL_TASK_TRANSFER": "PASS"}),
                _packet("8" * 40, {"LEARNING_EFFICIENCY": "PASS"}),
            ],
            subject_head=head,
            independent_review_state="NOT_REVIEWED",
            claim_ceiling="AGGREGATE_RESEARCH_ONLY_NOT_AGI",
        )
    except ValueError as exc:
        assert "subject head" in str(exc)
    else:
        raise AssertionError("mixed exact heads were aggregated")
