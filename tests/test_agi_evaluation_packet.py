import json
from pathlib import Path

import jsonschema

from vera_core import (
    AGIContaminationDisclosure,
    HeldOutCase,
    HeldOutProbe,
    build_agi_evaluation_packet,
    run_held_out_probe,
)


def _result():
    probe = HeldOutProbe(
        probe_id="novel-map-packet",
        family="NOVEL_MAPPING",
        curator_independence="INDEPENDENT_MODEL",
        cases=(
            HeldOutCase(case_id="a", model_input=2, expected=6),
            HeldOutCase(case_id="b", model_input=3, expected=9),
        ),
    )
    return run_held_out_probe(
        probe,
        subject=lambda value: value * 3,
        score=lambda prediction, expected: prediction == expected,
        contamination=AGIContaminationDisclosure(
            training_overlap="NONE_KNOWN",
            post_disclosure_tuning=False,
            developer_item_access=False,
            tool_access=(),
        ),
    )


def test_build_evaluation_packet_matches_governed_schema():
    packet = build_agi_evaluation_packet(
        _result(),
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="LOCAL_TEST_RUNTIME",
        dimension_states={
            "NOVEL_TASK_TRANSFER": "PARTIAL",
            "LEARNING_EFFICIENCY": "PARTIAL",
        },
        claim_ceiling="HELD_OUT_RESEARCH_EVIDENCE_ONLY_NOT_AGI",
    )

    schema = json.loads(
        Path(
            "architecture/schemas/VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(packet, schema)

    assert packet["probe"]["held_out"] is True
    assert packet["probe"]["items_digest"] == _result().items_digest
    assert packet["results"]["negative_results_preserved"] is True
    assert packet["independent_review"] is None


def test_evaluation_packet_requires_all_family_target_dimensions():
    try:
        build_agi_evaluation_packet(
            _result(),
            repository="thebrazenbeard/vera-mono",
            exact_head="2" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            dimension_states={"NOVEL_TASK_TRANSFER": "PARTIAL"},
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "LEARNING_EFFICIENCY" in str(exc)
    else:
        raise AssertionError("packet omitted a required family target dimension")


def test_evaluation_packet_rejects_non_exact_head_and_invalid_state():
    result = _result()

    try:
        build_agi_evaluation_packet(
            result,
            repository="thebrazenbeard/vera-mono",
            exact_head="not-a-head",
            runtime_binding="LOCAL_TEST_RUNTIME",
            dimension_states={
                "NOVEL_TASK_TRANSFER": "PARTIAL",
                "LEARNING_EFFICIENCY": "PARTIAL",
            },
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "exact_head" in str(exc)
    else:
        raise AssertionError("invalid exact head was accepted")

    try:
        build_agi_evaluation_packet(
            result,
            repository="thebrazenbeard/vera-mono",
            exact_head="3" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            dimension_states={
                "NOVEL_TASK_TRANSFER": "SURVIVES",
                "LEARNING_EFFICIENCY": "PARTIAL",
            },
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "dimension state" in str(exc)
    else:
        raise AssertionError("invalid dimension state was accepted")



def test_generic_packet_builder_cannot_self_award_dimension_pass():
    try:
        build_agi_evaluation_packet(
            _result(),
            repository="thebrazenbeard/vera-mono",
            exact_head="9" * 40,
            runtime_binding="LOCAL_TEST_RUNTIME",
            dimension_states={
                "NOVEL_TASK_TRANSFER": "PASS",
                "LEARNING_EFFICIENCY": "PASS",
            },
            claim_ceiling="RESEARCH_ONLY",
        )
    except ValueError as exc:
        assert "cannot self-award PASS" in str(exc)
    else:
        raise AssertionError("generic held-out packet self-awarded PASS")
