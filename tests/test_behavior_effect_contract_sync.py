import json
from pathlib import Path

from vera_core.behavior_effect_verification import (
    BEHAVIOR_EFFECT_KINDS,
    BEHAVIOR_EFFECT_STATUSES,
    BEHAVIOR_EFFECT_VERIFY_PREFIX,
)


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_behavior_effect_contract_matches_runtime_and_task_grammar():
    contract = load_json(
        "architecture/VERA_BEHAVIOR_EFFECT_VERIFICATION_V1.json"
    )
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")
    task = load_json(
        "architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json"
    )

    grammar = (
        f"{BEHAVIOR_EFFECT_VERIFY_PREFIX}|<consumer-id>|<probe-id>|"
        "<BEHAVIOR-or-EFFECT>|<stimulus-sha256>|<outcome-sha256>"
    )
    assert contract["requirement_grammar"]["syntax"] == grammar
    assert manifest["behavior_effect_verification"][
        "requirement_grammar"
    ] == grammar
    assert task["task_packet"][
        "evidence_requirement_behavior_effect_verification_grammar"
    ] == grammar
    assert set(contract["observation"]["statuses"]) == set(
        BEHAVIOR_EFFECT_STATUSES
    )
    assert set(contract["observation"]["kinds"]) == set(
        BEHAVIOR_EFFECT_KINDS
    )


def test_behavior_effect_contract_preserves_runtime_consumption_boundary():
    contract = load_json(
        "architecture/VERA_BEHAVIOR_EFFECT_VERIFICATION_V1.json"
    )
    prerequisite = contract["runtime_consumption_prerequisite"]
    boundaries = contract["boundaries"]

    assert prerequisite["exact_same_consumer_required"] is True
    assert prerequisite["live_current_PASS_required"] is True
    assert prerequisite[
        "runtime_consumption_PASS_is_behavior_effect_PASS"
    ] is False
    assert boundaries[
        "runtime_consumption_pass_is_not_behavior_effect_pass"
    ] is True
    assert boundaries[
        "behavior_effect_pass_is_not_protected_effect_authority"
    ] is True
    assert boundaries["behavior_effect_pass_is_not_deployment"] is True


def test_behavior_effect_contract_requires_live_external_refresh():
    contract = load_json(
        "architecture/VERA_BEHAVIOR_EFFECT_VERIFICATION_V1.json"
    )
    currentness = contract["live_currentness"]

    assert currentness[
        "stored_PASS_is_sufficient_without_refresh"
    ] is False
    assert currentness[
        "live_external_observation_must_match_exact_stored_PASS"
    ] is True
    assert currentness[
        "current_runtime_consumption_receipt_must_match_stored_behavior_receipt"
    ] is True
    assert currentness["missing_transport_after_stored_PASS"] == (
        "PENDING_NOT_CURRENT"
    )


def test_task_closeout_declares_behavior_effect_as_independent_gate():
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")
    task = load_json(
        "architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json"
    )

    assert (
        manifest["task_execution_closeout"]["closeout_gate"][
            "behavior_effect_required_when_declared"
        ]
        == "DENY_UNTIL_LIVE_CURRENT_PASS"
    )
    assert task["behavior_effect_verification"][
        "runtime_consumption_pass_is_behavior_effect_pass"
    ] is False
    assert "behavior/effect verification head" in task[
        "qualified_closeout_gate"
    ]["runtime_evidence_digest_binds"]
