from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping


MONOREPO_REPOSITORY = "thebrazenbeard/vera-mono"
PACKAGED_PROVENANCE_ENV = "VERA_MONO_PACKAGED_PROVENANCE"
PACKAGED_PROVENANCE_SCHEMA = "VERA_MONO_PACKAGED_PROVENANCE_V1"
RUNTIME_PACKAGE_REPO_PREFIX = "packages/vera_runtime/src"
AFFECTIVE_CONTRACT_LOGICAL_PATH = "runtime_cohesion/resources/ORGASM_RUNTIME_CONTRACT_V1.json"
AFFECTIVE_CONTRACT_REPO_PATH = f"{RUNTIME_PACKAGE_REPO_PREFIX}/{AFFECTIVE_CONTRACT_LOGICAL_PATH}"
AFFECTIVE_CONTRACT_BLOB = "a48eed5392fdadc073dccd1e799926042077f567"
AFFECTIVE_CONTRACT_ORIGIN = {
    "repository": "thebrazenbeard/sexuality",
    "commit": "150f1c8231423393bb66b0e2cb759ce7c018f8d7",
    "path": "vera/orgasm/ORGASM_RUNTIME_CONTRACT_V1.json",
    "blob": AFFECTIVE_CONTRACT_BLOB,
}

AFFECTIVE_RUNTIME_PATHS = frozenset({
    "runtime_cohesion/__init__.py",
    "runtime_cohesion/adapters.py",
    "runtime_cohesion/evidence.py",
    "runtime_cohesion/orgasm.py",
    "runtime_cohesion/affect_authority.py",
    "runtime_cohesion/affect_bound_runtime.py",
    "runtime_cohesion/affect_receipt.py",
    "runtime_cohesion/affect_host.py",
    "runtime_cohesion/affect_cycle.py",
    "runtime_cohesion/affect_persistence.py",
    "runtime_cohesion/affect_provider_runtime.py",
    "runtime_cohesion/affect_scope.py",
    "runtime_cohesion/local_bindings.py",
})

COHESION_INTEGRATION_PATHS = frozenset({
    "runtime_cohesion/__init__.py",
    "runtime_cohesion/adapters.py",
    "runtime_cohesion/affect_integration.py",
    "runtime_cohesion/affect_integration_bound.py",
    "runtime_cohesion/affect_signal.py",
    "runtime_cohesion/audit.py",
    "runtime_cohesion/executor.py",
    "runtime_cohesion/item_typing.py",
    "runtime_cohesion/origin.py",
    "runtime_cohesion/provider_admission.py",
    "runtime_cohesion/reconcile.py",
    "runtime_cohesion/runtime.py",
    "runtime_cohesion/local_bindings.py",
})


class LocalBindingError(ValueError):
    pass


