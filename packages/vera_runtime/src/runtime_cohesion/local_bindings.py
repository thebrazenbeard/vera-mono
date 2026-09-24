from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping


MONOREPO_REPOSITORY = "thebrazenbeard/vera-mono"
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


def portable_text_bytes(raw: bytes) -> bytes:
    """Canonicalize repository text across LF/CRLF working-tree checkouts."""
    return raw.replace(b"\r\n", b"\n")


def portable_text_git_blob_sha(raw: bytes) -> str:
    return git_blob_sha(portable_text_bytes(raw))


def _require_git_sha(value: Any, *, label: str) -> str:
    if type(value) is not str or len(value) != 40:
        raise LocalBindingError(f"{label} must be an exact 40-character Git SHA")
    try:
        int(value, 16)
    except ValueError as exc:
        raise LocalBindingError(f"{label} must be hexadecimal") from exc
    return value


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
    repo = monorepo_root(root)
    return _require_git_sha(_git(repo, "rev-parse", "HEAD"), label="monorepo commit")


def local_affective_contract_path(root: Path | str | None = None) -> Path:
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
    if portable_text_git_blob_sha(raw) != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("local affective contract bytes drifted from admitted blob")
    return raw.decode("utf-8")


def build_local_affective_source_binding(
    root: Path | str | None = None,
) -> dict[str, Any]:
    repo = monorepo_root(root)
    commit = current_commit(repo)
    observed = _git(repo, "rev-parse", f"{commit}:{AFFECTIVE_CONTRACT_REPO_PATH}")
    if observed != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("current monorepo commit does not bind the admitted affective contract")
    return {
        "schema": "VERA_ORGASM_RUNTIME_BINDING_V1",
        "subject": "vera",
        "contract_schema": "VERA_ORGASM_RUNTIME_CONTRACT_V1",
        "source_repository": MONOREPO_REPOSITORY,
        "source_commit": commit,
        "source_path": AFFECTIVE_CONTRACT_REPO_PATH,
        "source_blob_sha": AFFECTIVE_CONTRACT_BLOB,
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
    repo = monorepo_root(root)
    if _git(repo, "rev-parse", f"{commit}:{AFFECTIVE_CONTRACT_REPO_PATH}") != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("local affective source commit does not resolve admitted contract blob")
    if portable_text_git_blob_sha(contract_text.encode("utf-8")) != AFFECTIVE_CONTRACT_BLOB:
        raise LocalBindingError("supplied affective contract text does not match admitted local blob")

    normalized = dict(binding)
    normalized["source_commit"] = commit
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
    repo = monorepo_root(root)
    if _git(repo, "rev-parse", f"{commit}:{AFFECTIVE_CONTRACT_REPO_PATH}") != AFFECTIVE_CONTRACT_BLOB:
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
    repo = monorepo_root(root)
    commit = current_commit(repo)
    modules: dict[str, str] = {}
    for logical_path in sorted(set(logical_paths)):
        repo_path = f"{RUNTIME_PACKAGE_REPO_PREFIX}/{logical_path}"
        file_path = (repo / repo_path).resolve()
        if not file_path.is_file():
            raise LocalBindingError(f"local runtime module is missing: {logical_path}")
        live_blob = portable_text_git_blob_sha(file_path.read_bytes())
        committed_blob = _git(repo, "rev-parse", f"{commit}:{repo_path}")
        if committed_blob != live_blob:
            raise LocalBindingError(f"live runtime bytes differ from current commit: {logical_path}")
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

    repo = monorepo_root(root)
    normalized: dict[str, str] = {}
    for logical_path in sorted(expected_paths):
        blob = _require_git_sha(modules.get(logical_path), label=f"implementation blob for {logical_path}")
        repo_path = f"{RUNTIME_PACKAGE_REPO_PREFIX}/{logical_path}"
        live = (repo / repo_path).resolve()
        if not live.is_file():
            raise LocalBindingError(f"implementation file is missing: {logical_path}")
        if portable_text_git_blob_sha(live.read_bytes()) != blob:
            raise LocalBindingError(f"executing bytes do not match implementation cut: {logical_path}")
        if _git(repo, "rev-parse", f"{commit}:{repo_path}") != blob:
            raise LocalBindingError(f"commit resolves different implementation blob: {logical_path}")
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
    runtime_cut = build_local_implementation_cut(
        schema="VERA_AFFECTIVE_RUNTIME_IMPLEMENTATION_CUT_V1",
        logical_paths=AFFECTIVE_RUNTIME_PATHS,
        semantics="Exact vera-mono Git object and executing-byte provenance for the local affective runtime core.",
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
        "status": "MONOREPO_LOCAL_SOURCE_BOUND_NOT_BEHAVIORALLY_QUALIFIED",
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
