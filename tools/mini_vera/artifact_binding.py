"""Read-only local model byte binding for the Mini-Vera request composer.

This checks offline files, not the resident inference server: a passing result
does not establish that any server actually loaded these bytes.  No model is
started, downloaded, quantized, trained, or contacted.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any

from .compose import CompositionRejected, canonical, compose, read_object, sha256

MAX_MANIFEST_BYTES = 4096
MAX_MODEL_BYTES = 4 * 1024**3
MAX_TOTAL_PROFILE_BYTES = 3_000_000_000  # This Mini-Vera profile, not a general inference limit.
FORMATS = {
    "base": {"GGUF": ".gguf"},
    "adapter": {"GGUF": ".gguf", "SAFETENSORS": ".safetensors"},
}


def _hex64(s: object) -> bool:
    return type(s) is str and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _hash_local_file(root: Path, relative: str, expected_size: int, expected_sha: str,
                     *, role: str, artifact_format: str) -> None:
    parts = Path(relative).parts
    if (not parts or Path(relative).is_absolute() or any(x in (".", "..") for x in parts)
            or len(relative) > 240 or "\\" in relative or ":" in relative):
        raise CompositionRejected("invalid relative model artifact path")
    if not relative.endswith(FORMATS[role][artifact_format]):
        raise CompositionRejected("wrong artifact extension for role")
    candidate = root
    for component in parts:
        candidate = candidate / component
        if candidate.is_symlink():
            raise CompositionRejected("symlink path component rejected")
    if not candidate.is_file():
        raise CompositionRejected("pinned local model artifact missing")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as exc:
        raise CompositionRejected("cannot open pinned local model artifact") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
            raise CompositionRejected("artifact size/type mismatch")
        digest = hashlib.sha256()
        header = os.read(fd, min(8, expected_size))
        if artifact_format == "GGUF" and header[:4] != b"GGUF":
            raise CompositionRejected("GGUF header missing")
        # A safetensors adapter requires a valid-looking nonzero JSON header
        # length; this is not a full safetensors structural validation.
        if artifact_format == "SAFETENSORS" and (len(header) < 8 or int.from_bytes(header[:8], "little") < 2):
            raise CompositionRejected("adapter header invalid")
        digest.update(header)
        remaining = expected_size - len(header)
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                raise CompositionRejected("artifact truncated during read")
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise CompositionRejected("artifact changed during byte read")
        if digest.hexdigest() != expected_sha:
            raise CompositionRejected("artifact bytes do not match pinned digest")
    finally:
        os.close(fd)


def verify_local_manifest(root: Path, manifest_path: Path, *, expected_manifest_sha256: str) -> dict[str, Any]:
    """Verify an exact caller-pinned manifest and all its local artifact bytes."""
    if not _hex64(expected_manifest_sha256):
        raise CompositionRejected("invalid expected manifest digest")
    manifest, raw = read_object(manifest_path, MAX_MANIFEST_BYTES)
    if sha256(raw) != expected_manifest_sha256:
        raise CompositionRejected("manifest source drift")
    if set(manifest) != {"schema", "model_alias", "artifacts"} or manifest["schema"] != "MINI_VERA_LOCAL_MODEL_MANIFEST_V1":
        raise CompositionRejected("invalid local model manifest")
    model = manifest["model_alias"]
    if type(model) is not str or not 1 <= len(model) <= 128 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-" for c in model):
        raise CompositionRejected("invalid local model alias")
    artifacts = manifest["artifacts"]
    if type(artifacts) is not list or len(artifacts) not in (1, 2):
        raise CompositionRejected("invalid artifact count")
    seen: set[str] = set()
    total = 0
    bound: list[dict[str, Any]] = []
    pending: list[tuple[str, str, str, int, str]] = []
    root = root.resolve(strict=True)
    for item in artifacts:
        if type(item) is not dict or set(item) != {"role", "format", "path", "bytes", "sha256"}:
            raise CompositionRejected("invalid manifest artifact fields")
        role, fmt, relative, size, digest = item["role"], item["format"], item["path"], item["bytes"], item["sha256"]
        if type(role) is not str or role not in FORMATS or role in seen:
            raise CompositionRejected("duplicate or unknown artifact role")
        if type(fmt) is not str or fmt not in FORMATS[role]:
            raise CompositionRejected("invalid artifact format for role")
        if type(relative) is not str or type(size) is not int or not 8 <= size <= MAX_MODEL_BYTES or not _hex64(digest):
            raise CompositionRejected("invalid pinned artifact metadata")
        seen.add(role)
        total += size
        pending.append((role, fmt, relative, size, digest))
        bound.append({"role": role, "format": fmt, "bytes": size, "sha256": digest})
    if "base" not in seen:
        raise CompositionRejected("pinned GGUF base required")
    if total > MAX_TOTAL_PROFILE_BYTES:
        raise CompositionRejected("Mini-Vera total model byte budget exceeded")
    # Enforce combined byte budget before reading even one multi-GiB file.
    for role, fmt, relative, size, digest in pending:
        _hash_local_file(root, relative, size, digest, role=role, artifact_format=fmt)
    # A synthetic registry digest binds every component, not the server's
    # actual loaded checkpoint. Avoid calling this an attested model identity.
    registry_digest = sha256(canonical({"model_alias": model, "artifacts": sorted(bound, key=lambda x: x["role"])}))
    return {
        "schema": "MINI_VERA_LOCAL_ARTIFACT_WITNESS_V1", "model_alias": model,
        "model_registry_digest": registry_digest,
        "manifest_sha256": expected_manifest_sha256, "artifacts": bound,
        "total_bytes": total, "evidence": "LOCAL_BYTES_MATCH_DECLARED_MANIFEST_ONLY",
        "resident_model_identity": "NOT_ATTESTED", "provider_transport": "NOT_PROBED",
    }


def compose_with_local_manifest(*, model_root: Path, model_manifest: Path,
                                expected_manifest_sha256: str, **composer_args: Any) -> dict[str, Any]:
    """Feed measured local model bytes into the existing pure composer."""
    if "model" in composer_args or "model_digest" in composer_args:
        raise CompositionRejected("model fields must originate in verified local manifest")
    witness = verify_local_manifest(model_root, model_manifest,
                                    expected_manifest_sha256=expected_manifest_sha256)
    result = compose(**composer_args, model=witness["model_alias"],
                     model_digest=witness["model_registry_digest"])
    result["provenance"]["local_artifact_manifest_sha256"] = witness["manifest_sha256"]
    result["evidence"]["local_model_bytes"] = witness["evidence"]
    result["evidence"]["resident_model_identity"] = witness["resident_model_identity"]
    return result
