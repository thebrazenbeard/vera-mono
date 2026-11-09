"""Read-only ancestry metadata gate for Mini-Vera.

This gate compares *claims*, never establishes weight compatibility or grants
execution authority. The training manifest is self-asserted unless independently
pinned by the operator, and an operator's pin alone is still not a trust root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_REPO = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:[\\/][^\x00\r\n]+\Z")
_MAX_JSON_BYTES = 128 * 1024
_MAX_ADAPTER_BYTES = 1024 * 1024 * 1024


def _digest(path: Path, *, limit: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"missing or oversized input: {path.name}")
    hash_state = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError(f"oversized input: {path.name}")
            hash_state.update(chunk)
    return hash_state.hexdigest()


def _json_with_sha(path: Path) -> tuple[Mapping[str, Any], str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"missing or oversized JSON: {path.name}")

    # A single bounded byte snapshot underlies both the claims and their digest.
    # This is not atomic filesystem custody: pre-open symlink/stat races remain.
    with path.open("rb") as stream:
        raw = stream.read(_MAX_JSON_BYTES + 1)
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError(f"oversized JSON: {path.name}")
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        content = json.loads(raw.decode("utf-8-sig"),
                             object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON: {path.name}") from error
    if not isinstance(content, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return content, hashlib.sha256(raw).hexdigest()


def _json(path: Path) -> Mapping[str, Any]:
    return _json_with_sha(path)[0]


def _field(data: Mapping[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _path_claim(left: Any, right: Any) -> str:
    if not isinstance(left, str) or not isinstance(right, str):
        return "UNKNOWN"
    if not _WINDOWS_PATH.fullmatch(left) or not _WINDOWS_PATH.fullmatch(right):
        return "UNKNOWN"
    for value in (left, right):
        if any(segment in (".", "..") for segment in value.replace("/", "\\").split("\\")):
            return "UNKNOWN"
    # Only case/slash normalization for explicit Windows paths. No aliases,
    # basenames, symlinks, relocation assumptions, or repository-name guesses.
    normalize = lambda value: value.replace("/", "\\").casefold()
    return "MATCH" if normalize(left) == normalize(right) else "MISMATCH"


def _claim(left: Any, right: Any, *, kind: str) -> str:
    if not isinstance(left, str) or not isinstance(right, str):
        return "UNKNOWN"
    if kind == "repo" and (not _REPO.fullmatch(left) or not _REPO.fullmatch(right)):
        return "UNKNOWN"
    if kind == "revision" and (not left.strip() or not right.strip()):
        return "UNKNOWN"
    # Case and spelling matter. A GGUF publisher may have repackaged the same
    # weights: different repo claims are not proof of incompatible tensors.
    return "MATCH" if left == right else "MISMATCH"


def assess(adapter_config: Mapping[str, Any], adapter_sha256: str,
           training_manifest: Mapping[str, Any],
           runtime_qualification: Mapping[str, Any], *,
           expected_manifest_sha256: str | None = None,
           actual_manifest_sha256: str | None = None) -> dict[str, Any]:
    """Compare immutable *metadata claims* only; never returns execution approval."""
    expected = expected_manifest_sha256
    actual = actual_manifest_sha256
    pinned = (isinstance(expected, str) and bool(_HASH.fullmatch(expected))
              and isinstance(actual, str) and bool(_HASH.fullmatch(actual))
              and expected.casefold() == actual.casefold())
    recorded = _field(training_manifest, "adapter", "adapter_model_sha256")
    adapter_bound = (isinstance(recorded, str) and isinstance(adapter_sha256, str)
                     and _HASH.fullmatch(recorded) and _HASH.fullmatch(adapter_sha256))
    adapter_binding = ("UNKNOWN" if not adapter_bound else
                       "MATCH" if recorded.casefold() == adapter_sha256.casefold()
                       else "MISMATCH")
    checks = {
        "manifest_pin": "MATCH" if pinned else
                        "MISMATCH" if expected and actual and
                        _HASH.fullmatch(expected) and _HASH.fullmatch(actual) else "UNKNOWN",
        "adapter_binding": adapter_binding,
        "base_path_claim": _path_claim(
            _field(adapter_config, "base_model_name_or_path"),
            _field(training_manifest, "base", "path")),
        "repository_claim": _claim(
            _field(training_manifest, "base", "repository"),
            _field(runtime_qualification, "base", "hf_repo"), kind="repo"),
        "revision_claim": _claim(
            _field(training_manifest, "base", "revision"),
            _field(runtime_qualification, "base", "revision"), kind="revision"),
    }
    # Do not evaluate ancestry against a nearby but unrelated adapter manifest;
    # a mismatch there is absence of evidence, not a proven base mismatch.
    bound = all(checks[key] == "MATCH" for key in
                ("manifest_pin", "adapter_binding", "base_path_claim"))
    if not bound:
        relation = "UNKNOWN"
    elif "MISMATCH" in (checks["repository_claim"], checks["revision_claim"]):
        relation = "MISMATCH"
    elif checks["repository_claim"] == checks["revision_claim"] == "MATCH":
        relation = "MATCH"
    else:
        relation = "UNKNOWN"
    return {
        "schema": "mini-vera-model-lineage-claims-v1",
        "metadata_relation": relation,
        "scope": "offline metadata claims only; not tensor compatibility or training provenance proof",
        "manifest_pin_authority": "CALLER_PROVIDED_DIGEST_NOT_SIGNED",
        "checks": checks,
        "runtime_qualified": False,
        "proves_weight_equivalence": False,
        "authority_effect": "NONE",
        "reason": ("bound metadata claims agree" if relation == "MATCH" else
                   "bound metadata claims disagree; weight compatibility unknown" if
                   relation == "MISMATCH" else
                   "training adapter binding, provenance pin, path or base claims unestablished"),
    }


def assess_paths(adapter_config_path: Path, adapter_file: Path,
                 training_manifest_path: Path, runtime_qualification_path: Path, *,
                 expected_manifest_sha256: str | None = None) -> dict[str, Any]:
    """Bounded local read-only sources. Never read a model, secrets, or memory DB."""
    if Path(adapter_file).name != "adapter_model.safetensors":
        raise ValueError("adapter file must be named adapter_model.safetensors")
    config = _json(Path(adapter_config_path))
    manifest, manifest_sha = _json_with_sha(Path(training_manifest_path))
    runtime = _json(Path(runtime_qualification_path))
    sha = _digest(Path(adapter_file), limit=_MAX_ADAPTER_BYTES)
    return assess(config, sha, manifest, runtime,
                  expected_manifest_sha256=expected_manifest_sha256,
                  actual_manifest_sha256=manifest_sha)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-config", required=True, type=Path)
    parser.add_argument("--adapter-file", required=True, type=Path)
    parser.add_argument("--training-manifest", required=True, type=Path)
    parser.add_argument("--runtime-qualification", required=True, type=Path)
    parser.add_argument("--expected-training-manifest-sha256")
    args = parser.parse_args(argv)
    try:
        report = assess_paths(args.adapter_config, args.adapter_file,
                              args.training_manifest, args.runtime_qualification,
                              expected_manifest_sha256=args.expected_training_manifest_sha256)
    except (OSError, ValueError) as error:
        print(json.dumps({"schema": "mini-vera-model-lineage-claims-v1",
                          "metadata_relation": "UNKNOWN", "runtime_qualified": False,
                          "authority_effect": "NONE", "error": str(error)}, sort_keys=True))
        return 3
    print(json.dumps(report, sort_keys=True))
    # Nonzero unconditionally: metadata matching is never model qualification.
    return 2


if __name__ == "__main__":
    sys.exit(main())
