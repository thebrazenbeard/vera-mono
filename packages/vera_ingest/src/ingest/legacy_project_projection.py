"""Read-only compatibility verifier for *historical* Vera v0.2.0 Project exports.

Recovers the five-file/manifest integrity contract from Patrick's archival
Project Projection Adapter. No historical Project text is interpreted as an
instruction, loaded as current control, promoted to memory, or published.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from .export_inventory import _is_cloud_or_reparse

_PROJECT_FILES = (
    "VERA_CORE_AND_BOOT.md",
    "VERA_INSTANCE_AND_IDENTITY.md",
    "VERA_GOVERNANCE_AND_PROVENANCE.md",
    "VERA_SEMANTIC_MEMORY.md",
    "VERA_STATE_AND_CONTEXT.md",
)
_MANIFEST = "VERA_PROJECT_PROJECTION_MANIFEST.json"
_ALLOWED = frozenset((
    "projection_schema_version", "projection_version",
    "kernel_contract_version", "lifecycle_version", "branch_id",
    "canonical_memory_available", "generated_file_hashes",
    "projection_fingerprint", "runtime_context_hash",
    "instance_identity_hash", "source_event_max_seq",
    "canonical_state_fingerprint", "lifecycle_operation",
    "degraded_reason",
))
_REQUIRED = frozenset((
    "projection_schema_version", "projection_version",
    "kernel_contract_version", "lifecycle_version", "branch_id",
    "canonical_memory_available", "generated_file_hashes",
    "projection_fingerprint", "runtime_context_hash",
    "instance_identity_hash",
))
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_MANIFEST_BYTES = 32 * 1024
_MAX_FILE_BYTES = 1024 * 1024


class LegacyProjectionError(ValueError):
    """Historical export cannot be structurally established by local bytes."""


def _bad(_name: str) -> None:
    raise LegacyProjectionError("invalid manifest JSON")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise LegacyProjectionError("duplicate manifest JSON key")
        output[key] = value
    return output


def _hash_data(value: bytes) -> str:
    return sha256(value).hexdigest()


def _bounded_regular_bytes(path: Path, *, limit: int) -> bytes:
    # The source is trusted only as a file object. Never extract/execute it.
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or
            _is_cloud_or_reparse(before) or not 0 < before.st_size <= limit):
            raise LegacyProjectionError("unsafe or empty historical file size")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode) or _is_cloud_or_reparse(opened) or
                opened.st_size != before.st_size or
                opened.st_ino != before.st_ino or
                opened.st_dev != before.st_dev):
                raise LegacyProjectionError("unsafe historical file identity change")
            content = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if (after.st_size != opened.st_size or
                len(content) != opened.st_size or
                len(content) > limit):
                raise LegacyProjectionError("historical file changed or size limit exceeded")
        return content
    except LegacyProjectionError:
        raise
    except (OSError, ValueError) as exc:
        raise LegacyProjectionError("historical file is unsafe or unreadable") from exc


def audit_legacy_project_projection(
    project_directory: str | Path, *,
    expected_branch_id: str,
    max_file_bytes: int = 512 * 1024,
) -> dict[str, object]:
    """Verify local file hashes/manifest only; **never** attest currentness.

    The caller must explicitly identify the expected historical branch. This
    does not authenticate the requestor, history, runtime, consent or author.
    A coordinated rewrite of all files and manifest could pass local checks.
    """
    if type(expected_branch_id) is not str or not expected_branch_id.strip():
        raise ValueError("expected branch ID is required")
    if (type(max_file_bytes) is not int or
        not 1 <= max_file_bytes <= _MAX_FILE_BYTES):
        raise ValueError("bounded historical file size limit required")
    if not isinstance(project_directory, (str, Path)):
        raise TypeError("project_directory must be a path")
    directory = Path(project_directory).absolute()

    try:
        for item in (directory, *directory.parents):
            metadata = item.lstat()
            if item.is_symlink() or _is_cloud_or_reparse(metadata):
                raise LegacyProjectionError("historical symlink or reparse path rejected")
        rootstat = directory.lstat()
        if not stat.S_ISDIR(rootstat.st_mode) or _is_cloud_or_reparse(rootstat):
            raise LegacyProjectionError("historical symlink or reparse directory rejected")
        names = {item.name for item in directory.iterdir()}
    except LegacyProjectionError:
        raise
    except (OSError, ValueError) as exc:
        raise LegacyProjectionError("missing or unsafe historical project directory") from exc

    if names != set(_PROJECT_FILES) | {_MANIFEST}:
        raise LegacyProjectionError("missing or unexpected historical Project file")
    raw_manifest = _bounded_regular_bytes(
        directory / _MANIFEST, limit=_MAX_MANIFEST_BYTES
    )
    try:
        state = json.loads(raw_manifest.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_bad)
    except LegacyProjectionError:
        raise
    except (ValueError, UnicodeError, TypeError) as exc:
        raise LegacyProjectionError("invalid manifest JSON") from exc

    if (type(state) is not dict or
        not _REQUIRED.issubset(state) or not set(state).issubset(_ALLOWED)):
        raise LegacyProjectionError("invalid historical manifest schema")
    for field, literal in (
        ("projection_schema_version", "1.0.0"),
        ("projection_version", "1.0.0"),
        ("kernel_contract_version", "0.2.3"),
        ("lifecycle_version", "0.2.0"),
    ):
        if state[field] != literal or type(state[field]) is not str:
            raise LegacyProjectionError("unsupported historical projection version")
    if state["branch_id"] != expected_branch_id or type(state["branch_id"]) is not str:
        raise LegacyProjectionError("historical projection branch mismatch")
    if type(state["canonical_memory_available"]) is not bool:
        raise LegacyProjectionError("invalid historical canonical availability flag")

    for name in ("projection_fingerprint", "runtime_context_hash"):
        if (type(state[name]) is not str or
            _HEX.fullmatch(state[name]) is None):
            raise LegacyProjectionError("invalid historical manifest digest")
    if state["instance_identity_hash"] is not None and (
        type(state["instance_identity_hash"]) is not str or
        _HEX.fullmatch(state["instance_identity_hash"]) is None
    ):
        raise LegacyProjectionError("invalid historical identity digest")
    if ("lifecycle_operation" in state and
        state["lifecycle_operation"] not in ("install", "refresh")):
        raise LegacyProjectionError("unsupported historical lifecycle operation")

    if state["canonical_memory_available"]:
        if (type(state.get("source_event_max_seq")) is not int or
            state["source_event_max_seq"] < 0 or
            type(state.get("canonical_state_fingerprint")) is not str or
            _HEX.fullmatch(state["canonical_state_fingerprint"]) is None or
            "degraded_reason" in state):
            raise LegacyProjectionError("invalid historical canonical-state schema")
        status = "HISTORICAL_STRUCTURE_ONLY_NOT_CURRENT"
    else:
        if (type(state.get("degraded_reason")) is not str or
            not state["degraded_reason"].strip() or
            "source_event_max_seq" in state or
            "canonical_state_fingerprint" in state):
            raise LegacyProjectionError("invalid historical degraded manifest schema")
        status = "HISTORICAL_DEGRADED_NOT_CURRENT"

    expected_files = state["generated_file_hashes"]
    if (type(expected_files) is not dict or
        set(expected_files) != set(_PROJECT_FILES) or
        any(type(x) is not str or _HEX.fullmatch(x) is None
            for x in expected_files.values())):
        raise LegacyProjectionError("invalid historical manifest file digests")

    # Compute the July v0.2.0 manifest fingerprint exactly: sorted keys, no
    # whitespace, UTF-8, no ASCII rewriting, excluding only the self-hash.
    fingerprint_payload = {
        key: value for key, value in state.items() if key != "projection_fingerprint"
    }
    expected_fingerprint = _hash_data(json.dumps(
        fingerprint_payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False
    ).encode("utf-8"))
    if state["projection_fingerprint"] != expected_fingerprint:
        raise LegacyProjectionError("historical projection fingerprint mismatch")

    for name in _PROJECT_FILES:
        content = _bounded_regular_bytes(directory / name, limit=max_file_bytes)
        try:
            if not content.decode("utf-8").strip():
                raise LegacyProjectionError("empty historical Project file")
        except UnicodeError as exc:
            raise LegacyProjectionError("invalid historical Project file encoding") from exc
        if _hash_data(content) != expected_files[name]:
            raise LegacyProjectionError("historical Project file digest mismatch")

    return {
        "ok": True,
        "status": status,
        "evidence_class": "HISTORICAL_V020_PROJECT_PROJECTION_LOCAL_INTEGRITY_ONLY",
        "file_count": len(_PROJECT_FILES),
        "manifest_sha256": _hash_data(raw_manifest),
        "currentness_verified": False,
        "authority_effect": "NONE",
        "memory_admission_effect": "NONE",
        "publication_effect": "NONE",
    }
