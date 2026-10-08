import json
from pathlib import Path

import pytest

import runtime_cohesion.local_bindings as local_bindings
from runtime_cohesion.local_bindings import (
    AFFECTIVE_CONTRACT_BLOB,
    AFFECTIVE_CONTRACT_REPO_PATH,
    MONOREPO_REPOSITORY,
    PACKAGED_PROVENANCE_ENV,
    PACKAGED_PROVENANCE_SCHEMA,
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
    assert binding["source_verification_mode"] == "LOCAL_GIT_OBJECTS"
    assert binding["runtime_repository"] == MONOREPO_REPOSITORY
    validate_local_affective_source_binding(binding, text)


def test_external_origin_is_provenance_not_runtime_authority():
    binding = build_local_affective_binding()
    assert binding["origin_provenance"]["repository"] == "thebrazenbeard/sexuality"
    assert binding["source_repository"] != binding["origin_provenance"]["repository"]


def _packaged_manifest(source_commit: str) -> dict[str, object]:
    files: dict[str, str] = {}
    for repo_path in sorted(local_bindings.packaged_provenance_required_paths()):
        files[repo_path] = local_bindings.git_blob_sha(
            local_bindings._installed_runtime_path(repo_path).read_bytes()
        )
    return {
        "schema": PACKAGED_PROVENANCE_SCHEMA,
        "repository": MONOREPO_REPOSITORY,
        "source_commit": source_commit,
        "source_commit_verification": "LOCAL_GIT_OBJECTS_AT_GENERATION",
        "protected_effect_authority": False,
        "files": files,
    }


def test_packaged_provenance_supports_installed_runtime_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_commit = "a" * 40
    manifest = tmp_path / "packaged-provenance.json"
    manifest.write_text(
        json.dumps(_packaged_manifest(source_commit), sort_keys=True),
        encoding="utf-8",
    )
    monkeypatch.setenv(PACKAGED_PROVENANCE_ENV, str(manifest))

    def deny_git(*_args, **_kwargs):
        raise AssertionError("packaged provenance path must not call git")

    monkeypatch.setattr(local_bindings.subprocess, "run", deny_git)

    text = load_local_affective_contract()
    binding = build_local_affective_binding()
    assert binding["source_commit"] == source_commit
    assert binding["source_verification_mode"] == (
        "PACKAGED_MANIFEST_EXECUTING_BYTES"
    )
    assert binding["status"] == (
        "PACKAGED_SOURCE_BOUND_EXECUTING_BYTES_VERIFIED_"
        "NOT_BEHAVIORALLY_QUALIFIED"
    )
    validate_local_affective_source_binding(binding, text)


def test_packaged_provenance_rejects_tampered_executing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest_payload = _packaged_manifest("b" * 40)
    manifest_payload["files"][AFFECTIVE_CONTRACT_REPO_PATH] = "0" * 40
    manifest = tmp_path / "packaged-provenance.json"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    monkeypatch.setenv(PACKAGED_PROVENANCE_ENV, str(manifest))

    with pytest.raises(
        local_bindings.LocalBindingError,
        match="packaged runtime bytes differ from bound blob",
    ):
        build_local_affective_binding()
