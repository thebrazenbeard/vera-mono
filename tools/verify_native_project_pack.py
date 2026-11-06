"""Verify the source bytes of a Vera Mono ChatGPT Project pack.

This is a SOURCE integrity tool. It never reads or changes a ChatGPT Project,
looks for credentials, or grants installation, memory, runtime or effect authority.
The existing repository pack is intentionally a candidate, not a live owner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


SCHEMA = "VERA_MONO_CHATGPT_PROJECT_PACK_V1"
RECEIPT_SCHEMA = "VERA_NATIVE_PROJECT_PACK_SOURCE_AUDIT_V1"
EXPECTED_REPO = "thebrazenbeard/vera-mono"
REQUIRED_LOGICAL_ID = "VERA_NATIVE_PROJECT_INTERFACE"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_MEMBER_BYTES = 256 * 1024
MAX_MEMBERS = 64
_FILENAME = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ROOT_KEYS = frozenset({
    "schema", "status", "repository", "source_branch",
    "source_head_before_manifest", "creation_base_main", "project_name",
    "instructions_file", "members", "claim_ceiling",
    "protected_effects_not_authorized",
})
_MEMBER_KEYS = frozenset({"filename", "sha256", "size_bytes"})


class InvalidSourcePack(ValueError):
    pass


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSourcePack(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _read_bounded(path: Path, limit: int) -> bytes:
    if path.is_symlink():
        raise InvalidSourcePack("symbolic-link source is not acceptable")
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise InvalidSourcePack("source is not a regular file")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise InvalidSourcePack("source exceeds size limit")
    return data


def inspect_pack(
    source_root: Path,
    *,
    expected_repository: str = EXPECTED_REPO,
    observed_git_head: str | None = None,
    expected_manifest_blob: str | None = None,
) -> dict[str, Any]:
    """Check exact pack membership; never infer native Project installation."""
    if observed_git_head is not None and not _GIT_SHA.fullmatch(observed_git_head):
        raise InvalidSourcePack("Git head claim must be a 40-character SHA")
    if expected_manifest_blob is not None and not _GIT_SHA.fullmatch(expected_manifest_blob):
        raise InvalidSourcePack("manifest Git blob pin must be a 40-character SHA")
    root = source_root.resolve(strict=True)
    raw = _read_bounded(root / "PROJECT_PACK_MANIFEST.json", MAX_MANIFEST_BYTES)
    manifest_blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    if expected_manifest_blob is not None and manifest_blob != expected_manifest_blob:
        raise InvalidSourcePack("manifest differs from Git blob pin")
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidSourcePack("manifest is not unique-key UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != _ROOT_KEYS:
        raise InvalidSourcePack("manifest root keys mismatch")
    if manifest["schema"] != SCHEMA or manifest["repository"] != expected_repository:
        raise InvalidSourcePack("manifest schema/repository mismatch")
    if manifest["status"] != "CANDIDATE_NOT_INSTALLED":
        raise InvalidSourcePack("unsupported installation-state claim")
    if not isinstance(manifest["source_head_before_manifest"], str) or not _GIT_SHA.fullmatch(manifest["source_head_before_manifest"]):
        raise InvalidSourcePack("invalid pack source-head provenance")
    if not isinstance(manifest["creation_base_main"], str) or not _GIT_SHA.fullmatch(manifest["creation_base_main"]):
        raise InvalidSourcePack("invalid creation-base provenance")
    if manifest["claim_ceiling"] != "UPLOAD_READY_PROJECT_PACK; NOT INSTALLED; NOT RUNTIME_CONSUMED; NOT BEHAVIORALLY_QUALIFIED":
        raise InvalidSourcePack("claim ceiling cannot be promoted")
    if not isinstance(manifest["protected_effects_not_authorized"], list) or not manifest["protected_effects_not_authorized"]:
        raise InvalidSourcePack("protected-effect exclusions missing")
    if not isinstance(manifest["members"], list) or not 1 <= len(manifest["members"]) <= MAX_MEMBERS:
        raise InvalidSourcePack("invalid member count")
    if manifest["instructions_file"] not in [row.get("filename") for row in manifest["members"] if isinstance(row, dict)]:
        raise InvalidSourcePack("instructions file absent from source pack")

    seen: set[str] = set()
    mismatches: list[str] = []
    for index, item in enumerate(manifest["members"]):
        if not isinstance(item, dict) or set(item) != _MEMBER_KEYS:
            raise InvalidSourcePack(f"invalid member record {index}")
        name, digest, expected_length = item["filename"], item["sha256"], item["size_bytes"]
        if not isinstance(name, str) or not _FILENAME.fullmatch(name) or name in (".", ".."):
            raise InvalidSourcePack(f"unsafe member filename at {index}")
        if name.casefold() in seen:
            raise InvalidSourcePack(f"duplicate or case-equivalent member filename at {index}")
        seen.add(name.casefold())
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise InvalidSourcePack(f"invalid member digest at {index}")
        if type(expected_length) is not int or not 0 <= expected_length <= MAX_MEMBER_BYTES:
            raise InvalidSourcePack(f"invalid member length at {index}")
        child = root / name
        try:
            data = _read_bounded(child, MAX_MEMBER_BYTES)
        except (FileNotFoundError, InvalidSourcePack):
            mismatches.append(name)
            continue
        if len(data) != expected_length or hashlib.sha256(data).hexdigest() != digest:
            mismatches.append(name)

    # A repository pack is not the live ChatGPT Project source inventory.
    # The current manifest does not bind the required logical ID.
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "SOURCE_PACK_INTEGRITY_PASS_NATIVE_BINDING_HOLD" if not mismatches else "SOURCE_PACK_INTEGRITY_HOLD",
        "source_integrity": "PASS" if not mismatches else "FAIL",
        "member_count": len(seen),
        "mismatched_members": sorted(mismatches),
        "expected_repository": expected_repository,
        "claimed_source_head": observed_git_head,
        "head_claim_independently_verified": False,
        "manifest_git_blob_sha1": manifest_blob,
        "manifest_blob_matches_operator_pin": expected_manifest_blob is not None,
        "operator_pin_independently_verified": False,
        "required_logical_id": REQUIRED_LOGICAL_ID,
        "native_project_owner_binding": "UNRESOLVED",
        "project_source_inventory": "NOT_READ_BY_THIS_TOOL",
        "native_project_installation": "UNVERIFIED",
        "runtime_consumption": "UNVERIFIED",
        "behavioral_qualification": "UNVERIFIED",
        "memory_authority": False,
        "effect_authority": False,
        "evidence_class": "LOCAL_SOURCE_BYTES_ONLY",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--observed-git-head")
    parser.add_argument("--expected-manifest-blob")
    args = parser.parse_args(argv)
    try:
        receipt = inspect_pack(
            args.source_root,
            observed_git_head=args.observed_git_head,
            expected_manifest_blob=args.expected_manifest_blob,
        )
    except (InvalidSourcePack, OSError) as exc:
        print(json.dumps({"status": "INVALID_SOURCE_PACK", "error": str(exc)}))
        return 3
    print(json.dumps(receipt, sort_keys=True))
    return 2  # No native Project live-binding authority can be inferred.


if __name__ == "__main__":
    raise SystemExit(main())

