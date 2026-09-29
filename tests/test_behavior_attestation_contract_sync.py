import json
from pathlib import Path

from vera_core import (
    BEHAVIOR_ATTESTATION_STATUSES,
    BEHAVIOR_ATTEST_VERIFY_PREFIX,
)


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_external_behavior_attestation_contract_matches_runtime():
    contract = load_json(
        "architecture/VERA_EXTERNAL_BEHAVIOR_ATTESTATION_V1.json"
    )
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")
    task = load_json(
        "architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json"
    )

    grammar = (
        f"{BEHAVIOR_ATTEST_VERIFY_PREFIX}|<consumer-id>|<probe-id>|"
        "<declaration-sha256>|<provider-id>|<provider-key-id>|"
        "<provider-key-sha256>|<effect-subject-sha256-or-NONE>"
    )
    assert contract["requirement_grammar"]["syntax"] == grammar
    assert manifest["behavior_attestation"]["requirement_grammar"] == grammar
    assert task["task_packet"][
        "evidence_requirement_behavior_attestation_grammar"
    ] == grammar
    assert set(contract["statuses"]) == set(
        BEHAVIOR_ATTESTATION_STATUSES
    )


def test_attestation_is_stronger_provenance_not_independent_review():
    contract = load_json(
        "architecture/VERA_EXTERNAL_BEHAVIOR_ATTESTATION_V1.json"
    )
    boundaries = contract["boundaries"]

    assert boundaries["behavior_effect_pass_is_attestation_pass"] is False
    assert boundaries["attestation_pass_is_independent_review"] is False
    assert boundaries[
        "attestation_pass_is_protected_effect_authority"
    ] is False
    assert boundaries["local_effect_fence_is_external_effect_proof"] is False


def test_closeout_binds_behavior_attestation_head_and_gate():
    task = load_json(
        "architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json"
    )
    gate = task["qualified_closeout_gate"]

    assert "behavior attestation verification head" in gate[
        "runtime_evidence_digest_binds"
    ]
    assert gate[
        "required_behavior_attestation_forbids_close"
    ] == (
        "matching BEHAVIOR_ATTEST_VERIFY requirements must be "
        "live-current PASS above the exact current behavior/effect receipt"
    )
