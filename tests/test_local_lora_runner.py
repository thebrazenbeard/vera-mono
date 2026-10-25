"""Guardrails for explicitly opt-in offline LoRA execution."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.local_training.lora_runner import plan_local_training, train_local_adapter


@unittest.skipIf(os.name == "nt", "POSIX owner-only file semantics unavailable on Windows")
class LocalLoRARunnerTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.corpus = self.root / "approved.jsonl"
        examples = [
            {
                "example_id": f"e-{i}", "group_id": f"source-{i // 2}",
                "provenance": f"source-reviewed-{i}",
                "consent": "owner-approved-local-training",
                "messages": [{"role": "user", "content": f"question {i}"},
                             {"role": "assistant", "content": f"answer {i}"}],
            }
            for i in range(8)
        ]
        self.corpus.write_text("".join(json.dumps(row) + "\n" for row in examples), encoding="utf-8")
        self.corpus.chmod(0o600)
        self.manifest = self.root / "manifest.json"
        self.config = {
            "schema_version": 1,
            "base_model": {
                "hf_repo": "Qwen/Qwen3-0.6B", "revision_sha": "a" * 40,
                "tokenizer_revision_sha": "b" * 40,
                "chat_template_sha256": hashlib.sha256(b"local").hexdigest(),
                "gguf_base_sha256": "d" * 64,
                "license_review": "owner-reviewed",
            },
            "data": {
                "path": str(self.corpus),
                "sha256": hashlib.sha256(self.corpus.read_bytes()).hexdigest(),
                "classification": "private-local-only",
                "approval_reference": "owner-approved-fixture",
            },
            "split": {"seed": 1, "evaluation_fraction": 0.25},
            "execution": {"allow_network": False, "allow_weight_update": False},
        }
        self._write_manifest()
        self.model = self.root / "model"
        self.model.mkdir(mode=0o700)
        (self.model / "config.json").write_text(json.dumps({"model_type": "qwen3"}), encoding="utf-8")
        (self.model / "tokenizer_config.json").write_text(json.dumps({"chat_template": "local"}), encoding="utf-8")
        (self.model / "tokenizer.json").write_text("{}", encoding="utf-8")
        (self.model / "model.safetensors").write_bytes(b"inert-model-fixture")
        self._bind_snapshot()
        self.output = self.root / "adapter-new"

    def _write_manifest(self):
        self.manifest.write_text(json.dumps(self.config), encoding="utf-8")
        self.manifest.chmod(0o600)

    def _bind_snapshot(self):
        paths = tuple(p.name for p in self.model.iterdir() if p.name != "VERA_SOURCE.json")
        binding = {
            "schema_version": 1,
            "hf_repo": self.config["base_model"]["hf_repo"],
            "revision_sha": self.config["base_model"]["revision_sha"],
            "tokenizer_revision_sha": self.config["base_model"]["tokenizer_revision_sha"],
            "chat_template_sha256": self.config["base_model"]["chat_template_sha256"],
            "files_sha256": {
                name: hashlib.sha256((self.model / name).read_bytes()).hexdigest()
                for name in paths
            },
        }
        (self.model / "VERA_SOURCE.json").write_text(json.dumps(binding), encoding="utf-8")
        for item in self.model.iterdir():
            item.chmod(0o600)

    def test_dry_run_binds_local_safetensors_and_never_loads_model_or_writes_output(self):
        with patch("tools.local_training.lora_runner._train_model", side_effect=AssertionError("model loaded")):
            plan = plan_local_training(self.manifest, self.model, self.output)
            self.assertEqual(plan.status, "PREFLIGHT_ONLY_NOT_TRAINED")
            self.assertTrue(plan.model_snapshot_sha256)
        self.assertFalse(self.output.exists())

    def test_cli_train_plan_is_effectless_and_does_not_print_private_samples(self):
        command = [sys.executable, "-m", "tools.local_training", "train-plan", str(self.manifest),
                   str(self.output), "--model-dir", str(self.model)]
        result = subprocess.run(command, capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREFLIGHT_ONLY_NOT_TRAINED", result.stdout)
        self.assertIn("TRAIN_LOCAL_LORA:", result.stdout)
        self.assertNotIn("answer 0", result.stdout)
        self.assertFalse(self.output.exists())

    def test_refuses_qwen35_unqualified_multimodal_architecture(self):
        self.config["base_model"]["hf_repo"] = "Qwen/Qwen3.5-4B"
        self._write_manifest()
        self._bind_snapshot()
        (self.model / "config.json").write_text(json.dumps({"model_type": "qwen3_5"}), encoding="utf-8")
        (self.model / "config.json").chmod(0o600)
        self._bind_snapshot()
        with self.assertRaisesRegex(ValueError, "unsupported.*architecture|multimodal"):
            plan_local_training(self.manifest, self.model, self.output)
        self.assertFalse(self.output.exists())

    def test_refuses_tampered_local_snapshot(self):
        (self.model / "model.safetensors").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "snapshot digest"):
            plan_local_training(self.manifest, self.model, self.output)

    def test_unqualified_model_or_output_filesystem_refuses_before_weight_load(self):
        def gate(_path, description):
            if description in {"model snapshot", "training output parent"}:
                raise ValueError("unqualified Linux filesystem")

        with patch("tools.local_training.lora_runner._require_private_filesystem", side_effect=gate):
            with patch("tools.local_training.lora_runner._train_model", side_effect=AssertionError("weights loaded")):
                with self.assertRaisesRegex(ValueError, "unqualified Linux filesystem"):
                    plan_local_training(self.manifest, self.model, self.output)
        self.assertFalse(self.output.exists())

        def output_gate(_path, description):
            if description == "training output parent":
                raise ValueError("unqualified output")

        with patch("tools.local_training.lora_runner._require_private_filesystem", side_effect=output_gate):
            with self.assertRaisesRegex(ValueError, "unqualified output"):
                plan_local_training(self.manifest, self.model, self.output)
        self.assertFalse(self.output.exists())

    def test_refuses_source_inside_git_checkout(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Git checkout"):
            plan_local_training(self.manifest, self.model, self.output)

    def test_execution_requires_exact_weight_update_approval_before_accelerator_access(self):
        with patch("tools.local_training.lora_runner._require_accelerator", side_effect=AssertionError("accelerator probed")):
            with self.assertRaisesRegex(ValueError, "approval"):
                train_local_adapter(self.manifest, self.model, self.output,
                                    approval="TRAIN_INCORRECT", execute=True)
        self.assertFalse(self.output.exists())

    def test_step_change_requires_new_approval_before_accelerator_access(self):
        one_step = plan_local_training(self.manifest, self.model, self.output)
        with patch("tools.local_training.lora_runner._require_accelerator", side_effect=AssertionError("accelerator probed")):
            with self.assertRaisesRegex(ValueError, "approval"):
                train_local_adapter(self.manifest, self.model, self.output,
                                    approval=one_step.weight_update_approval, execute=True, steps=2)
        self.assertFalse(self.output.exists())

    def test_train_plan_binds_steps_and_recipe_to_approval(self):
        one_step = plan_local_training(self.manifest, self.model, self.output, steps=1)
        two_steps = plan_local_training(self.manifest, self.model, self.output, steps=2)
        self.assertNotEqual(one_step.weight_update_approval, two_steps.weight_update_approval)
        self.assertEqual(one_step.optimizer_steps, 1)
        self.assertEqual(two_steps.optimizer_steps, 2)
        self.assertEqual(one_step.recipe_sha256, two_steps.recipe_sha256)
        self.assertEqual(len(one_step.recipe_sha256), 64)

    def test_cli_train_plan_accepts_explicit_step_count_and_returns_bound_token(self):
        command = [sys.executable, "-m", "tools.local_training", "train-plan", str(self.manifest),
                   str(self.output), "--model-dir", str(self.model), "--steps", "2"]
        result = subprocess.run(command, capture_output=True, text=True,
                                cwd=Path(__file__).resolve().parents[1], timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["optimizer_steps"], 2)
        self.assertEqual(parsed["exact_approval_to_copy_for_train"],
                         plan_local_training(self.manifest, self.model, self.output, steps=2).weight_update_approval)

    def test_loaded_hub_library_refuses_before_accelerator_or_training_output(self):
        plan = plan_local_training(self.manifest, self.model, self.output)
        with patch.dict(sys.modules, {"huggingface_hub": object()}):
            with patch("tools.local_training.lora_runner._require_accelerator", side_effect=AssertionError("GPU accessed")):
                with self.assertRaisesRegex(ValueError, "before offline lock"):
                    train_local_adapter(self.manifest, self.model, self.output,
                                        approval=plan.weight_update_approval, execute=True)
        self.assertFalse(self.output.exists())

    def test_execution_requires_hardware_preflight_without_loading_model(self):
        plan = plan_local_training(self.manifest, self.model, self.output)
        with patch("tools.local_training.lora_runner._require_accelerator", side_effect=ValueError("no supported accelerator")):
            with patch("tools.local_training.lora_runner._train_model", side_effect=AssertionError("model loaded")):
                with self.assertRaisesRegex(ValueError, "no supported accelerator"):
                    train_local_adapter(self.manifest, self.model, self.output,
                                        approval=plan.weight_update_approval, execute=True)
        self.assertFalse(self.output.exists())

    def test_execution_cannot_claim_trained_without_adapter_weight_artifact(self):
        plan = plan_local_training(self.manifest, self.model, self.output)
        fake_gpu = {"gpu_name": "synthetic", "vram_total": 0, "vram_free": 0, "torch_version": "mock"}
        with patch("tools.local_training.lora_runner._require_accelerator", return_value=fake_gpu):
            with patch("tools.local_training.lora_runner._encode_training_rows", return_value=(([1, 2], [-100, 2]),)):
                with patch("tools.local_training.lora_runner._train_model", return_value={"optimizer_steps": 1}):
                    with self.assertRaisesRegex(ValueError, "adapter files absent"):
                        train_local_adapter(self.manifest, self.model, self.output,
                                            approval=plan.weight_update_approval, execute=True)
        self.assertTrue(self.output.is_dir())
        self.assertFalse((self.output / "VERA_ADAPTER_STATUS.json").exists())

    def test_mocked_adapter_artifacts_are_hash_bound_but_not_promoted(self):
        plan = plan_local_training(self.manifest, self.model, self.output)

        def fake_training(_model, _encoded, output, _steps):
            (output / "adapter_model.safetensors").write_bytes(b"synthetic-adapter-not-real-weights")
            (output / "adapter_config.json").write_bytes(b"{}")
            return {"optimizer_steps": 1}

        with patch("tools.local_training.lora_runner._require_accelerator", return_value={}):
            with patch("tools.local_training.lora_runner._encode_training_rows", return_value=(([1, 2], [-100, 2]),)):
                with patch("tools.local_training.lora_runner._train_model", side_effect=fake_training):
                    train_local_adapter(self.manifest, self.model, self.output,
                                        approval=plan.weight_update_approval, execute=True)
        marker = json.loads((self.output / "VERA_ADAPTER_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "TRAINED_ADAPTER_UNQUALIFIED_UNEVALUATED_NOT_ACTIVATED")
        self.assertEqual(marker["adapter_artifact_sha256"]["adapter_model.safetensors"],
                         hashlib.sha256(b"synthetic-adapter-not-real-weights").hexdigest())
        self.assertEqual(marker["optimizer_steps_requested"], 1)
        self.assertEqual(marker["recipe_sha256"], plan.recipe_sha256)

    def test_matching_two_step_approval_reaches_only_two_bounded_optimizer_steps(self):
        plan = plan_local_training(self.manifest, self.model, self.output, steps=2)

        def fake_training(_model, _encoded, output, steps):
            self.assertEqual(steps, 2)
            (output / "adapter_model.safetensors").write_bytes(b"two-step-synthetic-adapter")
            (output / "adapter_config.json").write_bytes(b"{}")
            return {"optimizer_steps": steps}

        with patch("tools.local_training.lora_runner._require_accelerator", return_value={}):
            with patch("tools.local_training.lora_runner._encode_training_rows", return_value=(([1, 2], [-100, 2]),)):
                with patch("tools.local_training.lora_runner._train_model", side_effect=fake_training):
                    train_local_adapter(self.manifest, self.model, self.output,
                                        approval=plan.weight_update_approval, execute=True, steps=2)
        marker = json.loads((self.output / "VERA_ADAPTER_STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["optimizer_steps_requested"], 2)
        self.assertEqual(marker["training"]["optimizer_steps"], 2)

    def test_alignment_failure_is_prevalidated_without_creating_output(self):
        plan = plan_local_training(self.manifest, self.model, self.output)
        with patch.dict(os.environ, {}, clear=True):
            with patch("tools.local_training.lora_runner._require_accelerator", return_value={}):
                with patch("tools.local_training.lora_runner._encode_training_rows", side_effect=ValueError("chat-template label alignment")):
                    with patch("tools.local_training.lora_runner._train_model", side_effect=AssertionError("gradient step")):
                        with self.assertRaisesRegex(ValueError, "chat-template label alignment"):
                            train_local_adapter(self.manifest, self.model, self.output,
                                                approval=plan.weight_update_approval, execute=True)
            self.assertEqual(os.environ.get("HF_HUB_OFFLINE"), "1")
            self.assertEqual(os.environ.get("HF_HUB_DISABLE_TELEMETRY"), "1")
            self.assertEqual(os.environ.get("TRANSFORMERS_OFFLINE"), "1")
        self.assertFalse(self.output.exists())

    def test_rejects_gguf_as_trainable_model(self):
        (self.model / "model.safetensors").unlink()
        (self.model / "model.gguf").write_bytes(b"quantized-not-trainable-fixture")
        self._bind_snapshot()
        with self.assertRaisesRegex(ValueError, "safetensors|GGUF"):
            plan_local_training(self.manifest, self.model, self.output)


@unittest.skipUnless(os.name == "nt", "native Windows ACL hold")
class WindowsLocalLoRAHoldTests(unittest.TestCase):
    def test_windows_refuses_before_private_io(self):
        with patch.object(Path, "is_file", side_effect=AssertionError("probed private file")):
            with self.assertRaisesRegex(ValueError, "Windows private ACL qualification"):
                plan_local_training(Path("C:/private/manifest.json"), Path("C:/model"), Path("C:/adapter"))


if __name__ == "__main__":
    unittest.main()
