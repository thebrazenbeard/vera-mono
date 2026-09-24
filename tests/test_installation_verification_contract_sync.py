import json
from pathlib import Path

from vera_core.installation_verification import (
    INSTALLATION_VERIFICATION_STATUSES,
    INSTALLATION_VERIFY_PREFIX,
)


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_installation_verification_contract_matches_runtime_and_task_grammar():
    contract = load_json(
        "architecture/VERA_INSTALLATION_VERIFICATION_V1.json"
    )
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")
    task = load_json(
        "architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json"
    )

    grammar = (
        f"{INSTALLATION_VERIFY_PREFIX}|"
        "<target-id>|<distribution>|<version>"
    )
    assert contract["requirement_grammar"]["syntax"] == grammar
    assert manifest["installation_verification"][
        "requirement_grammar"
    ] == grammar
    assert task["task_packet"][
        "evidence_requirement_installation_verification_grammar"
    ] == grammar
    assert set(contract["observation"]["statuses"]) == set(
        INSTALLATION_VERIFICATION_STATUSES
    )


def test_installation_verification_contract_preserves_truth_surface_boundaries():
    contract = load_json(
        "architecture/VERA_INSTALLATION_VERIFICATION_V1.json"
    )
    boundaries = contract["boundaries"]
    assert boundaries["source_pass_is_not_install_pass"] is True
    assert boundaries["package_pass_is_not_install_pass"] is True
    assert boundaries["installation_pass_is_not_current_route"] is True
    assert (
        boundaries["installation_pass_is_not_runtime_consumption"]
        is True
    )
    assert (
        boundaries["installation_pass_is_not_behavioral_qualification"]
        is True
    )
    assert boundaries["installation_verification_is_read_only"] is True
    assert (
        boundaries[
            "installation_verification_grants_no_install_or_mutation_authority"
        ]
        is True
    )


def test_installation_verification_contract_requires_live_currentness():
    contract = load_json(
        "architecture/VERA_INSTALLATION_VERIFICATION_V1.json"
    )
    currentness = contract["live_currentness"]
    assert currentness[
        "stored_PASS_is_sufficient_without_refresh"
    ] is False
    assert currentness[
        "current_observation_must_match_stored_PASS_digest"
    ] is True
    assert currentness["missing_transport_after_stored_PASS"] == (
        "PENDING_NOT_CURRENT"
    )
