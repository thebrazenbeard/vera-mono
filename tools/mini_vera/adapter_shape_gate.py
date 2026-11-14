"""Bounded read-only Qwen3.5 HF LoRA/base tensor-shape gate.

Checks declared file metadata only. A perfect shape match is NOT proof of a
training-base revision, identical weights, GGUF converter parity, or a license.
The CLI deliberately returns nonzero even on structural match.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any

_HEADER_LIMIT = 2 * 1024 * 1024
_INDEX_LIMIT = 256 * 1024
_SHARD = re.compile(r"model\.safetensors-\d{5}-of-\d{5}\.safetensors\Z")
_SUFFIX = re.compile(r"base_model\.model\.model\.(.+)\.lora_([AB])\.weight\Z")
_WIDTH = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "I64": 8,
          "I32": 4, "I16": 2, "I8": 1, "U8": 1, "BOOL": 1}


def _non_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError("duplicate metadata key")
        value[key] = entry
    return value


def _bytes(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("missing, linked, or oversized metadata file")
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError("oversized metadata file")
    return data


def _decode(raw: bytes) -> dict[str, Any]:
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_non_duplicate)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON metadata") from exc
    if type(obj) is not dict:
        raise ValueError("metadata must be a JSON object")
    return obj


def _tensor_header(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked tensor file")
    length = path.stat().st_size
    if length < 10:
        raise ValueError("truncated tensor header")
    with path.open("rb") as stream:
        prefix = stream.read(8)
        n = struct.unpack("<Q", prefix)[0]
        if n <= 1 or n > _HEADER_LIMIT or n + 8 > length:
            raise ValueError("invalid or oversized tensor header")
        raw = stream.read(n)
    if len(raw) != n:
        raise ValueError("truncated tensor header")
    content = _decode(raw)
    payload_length = length - 8 - n
    for key, item in content.items():
        if key == "__metadata__":
            continue
        if type(item) is not dict:
            raise ValueError("invalid tensor metadata")
        dtype, shape, offsets = (item.get("dtype"), item.get("shape"),
                                 item.get("data_offsets"))
        if (type(dtype) is not str or dtype not in _WIDTH
                or type(shape) is not list
                or not 1 <= len(shape) <= 8
                or any(type(dim) is not int or not 0 < dim <= 10**8
                       for dim in shape)
                or type(offsets) is not list or len(offsets) != 2
                or any(type(n) is not int for n in offsets)
                or not 0 <= offsets[0] < offsets[1] <= payload_length):
            raise ValueError("invalid tensor shape or offsets")
        size = _WIDTH[dtype]
        for dim in shape:
            size *= dim
        if offsets[1] - offsets[0] != size:
            raise ValueError("tensor byte count does not match shape")
    return content, hashlib.sha256(raw).hexdigest()


def inspect(adapter_config: Path, adapter_file: Path,
            hf_base: Path) -> dict[str, Any]:
    """Compare explicit LoRA A/B pairs to actual HF base tensor headers."""
    if adapter_config.name != "adapter_config.json" or \
            adapter_file.name != "adapter_model.safetensors":
        raise ValueError("expected named PEFT adapter config and file")
    if hf_base.is_symlink() or not hf_base.is_dir():
        raise ValueError("base directory unavailable or linked")
    cfg_bytes = _bytes(adapter_config, _INDEX_LIMIT)
    cfg = _decode(cfg_bytes)
    rank = cfg.get("r")
    if cfg.get("peft_type") != "LORA" or type(rank) is not int or not 1 <= rank <= 256:
        raise ValueError("expected PEFT LoRA with valid rank")
    idx_bytes = _bytes(hf_base / "model.safetensors.index.json", _INDEX_LIMIT)
    index = _decode(idx_bytes).get("weight_map")
    if type(index) is not dict or not index:
        raise ValueError("invalid base shard index")
    if any(type(k) is not str or type(name) is not str
           or not _SHARD.fullmatch(name) for k, name in index.items()):
        raise ValueError("invalid base shard name in index")
    adapter_header, adapter_header_hash = _tensor_header(adapter_file)
    tensors = {k: v for k, v in adapter_header.items() if k != "__metadata__"}
    if not tensors or len(tensors) > 8192:
        raise ValueError("empty or implausibly large adapter tensor set")
    pairs: dict[str, dict[str, dict[str, Any]]] = {}
    for name, value in tensors.items():
        match = _SUFFIX.fullmatch(name)
        if not match:
            raise ValueError("unrecognized LoRA tensor name")
        path, part = match.groups()
        target = "model.language_model." + path + ".weight"
        pair = pairs.setdefault(target, {})
        if part in pair:
            raise ValueError("duplicate LoRA pair member")
        pair[part] = value
    shard_headers: dict[str, dict[str, Any]] = {}
    shard_hashes: dict[str, str] = {}
    failures: list[str] = []
    matched = 0
    for target, ab in sorted(pairs.items()):
        shard = index.get(target)
        if type(shard) is not str:
            failures.append(target + ":missing_base")
            continue
        if shard not in shard_headers:
            header, digest = _tensor_header(hf_base / shard)
            shard_headers[shard] = header
            shard_hashes[shard] = digest
        base = shard_headers[shard].get(target)
        A = ab.get("A")
        B = ab.get("B")
        if type(base) is not dict or A is None or B is None:
            failures.append(target + ":missing_pair_or_tensor")
            continue
        sa, sb, sc = A["shape"], B["shape"], base["shape"]
        if (len(sa) == len(sb) == len(sc) == 2
                and sa[0] == sb[1] == rank
                and sa[1] == sc[1] and sb[0] == sc[0]):
            matched += 1
        else:
            failures.append(target + ":shape_or_rank_mismatch")
    count = len(pairs)
    return {
        "schema": "MINI_VERA_HF_ADAPTER_SHAPE_V1",
        "status": ("SHAPES_MATCH_ANCESTRY_UNKNOWN" if not failures
                   else "SHAPE_MISMATCH_ANCESTRY_UNKNOWN"),
        "pair_count": count, "matched_pairs": matched,
        "failed_pairs": count - matched,
        "failure_samples": failures[:12],
        "adapter_rank": rank,
        "adapter_header_sha256": adapter_header_hash,
        "adapter_config_sha256": hashlib.sha256(cfg_bytes).hexdigest(),
        "base_index_sha256": hashlib.sha256(idx_bytes).hexdigest(),
        "base_shard_header_sha256": dict(sorted(shard_hashes.items())),
        "evidence_class": "HEADER_BYTES_ONLY_NOT_FULL_WEIGHT_HASH",
        "proves_weight_ancestry": False,
        "proves_gguf_equivalence": False,
        "runtime_qualified": False,
        "authority_effect": "NONE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter-config", type=Path, required=True)
    parser.add_argument("--adapter-file", type=Path, required=True)
    parser.add_argument("--hf-base", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.adapter_config, args.adapter_file, args.hf_base)
    except (ValueError, OSError) as exc:
        result = {"schema": "MINI_VERA_HF_ADAPTER_SHAPE_V1",
                  "status": "UNABLE_TO_VALIDATE",
                  "authority_effect": "NONE", "error": str(exc)}
        print(json.dumps(result, sort_keys=True))
        return 3
    print(json.dumps(result, sort_keys=True))
    # Even matching tensor dimensions never authorize a merge or inference.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
