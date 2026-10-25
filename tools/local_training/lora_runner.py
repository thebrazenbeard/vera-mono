"""Offline-only, explicitly approved local LoRA for pinned small causal language models.

Qwen3.5 multimodal and GGUF reconversion inputs are NOT qualified here.
No heavyweight training dependency loads during source preflight.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from .adapter_prep import _load_snapshot, _prepare, _reject_git_checkout, _require_private_filesystem

_SUPPORTED_BASE = {"Qwen/Qwen3-0.6B": "qwen3"}
_TRAINING_RECIPE = {
    "revision": "qwen3-0.6b-causal-bf16-lora-v1",
    "precision": "bf16",
    "max_sequence_tokens": 1024,
    "batch_size": 1,
    "sample_order": "cyclic-training-split-v1",
    "lora_r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.0,
    "lora_target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "optimizer": "AdamW",
    "learning_rate": 1e-4,
    "learning_schedule": "constant",
}
_TRAINING_RECIPE_SHA256 = hashlib.sha256(
    json.dumps(_TRAINING_RECIPE, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


@dataclass(frozen=True)
class LocalTrainingPlan:
    status: str
    manifest_sha256: str
    base_binding_sha256: str
    model_snapshot_sha256: str
    train_examples: int
    heldout_examples: int
    optimizer_steps: int
    recipe_sha256: str
    weight_update_approval: str


def _model_snapshot(model_dir: Path, base: dict) -> str:
    if not model_dir.is_absolute():
        raise ValueError("model snapshot path must be absolute")
    _require_private_filesystem(model_dir, "model snapshot")
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise ValueError("model snapshot must be an absolute existing non-symlink directory")
    _reject_git_checkout(model_dir, "model snapshot")
    if os.name == "posix" and stat.S_IMODE(model_dir.stat().st_mode) & 0o077:
        raise ValueError("model snapshot directory requires private 0700 permissions")
    binding = json.loads(_load_snapshot(model_dir / "VERA_SOURCE.json", "model source binding", 1024 * 1024))
    if not isinstance(binding, dict) or set(binding) != {
        "schema_version", "hf_repo", "revision_sha", "tokenizer_revision_sha",
        "chat_template_sha256", "files_sha256",
    } or binding["schema_version"] != 1:
        raise ValueError("model source binding schema invalid")
    for field in ("hf_repo", "revision_sha", "tokenizer_revision_sha", "chat_template_sha256"):
        if binding[field] != base[field]:
            raise ValueError(f"model source binding mismatch: {field}")
    files = binding["files_sha256"]
    if not isinstance(files, dict) or not files or any(
        not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.-]+", name) is None
        or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for name, digest in files.items()
    ):
        raise ValueError("model source binding file digests invalid")
    if not {"config.json", "tokenizer.json", "tokenizer_config.json"}.issubset(files):
        raise ValueError("model source lacks tokenizer and config files")
    if not any(re.fullmatch(r"model(?:-\d{5}-of-\d{5})?\.safetensors", name) for name in files):
        raise ValueError("trainable base requires full-model safetensors; GGUF/adapter is not a base")
    if {p.name for p in model_dir.iterdir()} != set(files) | {"VERA_SOURCE.json"}:
        raise ValueError("model snapshot has unlisted or missing files")
    for name in sorted(files):
        path = model_dir / name
        _require_private_filesystem(path, "model file")
        if path.is_symlink() or not path.is_file():
            raise ValueError("model file cannot be a symlink/non-regular file")
        if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("model file requires private 0600 permissions")
        hashed = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(4 * 1024 * 1024):
                hashed.update(block)
        if hashed.hexdigest() != files[name]:
            raise ValueError(f"model snapshot digest mismatch: {name}")
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    expected = _SUPPORTED_BASE.get(base["hf_repo"])
    if expected is None or not isinstance(config, dict) or config.get("model_type") != expected:
        raise ValueError("unsupported multimodal/unqualified model architecture; Qwen3.5 needs separate qualification")
    config = json.loads((model_dir / "tokenizer_config.json").read_text(encoding="utf-8"))
    template = config.get("chat_template") if isinstance(config, dict) else None
    if not isinstance(template, str) or hashlib.sha256(template.encode()).hexdigest() != base["chat_template_sha256"]:
        raise ValueError("tokenizer chat template digest mismatch")
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _preflight(manifest_path: Path, model_dir: Path, output_dir: Path, *, steps: int = 1):
    if type(steps) is not int or not (1 <= steps <= 32):
        raise ValueError("steps must be within 1..32")
    prepared = _prepare(Path(manifest_path))  # Native Windows fails before private reads.
    manifest = json.loads(_load_snapshot(Path(manifest_path), "manifest", 65536))
    snapshot_sha = _model_snapshot(Path(model_dir), manifest["base_model"])
    output = Path(output_dir)
    if not output.is_absolute() or output.is_symlink() or output.exists():
        raise ValueError("training output requires a new absolute non-symlink directory")
    _reject_git_checkout(output.parent, "training output")
    _require_private_filesystem(output.parent, "training output parent")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("training output parent must exist and be non-symlink")
    if os.name == "posix" and stat.S_IMODE(output.parent.stat().st_mode) & 0o077:
        raise ValueError("training output parent requires owner-only permissions")
    binding = json.dumps({
        "manifest": prepared.plan.manifest_sha256,
        "base": prepared.plan.base_model_binding_sha256,
        "snapshot": snapshot_sha,
        "output": str(output),
        "optimizer_steps": steps,
        "recipe_sha256": _TRAINING_RECIPE_SHA256,
    }, sort_keys=True, separators=(",", ":"))
    return LocalTrainingPlan(
        status="PREFLIGHT_ONLY_NOT_TRAINED",
        manifest_sha256=prepared.plan.manifest_sha256,
        base_binding_sha256=prepared.plan.base_model_binding_sha256,
        model_snapshot_sha256=snapshot_sha,
        train_examples=prepared.plan.training_count,
        heldout_examples=prepared.plan.evaluation_count,
        optimizer_steps=steps,
        recipe_sha256=_TRAINING_RECIPE_SHA256,
        weight_update_approval="TRAIN_LOCAL_LORA:" + hashlib.sha256(binding.encode()).hexdigest(),
    ), prepared


def plan_local_training(manifest_path: Path, model_dir: Path, output_dir: Path, *, steps: int = 1) -> LocalTrainingPlan:
    """Digest-check all local input bytes; do not import torch or create output."""
    return _preflight(manifest_path, model_dir, output_dir, steps=steps)[0]


def _require_accelerator() -> dict:
    import torch

    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ValueError("CUDA GPU with BF16 support required; no CPU training fallback")
    free, total = torch.cuda.mem_get_info()
    if free < 3 * 1024**3:
        raise ValueError("at least 3 GiB actually free VRAM required even for tiny-model experiment")
    props = torch.cuda.get_device_properties(torch.cuda.current_device())
    return {"gpu_name": props.name, "vram_total": total, "vram_free": free,
            "torch_version": str(torch.__version__)}


def _lock_offline_environment() -> None:
    # Hugging Face variables must be set before the first hub import.
    if any(name == "huggingface_hub" or name.startswith("huggingface_hub.") for name in sys.modules):
        raise ValueError("huggingface_hub already loaded before offline lock")
    for name, value in {
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "WANDB_DISABLED": "true",
    }.items():
        os.environ[name] = value


def _encode_training_rows(model_dir: Path, rows: tuple[dict, ...]) -> tuple[tuple[list[int], list[int]], ...]:
    """Validate ALL examples and chat labels before weight update or output creation."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)
    encoded = []
    for row in rows:
        messages = row["messages"]
        prompt = tokenizer.apply_chat_template([messages[0]], tokenize=False, add_generation_prompt=True)
        full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        prefix_ids = tokenizer.encode(prompt, add_special_tokens=False)
        ids = tokenizer.encode(full, add_special_tokens=False)
        if len(ids) > _TRAINING_RECIPE["max_sequence_tokens"] or len(prefix_ids) >= len(ids) or ids[:len(prefix_ids)] != prefix_ids:
            raise ValueError("chat-template label alignment/length has not qualified")
        encoded.append((ids, [-100] * len(prefix_ids) + ids[len(prefix_ids):]))
    return tuple(encoded)


