from runtime_cohesion.local_bindings import (
    AFFECTIVE_CONTRACT_BLOB,
    AFFECTIVE_CONTRACT_REPO_PATH,
    MONOREPO_REPOSITORY,
    build_local_affective_binding,
    load_local_affective_contract,
    validate_local_affective_source_binding,
)


def test_affective_contract_is_monorepo_local_and_exact():
    text = load_local_affective_contract()
    binding = build_local_affective_binding()
    assert binding["source_repository"] == MONOREPO_REPOSITORY
    assert binding["source_path"] == AFFECTIVE_CONTRACT_REPO_PATH
    assert binding["source_blob_sha"] == AFFECTIVE_CONTRACT_BLOB
    assert binding["runtime_repository"] == MONOREPO_REPOSITORY
    validate_local_affective_source_binding(binding, text)


def test_external_origin_is_provenance_not_runtime_authority():
    binding = build_local_affective_binding()
    assert binding["origin_provenance"]["repository"] == "thebrazenbeard/sexuality"
    assert binding["source_repository"] != binding["origin_provenance"]["repository"]
