"""Offline, operator-declared local model-byte binding (not upstream attestation)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from .adapter_prep import _reject_git_checkout, _require_private_filesystem
from .lora_runner import _model_snapshot

_REPO = "Qwen/Qwen3-0.6B"
_REQUIRED = {"config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors"}
_OPTIONAL = {"generation_config.json", "merges.txt", "vocab.json", "special_tokens_map.json"}
_LIMIT = 16 * 1024 * 1024
_DTYPE_BYTES = {
    "BOOL": 1, "U8": 1, "I8": 1,
    "F8_E4M3FN": 1, "F8_E5M2": 1, "F8_E4M3FNUZ": 1, "F8_E5M2FNUZ": 1,
    "U16": 2, "I16": 2, "F16": 2, "BF16": 2,
    "U32": 4, "I32": 4, "F32": 4,
    "U64": 8, "I64": 8, "F64": 8,
}


@dataclass(frozen=True)
class SnapshotBindingReceipt:
    status: str
    binding_sha256: str
    file_count: int


def _pinned(value: object, length: int, label: str) -> None:
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise ValueError(f"{label} must be pinned lowercase {length}-character hex")


def _private_fd(dir_fd: int, name: str) -> tuple[int, os.stat_result]:
    # O_NONBLOCK prevents blocking on a swapped-in FIFO before fstat rejects it.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=dir_fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        os.close(fd)
        raise ValueError("model files require private 0600 regular files with no hardlinks")
    return fd, info


def _json_file(dir_fd: int, name: str) -> dict:
    fd, info = _private_fd(dir_fd, name)
    with os.fdopen(fd, "rb") as stream:
        if info.st_size > _LIMIT:
            raise ValueError("model metadata too large")
        try:
            data = json.loads(stream.read(_LIMIT + 1))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid model metadata JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("model metadata must be an object")
    return data


def _safetensors(dir_fd: int, name: str) -> None:
    fd, info = _private_fd(dir_fd, name)
    with os.fdopen(fd, "rb") as stream:
        prefix = stream.read(8)
        if len(prefix) != 8:
            raise ValueError("truncated safetensors header")
        length = struct.unpack("<Q", prefix)[0]
        if not 2 <= length <= _LIMIT or length + 8 >= info.st_size:
            raise ValueError("invalid safetensors header length")
        try:
            # Duplicate JSON keys are ambiguous metadata and must fail closed.
            def unique_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate safetensors metadata key")
                    result[key] = value
                return result

            header = json.loads(stream.read(length), object_pairs_hook=unique_keys)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid safetensors metadata") from exc
    if not isinstance(header, dict) or not (tensors := {k: v for k, v in header.items() if k != "__metadata__"}):
        raise ValueError("safetensors lacks tensors")
    remaining = info.st_size - length - 8
    occupied = []
    for tensor in tensors.values():
        if not isinstance(tensor, dict):
            raise ValueError("malformed safetensors tensor")
        shape, offsets = tensor.get("shape"), tensor.get("data_offsets")
        if (not isinstance(tensor.get("dtype"), str) or not isinstance(shape, list)
            or any(type(s) is not int or s < 0 for s in shape)
            or not isinstance(offsets, list) or len(offsets) != 2
            or any(type(n) is not int for n in offsets)
            or not 0 <= offsets[0] <= offsets[1] <= remaining):
            raise ValueError("invalid safetensors tensor offsets/shape")
        width = _DTYPE_BYTES.get(tensor["dtype"])
        if width is None or len(shape) > 32:
            raise ValueError("unsupported safetensors dtype or shape rank")
        count = 1
        for dim in shape:
            count *= dim
            if count * width > remaining:
                raise ValueError("safetensors shape exceeds tensor payload")
        if (offsets[1] - offsets[0]) != count * width:
            raise ValueError("safetensors dtype and shape disagree with byte offsets")
        occupied.append(tuple(offsets))
    # Safetensors specifies non-overlapping data offsets covering the payload.
    end = 0
    for start, stop in sorted(occupied):
        if start != end:
            raise ValueError("noncontiguous/overlapping safetensors tensor bytes")
        end = stop
    if end != remaining:
        raise ValueError("safetensors payload has unaccounted bytes")


def _digest(dir_fd: int, name: str) -> str:
    fd, before = _private_fd(dir_fd, name)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        while data := stream.read(4 * 1024 * 1024):
            digest.update(data)
        after = os.fstat(stream.fileno())
    if (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns) != (
        after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns
    ):
        raise ValueError("model file changed while hashing")
    return digest.hexdigest()


def bind_private_model_snapshot(
    model_dir: Path, *, hf_repo: str, revision_sha: str,
    tokenizer_revision_sha: str, expected_chat_template_sha256: str,
    origin_evidence_ref: str,
) -> SnapshotBindingReceipt:
    """Bind a *staged copy* in place; never modify pre-existing model bytes.

    Origin revisions and independent evidence digest are operator declarations;
    no remote publisher authenticity or licensing is verified by this function.
    """
    if not sys.platform.startswith("linux"):
        raise ValueError("binding requires a qualified local Linux filesystem")
    if hf_repo != _REPO:
        raise ValueError("unsupported model family")
    _pinned(revision_sha, 40, "model revision")
    _pinned(tokenizer_revision_sha, 40, "tokenizer revision")
    _pinned(expected_chat_template_sha256, 64, "expected chat template")
    if not isinstance(origin_evidence_ref, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", origin_evidence_ref):
        raise ValueError("separately retained origin evidence requires a sha256:<64hex> reference")
    if not isinstance(model_dir, Path) or not model_dir.is_absolute():
        raise ValueError("model directory must have an absolute Linux path")
    _require_private_filesystem(model_dir, "model snapshot")
    _reject_git_checkout(model_dir, "model snapshot")
    if model_dir.is_symlink() or not model_dir.is_dir() or stat.S_IMODE(model_dir.stat().st_mode) != 0o700:
        raise ValueError("model snapshot must be a non-symlink owner-only 0700 directory")
    names = {p.name for p in model_dir.iterdir()}
    if "VERA_SOURCE.json" in names:
        raise ValueError("VERA_SOURCE.json already exists and cannot be overwritten")
    if not _REQUIRED <= names or not names <= _REQUIRED | _OPTIONAL:
        raise ValueError("expected flat, complete original-format Qwen3-0.6B model files")
    dir_fd = os.open(model_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in names:
            _require_private_filesystem(model_dir / name, "model file")
        if _json_file(dir_fd, "config.json").get("model_type") != "qwen3":
            raise ValueError("model config must be qwen3")
        template = _json_file(dir_fd, "tokenizer_config.json").get("chat_template")
        if not isinstance(template, str) or hashlib.sha256(template.encode("utf-8")).hexdigest() != expected_chat_template_sha256:
            raise ValueError("chat template does not match explicit expected digest")
        _json_file(dir_fd, "tokenizer.json")
        _safetensors(dir_fd, "model.safetensors")
        files = {name: _digest(dir_fd, name) for name in sorted(names)}
        binding = {
            "schema_version": 1, "hf_repo": hf_repo,
            "revision_sha": revision_sha,
            "tokenizer_revision_sha": tokenizer_revision_sha,
            "chat_template_sha256": expected_chat_template_sha256,
            "files_sha256": files,
        }
        content = (json.dumps(binding, sort_keys=True, indent=2) + "\n").encode()
        try:
            output_fd = os.open("VERA_SOURCE.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
        except FileExistsError as exc:
            raise ValueError("VERA_SOURCE.json already exists and cannot be overwritten") from exc
        try:
            with os.fdopen(output_fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            binding_sha = _model_snapshot(model_dir, binding)
        except BaseException:
            os.unlink("VERA_SOURCE.json", dir_fd=dir_fd)
            raise
    finally:
        os.close(dir_fd)
    return SnapshotBindingReceipt("DECLARED_ORIGIN_BYTES_HASHED_ONLY", binding_sha, len(files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline binding of operator-staged private Qwen3-0.6B files")
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--hf-repo", required=True)
    parser.add_argument("--revision-sha", required=True)
    parser.add_argument("--tokenizer-revision-sha", required=True)
    parser.add_argument("--chat-template-sha256", required=True)
    parser.add_argument("--origin-evidence-ref", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = bind_private_model_snapshot(
            args.model_dir, hf_repo=args.hf_repo, revision_sha=args.revision_sha,
            tokenizer_revision_sha=args.tokenizer_revision_sha,
            expected_chat_template_sha256=args.chat_template_sha256,
            origin_evidence_ref=args.origin_evidence_ref,
        )
    except OSError:
        print("SOURCE_BINDING_HOLD: private local filesystem operation failed", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"SOURCE_BINDING_HOLD: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