def git_blob_sha(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def _require_git_sha(value: Any, *, label: str) -> str:
    if type(value) is not str or len(value) != 40:
        raise LocalBindingError(f"{label} must be an exact 40-character Git SHA")
    try:
        int(value, 16)
    except ValueError as exc:
        raise LocalBindingError(f"{label} must be hexadecimal") from exc
    return value


def packaged_provenance_required_paths() -> frozenset[str]:
    runtime_paths = {
        f"{RUNTIME_PACKAGE_REPO_PREFIX}/{logical_path}"
        for logical_path in (AFFECTIVE_RUNTIME_PATHS | COHESION_INTEGRATION_PATHS)
    }
    runtime_paths.add(AFFECTIVE_CONTRACT_REPO_PATH)
    return frozenset(runtime_paths)


def _packaged_provenance(root: Path | str | None = None) -> dict[str, Any] | None:
    if root is not None:
        return None
    raw_path = os.environ.get(PACKAGED_PROVENANCE_ENV)
    if raw_path is None:
        return None
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise LocalBindingError("packaged provenance manifest is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalBindingError("packaged provenance manifest is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise LocalBindingError("packaged provenance manifest must be a mapping")
    if payload.get("schema") != PACKAGED_PROVENANCE_SCHEMA:
        raise LocalBindingError("packaged provenance schema mismatch")
    if payload.get("repository") != MONOREPO_REPOSITORY:
        raise LocalBindingError("packaged provenance repository mismatch")
    source_commit = _require_git_sha(
        payload.get("source_commit"),
        label="packaged provenance source commit",
    )
    if (
        payload.get("source_commit_verification")
        != "LOCAL_GIT_OBJECTS_AT_GENERATION"
    ):
        raise LocalBindingError(
            "packaged provenance source verification mode mismatch"
        )
    if payload.get("protected_effect_authority") is not False:
        raise LocalBindingError(
            "packaged provenance cannot grant protected-effect authority"
        )
    files = payload.get("files")
    if not isinstance(files, Mapping):
        raise LocalBindingError("packaged provenance files must be a mapping")
    expected_paths = packaged_provenance_required_paths()
    if set(files) != expected_paths:
        raise LocalBindingError("packaged provenance file set mismatch")
    normalized_files: dict[str, str] = {}
    for repo_path in sorted(expected_paths):
        normalized_files[repo_path] = _require_git_sha(
            files.get(repo_path),
            label=f"packaged provenance blob for {repo_path}",
        )
    return {
        "schema": PACKAGED_PROVENANCE_SCHEMA,
        "repository": MONOREPO_REPOSITORY,
        "source_commit": source_commit,
        "source_commit_verification": "LOCAL_GIT_OBJECTS_AT_GENERATION",
        "protected_effect_authority": False,
        "files": normalized_files,
    }


def _source_verification_mode(root: Path | str | None = None) -> str:
    return (
        "PACKAGED_MANIFEST_EXECUTING_BYTES"
        if _packaged_provenance(root) is not None
        else "LOCAL_GIT_OBJECTS"
    )


def _installed_runtime_path(repo_path: str) -> Path:
    prefix = RUNTIME_PACKAGE_REPO_PREFIX + "/"
    if not repo_path.startswith(prefix):
        raise LocalBindingError("packaged provenance path is outside vera_runtime")
    logical = repo_path[len(prefix) :]
    root = Path(__file__).resolve().parent.parent
    path = (root / logical).resolve()
    if path != root and root not in path.parents:
        raise LocalBindingError("packaged runtime path escapes installed source root")
    if not path.is_file():
        raise LocalBindingError(f"packaged runtime file is missing: {repo_path}")
    return path


def _repo_file_path(
    repo_path: str,
    root: Path | str | None = None,
) -> Path:
    packaged = _packaged_provenance(root)
    if packaged is not None:
        return _installed_runtime_path(repo_path)
    repo = monorepo_root(root)
    path = (repo / repo_path).resolve()
    if path != repo and repo not in path.parents:
        raise LocalBindingError("repository path escapes vera-mono root")
    if not path.is_file():
        raise LocalBindingError(f"local runtime file is missing: {repo_path}")
    return path


def _committed_blob(
    repo_path: str,
    root: Path | str | None = None,
) -> str:
    packaged = _packaged_provenance(root)
    if packaged is not None:
        expected = str(packaged["files"][repo_path])
        live = git_blob_sha(_repo_file_path(repo_path, root).read_bytes())
        if live != expected:
            raise LocalBindingError(
                f"packaged runtime bytes differ from bound blob: {repo_path}"
            )
        return expected
    repo = monorepo_root(root)
    commit = current_commit(repo)
    return _require_git_sha(
        _git(repo, "rev-parse", f"{commit}:{repo_path}"),
        label=f"committed blob for {repo_path}",
    )


def monorepo_root(start: Path | str | None = None) -> Path:
    current = Path(start) if start is not None else Path(__file__)
    current = current.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "MONOREPO_CONTRACT.md").is_file():
            return candidate
    raise LocalBindingError("cannot locate vera-mono repository root")


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LocalBindingError(f"git command failed: {' '.join(args)}") from exc


def current_commit(root: Path | str | None = None) -> str:
    packaged = _packaged_provenance(root)
    if packaged is not None:
        return str(packaged["source_commit"])
    repo = monorepo_root(root)
    return _require_git_sha(_git(repo, "rev-parse", "HEAD"), label="monorepo commit")


def local_affective_contract_path(root: Path | str | None = None) -> Path:
    packaged = _packaged_provenance(root)
    if packaged is not None:
        return _repo_file_path(AFFECTIVE_CONTRACT_REPO_PATH, root)
    repo = monorepo_root(root)
    path = (repo / AFFECTIVE_CONTRACT_REPO_PATH).resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise LocalBindingError("affective contract path escapes monorepo") from exc
    return path


def load_local_affective_contract(root: Path | str | None = None) -> str:
    path = local_affective_contract_path(root)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise LocalBindingError("local affective contract is unavailable") from exc
    if git_blob_sha(raw) != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("local affective contract bytes drifted from admitted blob")
    return raw.decode("utf-8")


def build_local_affective_source_binding(
    root: Path | str | None = None,
) -> dict[str, Any]:
    commit = current_commit(root)
    observed = _committed_blob(AFFECTIVE_CONTRACT_REPO_PATH, root)
    if observed != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("current source cut does not bind the admitted affective contract")
    return {
        "schema": "VERA_ORGASM_RUNTIME_BINDING_V1",
        "subject": "vera",
        "contract_schema": "VERA_ORGASM_RUNTIME_CONTRACT_V1",
        "source_repository": MONOREPO_REPOSITORY,
        "source_commit": commit,
        "source_path": AFFECTIVE_CONTRACT_REPO_PATH,
        "source_blob_sha": AFFECTIVE_CONTRACT_BLOB,
        "source_verification_mode": _source_verification_mode(root),
        "availability_implies_activation": False,
    }


def validate_local_affective_source_binding(
    binding: Mapping[str, Any],
    contract_text: str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if not isinstance(binding, Mapping):
        raise LocalBindingError("affective source binding must be a mapping")
    expected = {
        "schema": "VERA_ORGASM_RUNTIME_BINDING_V1",
        "subject": "vera",
        "contract_schema": "VERA_ORGASM_RUNTIME_CONTRACT_V1",
        "source_repository": MONOREPO_REPOSITORY,
        "source_path": AFFECTIVE_CONTRACT_REPO_PATH,
        "source_blob_sha": AFFECTIVE_CONTRACT_BLOB,
        "availability_implies_activation": False,
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            raise LocalBindingError(f"local affective source mismatch: {key}")

    commit = _require_git_sha(binding.get("source_commit"), label="local affective source commit")
    mode = _source_verification_mode(root)
    observed_mode = binding.get("source_verification_mode")
    if observed_mode is None and mode == "LOCAL_GIT_OBJECTS":
        observed_mode = mode
    if observed_mode != mode:
        raise LocalBindingError("local affective source verification mode mismatch")
    if current_commit(root) != commit:
        raise LocalBindingError("local affective source commit does not match current source cut")
    if _committed_blob(AFFECTIVE_CONTRACT_REPO_PATH, root) != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("local affective source commit does not resolve admitted contract blob")
    if git_blob_sha(contract_text.encode("utf-8")) != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("supplied affective contract text does not match admitted local blob")

    normalized = dict(binding)
    normalized["source_commit"] = commit
    normalized["source_verification_mode"] = mode
    return normalized


def validate_local_affective_provenance(
    source: Mapping[str, Any],
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Validate signal/checkpoint source metadata against the local contract copy."""
    if not isinstance(source, Mapping):
        raise LocalBindingError("affective source provenance must be a mapping")
    expected = {
        "source_repository": MONOREPO_REPOSITORY,
        "source_path": AFFECTIVE_CONTRACT_REPO_PATH,
        "source_blob_sha": AFFECTIVE_CONTRACT_BLOB,
    }
    for key, value in expected.items():
        if source.get(key) != value:
            raise LocalBindingError(f"local affective provenance mismatch: {key}")
    commit = _require_git_sha(source.get("source_commit"), label="local affective provenance commit")
    if current_commit(root) != commit:
        raise LocalBindingError("local affective provenance commit does not match current source cut")
    if _committed_blob(AFFECTIVE_CONTRACT_REPO_PATH, root) != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("local affective provenance commit does not bind admitted contract")
    normalized = dict(source)
    normalized["source_commit"] = commit
    return normalized


def build_local_implementation_cut(
    *,
    schema: str,
    logical_paths: Iterable[str],
    semantics: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    commit = current_commit(root)
    modules: dict[str, str] = {}
    for logical_path in sorted(set(logical_paths)):
        repo_path = f"{RUNTIME_PACKAGE_REPO_PREFIX}/{logical_path}"
        file_path = _repo_file_path(repo_path, root)
        live_blob = git_blob_sha(file_path.read_bytes())
        committed_blob = _committed_blob(repo_path, root)
        if committed_blob != live_blob:
            raise LocalBindingError(f"live runtime bytes differ from current source cut: {logical_path}")
        modules[logical_path] = live_blob
    cut: dict[str, Any] = {
        "schema": schema,
        "repository": MONOREPO_REPOSITORY,
        "commit": commit,
        "modules": modules,
    }
    if semantics is not None:
        cut["semantics"] = semantics
    return cut


def validate_local_implementation_cut(
    cut: Mapping[str, Any],
    *,
    schema: str,
    logical_paths: Iterable[str],
    require_semantics: bool,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if not isinstance(cut, Mapping):
        raise LocalBindingError("implementation cut must be a structured mapping")
    required_fields = {"schema", "repository", "commit", "modules"}
    if require_semantics:
        required_fields.add("semantics")
    if set(cut) != required_fields:
        raise LocalBindingError("implementation cut field set mismatch")
    if cut.get("schema") != schema:
        raise LocalBindingError("implementation cut schema mismatch")
    if cut.get("repository") != MONOREPO_REPOSITORY:
        raise LocalBindingError("implementation cut must bind vera-mono")
    if require_semantics and (type(cut.get("semantics")) is not str or not str(cut.get("semantics")).strip()):
        raise LocalBindingError("implementation cut semantics must be a non-empty string")

    commit = _require_git_sha(cut.get("commit"), label="implementation cut commit")
    expected_paths = set(logical_paths)
    modules = cut.get("modules")
    if not isinstance(modules, Mapping) or set(modules) != expected_paths:
        raise LocalBindingError("implementation cut module set mismatch")

    if current_commit(root) != commit:
        raise LocalBindingError("implementation cut commit does not match current source cut")
    normalized: dict[str, str] = {}
    for logical_path in sorted(expected_paths):
        blob = _require_git_sha(modules.get(logical_path), label=f"implementation blob for {logical_path}")
        repo_path = f"{RUNTIME_PACKAGE_REPO_PREFIX}/{logical_path}"
        live = _repo_file_path(repo_path, root)
        if git_blob_sha(live.read_bytes()) != blob:
            raise LocalBindingError(f"executing bytes do not match implementation cut: {logical_path}")
        if _committed_blob(repo_path, root) != blob:
            raise LocalBindingError(f"source cut resolves different implementation blob: {logical_path}")
        normalized[logical_path] = blob

    result: dict[str, Any] = {
        "schema": schema,
        "repository": MONOREPO_REPOSITORY,
        "commit": commit,
        "modules": normalized,
    }
    if require_semantics:
        result["semantics"] = str(cut["semantics"])
    return result


def build_local_affective_binding(root: Path | str | None = None) -> dict[str, Any]:
    source = build_local_affective_source_binding(root)
    mode = _source_verification_mode(root)
    semantics = (
        "Exact vera-mono Git object and executing-byte provenance for the local affective runtime core."
        if mode == "LOCAL_GIT_OBJECTS"
        else "Host-packaged source-head provenance plus exact executing-byte verification for the installed affective runtime core; Git-object resolution occurred at manifest generation, not locally."
    )
    runtime_cut = build_local_implementation_cut(
        schema="VERA_AFFECTIVE_RUNTIME_IMPLEMENTATION_CUT_V1",
        logical_paths=AFFECTIVE_RUNTIME_PATHS,
        semantics=semantics,
        root=root,
    )
    integration_cut = build_local_implementation_cut(
        schema="VERA_COHESION_AFFECTIVE_INTEGRATION_CUT_V1",
        logical_paths=COHESION_INTEGRATION_PATHS,
        root=root,
    )
    generation = runtime_cut["commit"]
    if integration_cut["commit"] != generation:
        raise LocalBindingError("runtime and integration cuts are not one monorepo generation")
    return {
        **source,
        "status": (
            "MONOREPO_LOCAL_SOURCE_BOUND_NOT_BEHAVIORALLY_QUALIFIED"
            if mode == "LOCAL_GIT_OBJECTS"
            else "PACKAGED_SOURCE_BOUND_EXECUTING_BYTES_VERIFIED_NOT_BEHAVIORALLY_QUALIFIED"
        ),
        "runtime_repository": MONOREPO_REPOSITORY,
        "runtime_module": f"{RUNTIME_PACKAGE_REPO_PREFIX}/runtime_cohesion/orgasm.py",
        "runtime_implementation_cut": runtime_cut,
        "cohesion_integration_cut": integration_cut,
        "cross_binding": {
            "generation_commit": generation,
            "affective_core_and_cohesion_integration_same_generation": True,
            "supported_execution_requires_both_exact_cuts": True,
            "generic_planning_mutation_owner": "COHESION_INTEGRATION_ARBITRATION_PORT",
            "orgasm_subsystem_generic_planning_mutation_authority": False,
        },
        "origin_provenance": dict(AFFECTIVE_CONTRACT_ORIGIN),
    }
