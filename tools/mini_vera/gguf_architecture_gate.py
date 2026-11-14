"""Read-only GGUF-v3/HF architecture metadata comparison; never weight ancestry.

Based on ggml-org/llama.cpp ggml/include/gguf.h public format specification.
No model weights are read, mapped, inferred, merged, or loaded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any

_MAX_METADATA_BYTES = 64 * 1024 * 1024
_MAX_JSON_BYTES = 256 * 1024
_MAX_ARRAY_ELEMENTS = 500_000
_MAX_NAME_BYTES = 4096
_NUMERIC_FORMATS = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d",
}
_LAYERS = re.compile(r"blk\.(\d+)\.")


def _json_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("invalid linked or oversized HF metadata")
    def unique(pairs):
        d = {}
        for key, value in pairs:
            if key in d:
                raise ValueError("duplicate HF JSON metadata field")
            d[key] = value
        return d
    try:
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid HF JSON") from exc
    if type(result) is not dict:
        raise ValueError("HF metadata must be object")
    return result


class _Reader:
    def __init__(self, file):
        self.file = file
        self.size = file.seek(0, 2)
        file.seek(0)

    def read(self, n: int) -> bytes:
        if n < 0 or n > _MAX_METADATA_BYTES or self.file.tell() + n > self.size \
                or self.file.tell() + n > _MAX_METADATA_BYTES:
            raise ValueError("GGUF metadata exceeds bounded header")
        raw = self.file.read(n)
        if len(raw) != n:
            raise ValueError("truncated GGUF header")
        return raw

    def skip(self, n: int) -> None:
        if n < 0 or self.file.tell() + n > self.size \
                or self.file.tell() + n > _MAX_METADATA_BYTES:
            raise ValueError("GGUF metadata exceeds bounded header")
        self.file.seek(n, 1)

    def scalar(self, type_id: int) -> int | float | bool:
        fmt = _NUMERIC_FORMATS.get(type_id)
        if fmt is None:
            raise ValueError("unsupported GGUF metadata scalar type")
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]

    def u32(self) -> int:
        return int(self.scalar(4))

    def u64(self) -> int:
        return int(self.scalar(10))

    def string(self, *, keep: bool = True) -> str | None:
        n = self.u64()
        if n > _MAX_METADATA_BYTES:
            raise ValueError("GGUF string length unbounded")
        if keep:
            if n > _MAX_NAME_BYTES:
                raise ValueError("GGUF string length too large to retain")
            try:
                return self.read(n).decode("utf-8")
            except UnicodeError as exc:
                raise ValueError("invalid GGUF UTF-8") from exc
        self.skip(n)
        return None

    def value(self, typ: int, *, keep: bool = False) -> Any:
        if typ in _NUMERIC_FORMATS:
            return self.scalar(typ) if keep else (self.skip(
                struct.calcsize(_NUMERIC_FORMATS[typ])) or None)
        if typ == 8:
            return self.string(keep=keep)
        if typ == 9:
            inner, count = self.u32(), self.u64()
            if count > _MAX_ARRAY_ELEMENTS:
                raise ValueError("GGUF array length too large")
            if inner in _NUMERIC_FORMATS:
                self.skip(struct.calcsize(_NUMERIC_FORMATS[inner]) * count)
            elif inner == 8:
                for _ in range(count):
                    self.string(keep=False)
            else:
                raise ValueError("unsupported GGUF array type")
            return {"item_type": inner, "count": count} if keep else None
        raise ValueError("unsupported GGUF value type")


def _metadata(file_path: Path) -> dict[str, Any]:
    if file_path.suffix.lower() != ".gguf" or file_path.is_symlink() \
            or not file_path.is_file():
        raise ValueError("GGUF must be regular .gguf file")
    with file_path.open("rb") as file:
        reader = _Reader(file)
        if reader.read(4) != b"GGUF":
            raise ValueError("invalid GGUF magic")
        version = reader.u32()
        if version != 3:
            raise ValueError("unsupported GGUF version")
        nt, nk = reader.u64(), reader.u64()
        if not 1 <= nt <= 20000 or not 1 <= nk <= 2000:
            raise ValueError("GGUF tensor/key counts unreasonable")
        keep_keys = {
            "general.architecture", "general.file_type", "general.name",
            "general.source.url", "general.source.huggingface.repository",
            "general.source.huggingface.revision",
            "qwen35.block_count", "qwen35.embedding_length",
            "qwen35.feed_forward_length", "qwen35.attention.head_count",
            "qwen35.attention.head_count_kv", "qwen35.full_attention_interval",
            "tokenizer.ggml.eos_token_id",
        }
        values: dict[str, Any] = {}
        for _ in range(nk):
            name = reader.string()
            if name in values:
                raise ValueError("duplicate GGUF metadata key")
            typ = reader.u32()
            values[name] = reader.value(typ, keep=name in keep_keys)
        layer_indices: set[int] = set()
        tensor_names: set[str] = set()
        token_embedding = None
        quant_types: Counter[int] = Counter()
        for _ in range(nt):
            name = reader.string()
            if not name or name in tensor_names:
                raise ValueError("duplicate or blank GGUF tensor name")
            tensor_names.add(name)
            rank = reader.u32()
            if not 1 <= rank <= 8:
                raise ValueError("GGUF tensor rank out of bounds")
            shape = [reader.u64() for _ in range(rank)]
            if any(not 1 <= dim <= 10**9 for dim in shape):
                raise ValueError("GGUF tensor dimension out of bounds")
            quant_type, offset = reader.u32(), reader.u64()
            if offset > reader.size:
                raise ValueError("GGUF tensor offset beyond file")
            quant_types[quant_type] += 1
            matched = _LAYERS.match(name)
            if matched:
                layer_indices.add(int(matched.group(1)))
            if name == "token_embd.weight":
                token_embedding = shape
        meta_end = file.tell()
        file.seek(0)
        h = hashlib.sha256()
        remaining = meta_end
        while remaining:
            chunk = file.read(min(1024*1024, remaining))
            if not chunk:
                raise ValueError("truncated GGUF metadata during hash")
            h.update(chunk)
            remaining -= len(chunk)
        return {
            "version": version, "tensor_count": nt, "key_count": nk,
            "values": values, "layer_indices": sorted(layer_indices),
            "token_embedding_shape": token_embedding,
            "quant_type_counts": dict(sorted(quant_types.items())),
            "header_sha256": h.hexdigest(),
            "header_bytes": meta_end,
            "file_bytes": reader.size,
        }


def _relation(left: Any, right: Any) -> str:
    if type(left) is not int or type(right) is not int:
        return "UNKNOWN"
    return "MATCH" if left == right else "MISMATCH"


def inspect(hf_config: Path, hf_tokenizer: Path, gguf: Path) -> dict[str, Any]:
    cfg = _json_file(hf_config)
    tokenizer = _json_file(hf_tokenizer)
    if cfg.get("model_type") != "qwen3_5":
        raise ValueError("expected HF Qwen3.5 configuration")
    text_config = cfg.get("text_config")
    if type(text_config) is not dict:
        raise ValueError("missing HF Qwen3.5 text configuration")
    info = _metadata(gguf)
    gg = info["values"]
    fields = {
        "layers": ("num_hidden_layers", "qwen35.block_count"),
        "hidden_size": ("hidden_size", "qwen35.embedding_length"),
        "feed_forward_size": ("intermediate_size", "qwen35.feed_forward_length"),
        "attention_heads": ("num_attention_heads", "qwen35.attention.head_count"),
        "key_value_heads": ("num_key_value_heads", "qwen35.attention.head_count_kv"),
        "full_attention_interval": ("full_attention_interval",
                                    "qwen35.full_attention_interval"),
    }
    observed = {name: _relation(text_config.get(hf), gg.get(g))
                for name, (hf, g) in fields.items()}
    mismatches = [
        name for name, relation in observed.items() if relation != "MATCH"
    ]
    if gg.get("general.architecture") != "qwen35":
        mismatches.append("architecture")
    layer_num = text_config.get("num_hidden_layers")
    if type(layer_num) is not int or info["layer_indices"] != list(range(layer_num)):
        mismatches.append("layer_tensor_coverage")
    emb = info["token_embedding_shape"]
    if type(emb) is not list or len(emb) != 2 \
            or _relation(emb[0], text_config.get("hidden_size")) != "MATCH":
        mismatches.append("token_embedding_hidden_width")
    vocab = text_config.get("vocab_size")
    if type(vocab) is int and (type(emb) is not list or len(emb) != 2
                               or emb[1] != vocab):
        mismatches.append("token_embedding_vocabulary_size")

    eos = tokenizer.get("eos_token")
    decoder = tokenizer.get("added_tokens_decoder")
    hf_eos = None
    if type(eos) is str and type(decoder) is dict:
        for key, entry in decoder.items():
            if type(entry) is dict and entry.get("content") == eos:
                try:
                    parsed = int(key)
                except (TypeError, ValueError):
                    continue
                if hf_eos is not None and hf_eos != parsed:
                    hf_eos = None
                    break
                hf_eos = parsed
    gg_eos = gg.get("tokenizer.ggml.eos_token_id")
    source = {
        name: gg.get(name) for name in (
            "general.source.url", "general.source.huggingface.repository",
            "general.source.huggingface.revision")
        if type(gg.get(name)) is str
    }
    return {
        "schema": "MINI_VERA_GGUF_HF_ARCHITECTURE_V1",
        "status": ("ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN" if not mismatches
                   else "ARCHITECTURE_MISMATCH_ANCESTRY_UNKNOWN"),
        "architecture_mismatch_count": len(mismatches),
        "architecture_mismatch_fields": sorted(mismatches),
        "architecture_field_relations": observed,
        "gguf_layer_indices": info["layer_indices"],
        "tensor_count": info["tensor_count"],
        "key_count": info["key_count"],
        "gguf_version": info["version"],
        "gguf_header_bytes": info["header_bytes"],
        "gguf_file_bytes": info["file_bytes"],
        "gguf_header_sha256": info["header_sha256"],
        "gguf_quant_type_counts": info["quant_type_counts"],
        "source_metadata_claims": source,
        "hf_model_config_eos_id": text_config.get("eos_token_id"),
        "hf_tokenizer_eos_id": hf_eos,
        "gguf_eos_id": gg_eos,
        "hf_tokenizer_eos_relation": _relation(hf_eos, gg_eos),
        "hf_model_config_eos_relation":
            _relation(text_config.get("eos_token_id"), gg_eos),
        "evidence_class": "METADATA_ONLY_NO_WEIGHT_READ",
        "proves_weight_ancestry": False,
        "proves_gguf_conversion_equivalence": False,
        "runtime_qualified": False,
        "authority_effect": "NONE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-config", type=Path, required=True)
    parser.add_argument("--hf-tokenizer", type=Path, required=True)
    parser.add_argument("--gguf", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect(args.hf_config, args.hf_tokenizer, args.gguf)
    except (ValueError, OSError) as exc:
        result = {"schema": "MINI_VERA_GGUF_HF_ARCHITECTURE_V1",
                  "status": "UNABLE_TO_VALIDATE",
                  "authority_effect": "NONE", "error": str(exc)}
        print(json.dumps(result, sort_keys=True))
        return 3
    print(json.dumps(result, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
