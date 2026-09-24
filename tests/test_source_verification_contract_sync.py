import json
from pathlib import Path

from vera_core.source_verification import (
    SOURCE_CHECK_STATUSES,
    SOURCE_VERIFICATION_PREFIX,
    SOURCE_VERIFICATION_STATUSES,
)


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_source_verification_contract_matches_executable_status_sets_and_grammar():
    contract = load_json(
        "architecture/VERA_SOURCE_VERIFICATION_V1.json"
    )
    source = load_json(
        "architecture/VERA_QUALIFIED_SOURCE_MUTATION_V1.json"
    )
    task = load_json(
        "architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json"
    )
    manifest = load_json(
        "architecture/VERA_MONO_MANIFEST_V1.json"
    )

    grammar = (
        f"{SOURCE_VERIFICATION_PREFIX}|"
        "<repository>|<ref>|<check-name>"
    )
    assert contract["requirement_grammar"]["syntax"] == grammar
    assert source["exact_commit_verification"][
        "requirement_grammar"
    ] == grammar
    assert task["task_packet"][
        "evidence_requirement_source_verification_grammar"
    ] == grammar
    assert manifest["source_verification"][
        "requirement_grammar"
    ] == grammar

    assert set(contract["observation"]["check_statuses"]) == set(
        SOURCE_CHECK_STATUSES
    )
    assert set(contract["observation"]["aggregate_statuses"]) == set(
        SOURCE_VERIFICATION_STATUSES
    )
    assert set(manifest["source_verification"]["statuses"]) == set(
        SOURCE_VERIFICATION_STATUSES
    )


def test_source_verification_contract_preserves_surface_separation():
    contract = load_json(
        "architecture/VERA_SOURCE_VERIFICATION_V1.json"
    )
    boundaries = contract["boundaries"]
    assert boundaries["source_verification_is_not_merge_authority"] is True
    assert boundaries["source_verification_is_not_deployment"] is True
    assert (
        boundaries[
            "source_verification_is_not_installation_or_registration"
        ]
        is True
    )
    assert (
        boundaries["source_verification_is_not_runtime_consumption"]
        is True
    )
    assert (
        boundaries[
            "source_verification_is_not_behavioral_qualification"
        ]
        is True
    )
    assert (
        boundaries[
            "passing_source_checks_do_not_promote_other_closeout_surfaces"
        ]
        is True
    )


def test_github_source_verification_contract_requires_exact_commit_and_pagination():
    contract = load_json(
        "architecture/VERA_SOURCE_VERIFICATION_V1.json"
    )
    github = contract["concrete_github_transport"]
    assert github["transport"] == (
        "vera_core.GitHubSourceVerificationTransport"
    )
    assert "exact commit" in github["commit_binding"]
    assert "until hasNextPage=false" in github["pagination"]
    assert set(github["accepted_context_types"]) == {
        "CheckRun",
        "StatusContext",
    }
    assert github["missing_required_context"] == "UNAVAILABLE"


def test_source_verification_contract_requires_live_ref_currentness_after_pass():
    contract = load_json(
        "architecture/VERA_SOURCE_VERIFICATION_V1.json"
    )
    currentness = contract["currentness"]
    assert currentness[
        "stored_PASS_is_sufficient_without_live_ref_refresh"
    ] is False
    assert currentness[
        "live_ref_must_still_equal_exact_verified_commit"
    ] is True
    assert currentness["later_ref_movement"] == "PROVENANCE_MISMATCH"
    assert currentness["missing_transport_after_stored_PASS"] == (
        "PENDING_NOT_CURRENT"
    )