def _train_model(model_dir: Path, encoded: tuple[tuple[list[int], list[int]], ...], output: Path, steps: int) -> dict:
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForCausalLM

    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.bfloat16,
    ).to("cuda")
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.CAUSAL_LM, r=_TRAINING_RECIPE["lora_r"],
        lora_alpha=_TRAINING_RECIPE["lora_alpha"],
        lora_dropout=_TRAINING_RECIPE["lora_dropout"],
        target_modules=_TRAINING_RECIPE["lora_target_modules"],
    ))
    model.train()
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=_TRAINING_RECIPE["learning_rate"],
    )
    done = 0
    for step in range(steps):
        ids, labels = encoded[step % len(encoded)]
        inputs = torch.tensor([ids], device="cuda", dtype=torch.long)
        targets = torch.tensor([labels], device="cuda", dtype=torch.long)
        optimizer.zero_grad(set_to_none=True)
        loss = model(input_ids=inputs, labels=targets).loss
        if not torch.isfinite(loss):
            raise ValueError("non-finite loss")
        loss.backward()
        optimizer.step()
        done += 1
    model.save_pretrained(str(output), safe_serialization=True)
    return {"optimizer_steps": done,
            "transformers_version": str(__import__("transformers").__version__),
            "peft_version": str(__import__("peft").__version__)}


