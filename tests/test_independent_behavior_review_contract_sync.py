import json
from pathlib import Path

from vera_core import (
    INDEPENDENT_BEHAVIOR_REVIEW_STATUSES,
    INDEPENDENT_BEHAVIOR_REVIEW_VERIFY_PREFIX,
)

ROOT = Path(__file__).resolve().parents[1]

def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))

def expected_grammar():
    return (
        f"{INDEPENDENT_BEHAVIOR_REVIEW_VERIFY_PREFIX}|<consumer-id>|<probe-id>|"
        "<review-id>|<subject-actor-id>|<declaration-sha256>|"
        "<held-out-probe-set-sha256>|<probe-curator-id>|<evaluator-id>|"
        "<evaluator-key-id>|<evaluator-key-sha256>|<authority-id>|"
        "<authority-key-id>|<authority-key-sha256>"
    )

def test_independent_review_contract_matches_runtime_and_task_manifest():
    contract = load_json("architecture/VERA_INDEPENDENT_HELD_OUT_BEHAVIOR_REVIEW_V1.json")
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")
    task = load_json("architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json")
    grammar = expected_grammar()
    assert contract["requirement_grammar"]["syntax"] == grammar
    assert manifest["independent_behavior_review"]["requirement_grammar"] == grammar
    assert task["task_packet"]["evidence_requirement_independent_behavior_review_grammar"] == grammar
    assert set(contract["statuses"]) == set(INDEPENDENT_BEHAVIOR_REVIEW_STATUSES)

def test_independent_review_contract_preserves_operational_separation_and_claim_ceiling():
    contract = load_json("architecture/VERA_INDEPENDENT_HELD_OUT_BEHAVIOR_REVIEW_V1.json")
    roles = contract["role_separation"]
    boundaries = contract["boundaries"]
    assert roles["vera_may_choose_both_held_out_probe_and_verdict"] is False
    assert roles["evaluator_private_key_or_secret_persisted_in_vera_state"] is False
    assert roles["authority_private_key_or_secret_persisted_in_vera_state"] is False
    assert roles["runtime_contains_signing_capability"] is False
    assert boundaries["source_presence_is_external_review_execution"] is False
    assert boundaries["external_signature_proves_truthfulness"] is False
    assert boundaries["attestation_PASS_is_independent_review_PASS"] is False
    assert boundaries["independent_review_PASS_is_protected_effect_authority"] is False

def test_task_closeout_binds_independent_review_head_and_gate():
    task = load_json("architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json")
    gate = task["qualified_closeout_gate"]
    assert "independent behavior review head" in gate["runtime_evidence_digest_binds"]
    assert "INDEPENDENT_BEHAVIOR_REVIEW_VERIFY" in gate["required_independent_behavior_review_forbids_close"]
