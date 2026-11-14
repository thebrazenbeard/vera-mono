"""Offline GGUF v3 architecture metadata checks cannot prove model ancestry."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from tools.mini_vera import gguf_architecture_gate as gate


def ggstr(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def mkgguf(path: Path, *, hidden: int = 64, blocks: tuple[int, ...] = (0, 1),
           missing_gguf_eos: bool = False, bad_array: bool = False,
           overlong_name: bool = False) -> None:
    values = {
        "general.architecture": (8, "qwen35"),
        "general.name": (8, "Synthetic 2-layer GGUF"),
        "qwen35.block_count": (4, 2),
        "qwen35.embedding_length": (4, hidden),
        "qwen35.feed_forward_length": (4, 128),
        "qwen35.attention.head_count": (4, 8),
        "qwen35.attention.head_count_kv": (4, 2),
        "qwen35.full_attention_interval": (4, 4),
        "tokenizer.ggml.tokens": (9, ["one", "two", "<|im_end|>"]),
    }
    if not missing_gguf_eos:
        values["tokenizer.ggml.eos_token_id"] = (4, 51)
    ts = [("token_embd.weight", [64, 100], 0, 0)]
    ts.extend((f"blk.{i}.ffn_gate.weight", [64, 128], 12, 100 + i*1024)
              for i in blocks)
    data = bytearray(b"GGUF")
    data.extend(struct.pack("<IQQ", 3, len(ts), len(values)))
    for key, (kind, value) in values.items():
        data.extend(ggstr(key))
        data.extend(struct.pack("<I", kind))
        if kind == 8:
            data.extend(ggstr(value))
        elif kind == 4:
            data.extend(struct.pack("<I", value))
        elif kind == 9:
            data.extend(struct.pack("<IQ", 999 if bad_array else 8, len(value)))
            for item in value:
                data.extend(ggstr(item))
    for name, shape, typ, offset in ts:
        if overlong_name and name.startswith("blk."):
            data.extend(struct.pack("<Q", 10**8))
            break
        data.extend(ggstr(name))
        data.extend(struct.pack("<I", len(shape)))
        data.extend(struct.pack("<" + "Q" * len(shape), *shape))
        data.extend(struct.pack("<IQ", typ, offset))
    path.write_bytes(data + b"\0" * 8192)


def mkfiles(root: Path, **gguf_options):
    base = root/"base"
    base.mkdir()
    cfg = base/"config.json"
    cfg.write_text(json.dumps({"model_type": "qwen3_5", "text_config": {
        "num_hidden_layers": 2, "hidden_size": 64,
        "intermediate_size": 128, "num_attention_heads": 8,
        "num_key_value_heads": 2, "full_attention_interval": 4,
        "vocab_size": 100, "eos_token_id": 50}}))
    tok = base/"tokenizer_config.json"
    tok.write_text(json.dumps({
        "eos_token": "<|im_end|>",
        "added_tokens_decoder": {
            "50": {"content": "<|endoftext|>"},
            "51": {"content": "<|im_end|>"}}}))
    gguf = root/"base.gguf"
    mkgguf(gguf, **gguf_options)
    return cfg, tok, gguf


class GgufArchitectureTests(unittest.TestCase):
    def test_matches_public_structure_but_not_source_weight_ancestry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp))
            report=gate.inspect(cfg,tok,gguf)
        self.assertEqual("ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN",report["status"])
        self.assertEqual(3,report["tensor_count"])
        self.assertEqual([0,1], report["gguf_layer_indices"])
        self.assertEqual(0,report["architecture_mismatch_count"])
        self.assertEqual("MATCH",report["hf_tokenizer_eos_relation"])
        self.assertEqual("MISMATCH",report["hf_model_config_eos_relation"])
        self.assertFalse(report["proves_weight_ancestry"])
        self.assertFalse(report["proves_gguf_conversion_equivalence"])
        self.assertEqual("NONE",report["authority_effect"])
        self.assertEqual("METADATA_ONLY_NO_WEIGHT_READ",report["evidence_class"])

    def test_hidden_width_mismatch_is_not_elevated_to_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp),hidden=80)
            report=gate.inspect(cfg,tok,gguf)
        self.assertEqual("ARCHITECTURE_MISMATCH_ANCESTRY_UNKNOWN",report["status"])
        self.assertIn("hidden_size",report["architecture_mismatch_fields"])

    def test_missing_layer_cannot_look_like_complete_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp),blocks=(0,))
            report=gate.inspect(cfg,tok,gguf)
        self.assertEqual("ARCHITECTURE_MISMATCH_ANCESTRY_UNKNOWN",report["status"])
        self.assertIn("layer_tensor_coverage",report["architecture_mismatch_fields"])

    def test_missing_gguf_eos_is_unknown_not_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp),missing_gguf_eos=True)
            report=gate.inspect(cfg,tok,gguf)
        self.assertEqual("UNKNOWN",report["hf_tokenizer_eos_relation"])

    def test_invalid_array_subtype_is_controlled_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp),bad_array=True)
            with self.assertRaisesRegex(ValueError,"array type"):
                gate.inspect(cfg,tok,gguf)

    def test_oversized_tensor_name_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp),overlong_name=True)
            with self.assertRaisesRegex(ValueError,"string length"):
                gate.inspect(cfg,tok,gguf)

    def test_cli_return_two_even_on_matched_architecture(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg,tok,gguf=mkfiles(Path(tmp))
            proc=subprocess.run(
                [sys.executable,"-m","tools.mini_vera.gguf_architecture_gate",
                 "--hf-config",str(cfg),"--hf-tokenizer",str(tok),
                 "--gguf",str(gguf)],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(2,proc.returncode,proc.stderr)
            self.assertEqual("ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN",
                             json.loads(proc.stdout)["status"])


def declarations(root: Path, cfg: Path, gguf: Path,
                 *, base_repo: str = "rodrigomt/Qwen3.5-4B-Uncensored-Aggressive"):
    manifest = root/"MODEL_MANIFEST.json"
    manifest.write_text(json.dumps({"base": {"repository": base_repo,
                                              "revision": "revision-for-declaration-only"},
                                    "package_id": "older-training-package"}))
    adapter = root/"adapter_config.json"
    adapter.write_text(json.dumps({"base_model_name_or_path": str(cfg.parent)}))
    digest = hashlib.sha256(gguf.read_bytes()).hexdigest()
    return manifest, adapter, digest


class GgufPublishedSourceConflictTests(unittest.TestCase):
    def test_pub_base_conflict_changes_report_not_tensor_ancestry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg,tok,gguf = mkfiles(root)
            manifest,adapter,digest = declarations(root,cfg,gguf)
            report = gate.inspect(
                cfg,tok,gguf,hf_package_manifest=manifest,
                adapter_config=adapter,
                publisher_base_repository="Qwen/Qwen3.5-4B",
                expected_gguf_sha256=digest)
        self.assertEqual("DECLARED_UPSTREAM_CONFLICT_ANCESTRY_UNKNOWN",report["status"])
        self.assertEqual("MISMATCH",report["declared_base_repository_relation"])
        self.assertTrue(report["gguf_complete_file_sha256_verified"])
        self.assertEqual("MATCH",report["adapter_local_base_path_relation"])
        self.assertFalse(report["proves_weight_ancestry"])
        self.assertEqual("NONE",report["authority_effect"])
        self.assertEqual("ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN",
                         report["architecture_status"])
        self.assertEqual("DECLARED_ONLY",report["hf_package_manifest_evidence_class"])

    def test_matching_publisher_name_still_cannot_qualify_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cfg,tok,gguf=mkfiles(root)
            manifest,adapter,digest=declarations(root,cfg,gguf,
                base_repo="Qwen/Qwen3.5-4B")
            report=gate.inspect(cfg,tok,gguf,hf_package_manifest=manifest,
                adapter_config=adapter,
                publisher_base_repository="Qwen/Qwen3.5-4B",
                expected_gguf_sha256=digest)
        self.assertEqual("ARCHITECTURE_MATCH_ANCESTRY_UNKNOWN",report["status"])
        self.assertEqual("MATCH",report["declared_base_repository_relation"])
        self.assertFalse(report["runtime_qualified"])

    def test_architecture_mismatch_takes_priority_over_source_claim_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            cfg,tok,gguf=mkfiles(root,hidden=80)
            manifest,adapter,digest=declarations(root,cfg,gguf)
            report=gate.inspect(cfg,tok,gguf,hf_package_manifest=manifest,
                adapter_config=adapter,
                publisher_base_repository="Qwen/Qwen3.5-4B",
                expected_gguf_sha256=digest)
        self.assertEqual("ARCHITECTURE_MISMATCH_ANCESTRY_UNKNOWN",report["status"])
        self.assertEqual("MISMATCH",report["declared_base_repository_relation"])
        self.assertIn("hidden_size",report["architecture_mismatch_fields"])

    def test_false_published_digest_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg,tok,gguf=mkfiles(root)
            manifest,adapter,_=declarations(root,cfg,gguf)
            with self.assertRaisesRegex(ValueError,"full GGUF SHA-256 mismatch"):
                gate.inspect(cfg,tok,gguf,hf_package_manifest=manifest,
                    adapter_config=adapter,
                    publisher_base_repository="Qwen/Qwen3.5-4B",
                    expected_gguf_sha256="0"*64)

    def test_adapter_base_path_must_match_current_hf_config_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg,tok,gguf=mkfiles(root)
            manifest,adapter,digest=declarations(root,cfg,gguf)
            adapter.write_text(json.dumps({"base_model_name_or_path":str(root)}))
            with self.assertRaisesRegex(ValueError,"adapter base path mismatch"):
                gate.inspect(cfg,tok,gguf,hf_package_manifest=manifest,
                    adapter_config=adapter,
                    publisher_base_repository="Qwen/Qwen3.5-4B",
                    expected_gguf_sha256=digest)

    def test_partial_source_claims_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg,tok,gguf=mkfiles(root)
            manifest,_,_=declarations(root,cfg,gguf)
            with self.assertRaisesRegex(ValueError,"all source declaration"):
                gate.inspect(cfg,tok,gguf,hf_package_manifest=manifest)

    def test_cli_emits_conflict_and_nonzero_qualification_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg,tok,gguf=mkfiles(root)
            manifest,adapter,digest=declarations(root,cfg,gguf)
            cmd=[sys.executable,"-B","-m",
                 "tools.mini_vera.gguf_architecture_gate",
                 "--hf-config",str(cfg),"--hf-tokenizer",str(tok),
                 "--gguf",str(gguf),"--hf-package-manifest",str(manifest),
                 "--adapter-config",str(adapter),
                 "--publisher-base-repository","Qwen/Qwen3.5-4B",
                 "--expected-gguf-sha256",digest]
            proc=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        self.assertEqual(2,proc.returncode,proc.stderr)
        self.assertEqual("DECLARED_UPSTREAM_CONFLICT_ANCESTRY_UNKNOWN",
                         json.loads(proc.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