def train_local_adapter(manifest_path: Path, model_dir: Path, output_dir: Path,
                        *, approval: str, execute: bool, steps: int = 1) -> LocalTrainingPlan:
    """Separate exact-input approval before GPU access or any adapter artifact."""
    plan, prepared = _preflight(manifest_path, model_dir, output_dir, steps=steps)
    if execute is not True or approval != plan.weight_update_approval:
        raise ValueError("exact separate weight update approval and --execute required")
    _lock_offline_environment()
    device = _require_accelerator()
    encoded = _encode_training_rows(Path(model_dir), prepared.train)
    # Catch model-directory mutation between initial preflight and encoding.
    after, _ = _preflight(manifest_path, model_dir, output_dir, steps=steps)
    if after != plan:
        raise ValueError("model/data binding changed before training; replan required")
    output = Path(output_dir)
    output.mkdir(mode=0o700)
    if os.name == "posix":
        os.chmod(output, 0o700)
    previous_umask = os.umask(0o077)
    try:
        training = _train_model(Path(model_dir), encoded, output, steps)
        if not (output / "adapter_model.safetensors").is_file() or not (output / "adapter_config.json").is_file():
            raise ValueError("adapter files absent after weight-update call; refuse trained marker")
        artifacts = {}
        for name in ("adapter_model.safetensors", "adapter_config.json"):
            digest = hashlib.sha256()
            with (output / name).open("rb") as handle:
                while block := handle.read(4 * 1024 * 1024):
                    digest.update(block)
            artifacts[name] = digest.hexdigest()
        (output / "VERA_ADAPTER_STATUS.json").write_text(json.dumps({
            "status": "TRAINED_ADAPTER_UNQUALIFIED_UNEVALUATED_NOT_ACTIVATED",
            "manifest_sha256": plan.manifest_sha256,
            "base_binding_sha256": plan.base_binding_sha256,
            "snapshot_sha256": plan.model_snapshot_sha256,
            "train_examples": plan.train_examples,
            "heldout_examples_excluded": plan.heldout_examples,
            "optimizer_steps_requested": plan.optimizer_steps,
            "recipe_sha256": plan.recipe_sha256,
            "accelerator": device, "training": training,
            "adapter_artifact_sha256": artifacts,
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    finally:
        os.umask(previous_umask)
    return plan
