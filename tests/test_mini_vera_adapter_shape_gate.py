"""Read-only metadata shape check; no trained-base identity or merge permission."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from tools.mini_vera import adapter_shape_gate as gate


BASE_TARGET = "model.language_model.layers.0.mlp.gate_proj.weight"
LORA_PREFIX = "base_model.model.model.layers.0.mlp.gate_proj"


def write_tensor_file(path: Path, shapes: dict[str, tuple[str, list[int]]]):
    offset = 0
    tensor_map = {}
    for name, (dtype, shape) in shapes.items():
        width = {"F32": 4, "BF16": 2}[dtype]
        byte_count = width
        for dim in shape:
            byte_count *= dim
        tensor_map[name] = {
            "dtype": dtype, "shape": shape,
            "data_offsets": [offset, offset + byte_count]}
        offset += byte_count
    raw = json.dumps(tensor_map, sort_keys=True).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\0" * offset)


def fixture(root: Path, *, bad=False, half=False, escape=False):
    base = root / "hf-base"
    base.mkdir()
    adapter = root / "adapter"
    adapter.mkdir()
    config = adapter / "adapter_config.json"
    config.write_text(json.dumps({
        "peft_type": "LORA", "r": 2,
        "base_model_name_or_path": "D:\\VERA\\synthetic-base"}))
    item = BASE_TARGET
    base_name = ("../outside.safetensors" if escape
                 else "model.safetensors-00001-of-00001.safetensors")
    (base / "model.safetensors.index.json").write_text(json.dumps({
        "weight_map": {item: base_name}, "metadata": {"total_size": 24}}))
    if not escape:
        write_tensor_file(base / base_name, {item: ("BF16", [3, 4])})
    adapter_tensors = {
        LORA_PREFIX + ".lora_A.weight": ("F32", [2, 5 if bad else 4]),
        LORA_PREFIX + ".lora_B.weight": ("F32", [3, 2])}
    if half:
        del adapter_tensors[LORA_PREFIX + ".lora_B.weight"]
    model = adapter / "adapter_model.safetensors"
    write_tensor_file(model, adapter_tensors)
    return config, model, base


class AdapterShapeGateTests(unittest.TestCase):
    def test_valid_structural_pair_passes_but_weight_ancestry_remains_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg, adapter, base = fixture(Path(temp))
            result = gate.inspect(cfg, adapter, base)
        self.assertEqual("SHAPES_MATCH_ANCESTRY_UNKNOWN", result["status"])
        self.assertEqual(1, result["pair_count"])
        self.assertEqual(1, result["matched_pairs"])
        self.assertEqual(0, result["failed_pairs"])
        self.assertFalse(result["proves_weight_ancestry"])
        self.assertFalse(result["runtime_qualified"])
        self.assertEqual("NONE", result["authority_effect"])
        self.assertEqual("HEADER_BYTES_ONLY_NOT_FULL_WEIGHT_HASH",
                         result["evidence_class"])
        self.assertEqual(64, len(result["adapter_header_sha256"]))

    def test_mismatched_dimensions_never_return_match(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg, adapter, base = fixture(Path(temp), bad=True)
            result = gate.inspect(cfg, adapter, base)
        self.assertEqual("SHAPE_MISMATCH_ANCESTRY_UNKNOWN", result["status"])
        self.assertEqual(0, result["matched_pairs"])
        self.assertEqual(1, result["failed_pairs"])

    def test_missing_adapter_pair_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg, adapter, base = fixture(Path(temp), half=True)
            result = gate.inspect(cfg, adapter, base)
        self.assertEqual("SHAPE_MISMATCH_ANCESTRY_UNKNOWN", result["status"])
        self.assertEqual(1, result["failed_pairs"])

    def test_untrusted_shard_escape_is_refused_without_reading_outside(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg, adapter, base = fixture(root, escape=True)
            outside = root / "outside.safetensors"
            outside.write_bytes(b"UNTOUCHED")
            with self.assertRaisesRegex(ValueError, "shard name"):
                gate.inspect(cfg, adapter, base)
            self.assertEqual(b"UNTOUCHED", outside.read_bytes())

    def test_bad_tensor_header_refuses_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg, adapter, base = fixture(Path(temp))
            adapter.write_bytes(struct.pack("<Q", 8*1024*1024))
            with self.assertRaisesRegex(ValueError, "header"):
                gate.inspect(cfg, adapter, base)

    def test_unhashable_dtype_is_clean_validation_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg, adapter, base = fixture(Path(temp))
            bad = {LORA_PREFIX + ".lora_A.weight": {
                "dtype": [], "shape": [2, 4], "data_offsets": [0, 32]}}
            raw = json.dumps(bad).encode("utf-8")
            adapter.write_bytes(struct.pack("<Q", len(raw)) + raw + b"\\0" * 32)
            with self.assertRaisesRegex(ValueError, "invalid tensor shape"):
                gate.inspect(cfg, adapter, base)

    def test_cli_status_is_unqualified_even_when_shapes_match(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg, adapter, base = fixture(Path(temp))
            result = subprocess.run(
                [sys.executable, "-m", "tools.mini_vera.adapter_shape_gate",
                 "--adapter-config", str(cfg), "--adapter-file", str(adapter),
                 "--hf-base", str(base)],
                capture_output=True, text=True, timeout=10)
        self.assertEqual(2, result.returncode, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual("SHAPES_MATCH_ANCESTRY_UNKNOWN", body["status"])
        self.assertFalse(body["proves_weight_ancestry"])


if __name__ == "__main__":
    unittest.main()
