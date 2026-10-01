from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random

import numpy as np

from .checkpoint import save_checkpoint
from .model import ModelConfig, NativeTransformer
from .tokenizer import BPETokenizer


@dataclass(frozen=True, slots=True)
class TrainingArtifacts:
    checkpoint_path: Path
    tokenizer_path: Path
    final_loss: float
    steps: int


def train_text_model(
    text: str,
    output_dir: str | Path,
    *,
    vocab_size: int = 512,
    context_length: int = 128,
    n_layer: int = 2,
    n_head: int = 2,
    n_embd: int = 64,
    steps: int = 100,
    batch_size: int = 8,
    learning_rate: float = 3e-4,
    seed: int = 0,
) -> TrainingArtifacts:
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError as exc:
        raise RuntimeError(
            "training requires PyTorch; install the "
            "vera-mono model-training extra"
        ) from exc

    if type(text) is not str or not text.strip():
        raise ValueError(
            "training text must be non-empty"
        )
    if type(steps) is not int or steps <= 0:
        raise ValueError(
            "steps must be a positive integer"
        )
    if (
        type(batch_size) is not int
        or batch_size <= 0
    ):
        raise ValueError(
            "batch_size must be a positive integer"
        )
    if learning_rate <= 0:
        raise ValueError(
            "learning_rate must be positive"
        )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tokenizer = BPETokenizer.train(
        text,
        vocab_size=vocab_size,
    )
    token_ids = tokenizer.encode(text)
    if len(token_ids) < context_length + 2:
        raise ValueError(
            "training corpus is too short "
            "for context_length"
        )

    config = ModelConfig(
        vocab_size=tokenizer.vocab_size,
        context_length=context_length,
        n_layer=n_layer,
        n_head=n_head,
        n_embd=n_embd,
    )

    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)

    class Block(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.ln1 = nn.LayerNorm(
                n_embd,
                eps=config.layer_norm_epsilon,
            )
            self.qkv = nn.Linear(
                n_embd,
                3 * n_embd,
                bias=False,
            )
            self.proj = nn.Linear(
                n_embd,
                n_embd,
                bias=False,
            )
            self.ln2 = nn.LayerNorm(
                n_embd,
                eps=config.layer_norm_epsilon,
            )
            self.fc = nn.Linear(
                n_embd,
                config.mlp_ratio * n_embd,
                bias=False,
            )
            self.mlp_proj = nn.Linear(
                config.mlp_ratio * n_embd,
                n_embd,
                bias=False,
            )

        def forward(self, x):
            b, t, c = x.shape
            a = self.ln1(x)
            q, k, v = self.qkv(a).chunk(
                3,
                dim=-1,
            )
            hd = c // n_head
            q = q.view(
                b, t, n_head, hd
            ).transpose(1, 2)
            k = k.view(
                b, t, n_head, hd
            ).transpose(1, 2)
            v = v.view(
                b, t, n_head, hd
            ).transpose(1, 2)
            scores = (
                q @ k.transpose(-2, -1)
            ) / (hd**0.5)
            mask = torch.triu(
                torch.ones(
                    t,
                    t,
                    dtype=torch.bool,
                    device=x.device,
                ),
                diagonal=1,
            )
            scores = scores.masked_fill(
                mask,
                float("-inf"),
            )
            y = torch.softmax(
                scores,
                dim=-1,
            ) @ v
            y = (
                y.transpose(1, 2)
                .contiguous()
                .view(b, t, c)
            )
            x = x + self.proj(y)
            m = self.ln2(x)
            m = F.gelu(
                self.fc(m),
                approximate="tanh",
            )
            return x + self.mlp_proj(m)

    class TorchModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.wte = nn.Embedding(
                config.vocab_size,
                n_embd,
            )
            self.wpe = nn.Embedding(
                context_length,
                n_embd,
            )
            self.blocks = nn.ModuleList(
                [
                    Block()
                    for _ in range(n_layer)
                ]
            )
            self.ln_f = nn.LayerNorm(
                n_embd,
                eps=config.layer_norm_epsilon,
            )
            self.apply(self._init_weights)

        @staticmethod
        def _init_weights(module) -> None:
            if isinstance(module, nn.Linear):
                nn.init.normal_(
                    module.weight,
                    mean=0.0,
                    std=0.02,
                )
            elif isinstance(
                module,
                nn.Embedding,
            ):
                nn.init.normal_(
                    module.weight,
                    mean=0.0,
                    std=0.02,
                )

        def forward(self, idx):
            _, t = idx.shape
            pos = torch.arange(
                t,
                device=idx.device,
            )
            x = (
                self.wte(idx)
                + self.wpe(pos)[None, :, :]
            )
            for block in self.blocks:
                x = block(x)
            x = self.ln_f(x)
            return x @ self.wte.weight.T

    model = TorchModel()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
    )
    data = torch.tensor(
        token_ids,
        dtype=torch.long,
    )
    max_start = (
        len(token_ids)
        - context_length
        - 1
    )
    generator = torch.Generator().manual_seed(
        seed
    )

    final_loss = 0.0
    model.train()
    for _ in range(steps):
        starts = torch.randint(
            0,
            max_start + 1,
            (batch_size,),
            generator=generator,
        )
        x = torch.stack(
            [
                data[
                    s : s + context_length
                ]
                for s in starts.tolist()
            ]
        )
        y = torch.stack(
            [
                data[
                    s + 1 :
                    s + context_length + 1
                ]
                for s in starts.tolist()
            ]
        )
        logits = model(x)
        loss = F.cross_entropy(
            logits.reshape(
                -1,
                config.vocab_size,
            ),
            y.reshape(-1),
        )
        optimizer.zero_grad(
            set_to_none=True
        )
        loss.backward()
        optimizer.step()
        final_loss = float(
            loss.detach().item()
        )

    weights: dict[str, np.ndarray] = {
        "wte": model.wte.weight.detach()
        .cpu()
        .numpy()
        .astype(np.float32),
        "wpe": model.wpe.weight.detach()
        .cpu()
        .numpy()
        .astype(np.float32),
        "ln_f.weight": model.ln_f.weight
        .detach()
        .cpu()
        .numpy()
        .astype(np.float32),
        "ln_f.bias": model.ln_f.bias
        .detach()
        .cpu()
        .numpy()
        .astype(np.float32),
    }
    for i, block in enumerate(model.blocks):
        p = f"blocks.{i}"
        weights[f"{p}.ln1.weight"] = (
            block.ln1.weight.detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        weights[f"{p}.ln1.bias"] = (
            block.ln1.bias.detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        weights[f"{p}.attn.qkv.weight"] = (
            block.qkv.weight.detach()
            .cpu()
            .numpy()
            .T.astype(np.float32)
        )
        weights[f"{p}.attn.proj.weight"] = (
            block.proj.weight.detach()
            .cpu()
            .numpy()
            .T.astype(np.float32)
        )
        weights[f"{p}.ln2.weight"] = (
            block.ln2.weight.detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        weights[f"{p}.ln2.bias"] = (
            block.ln2.bias.detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )
        weights[f"{p}.mlp.fc.weight"] = (
            block.fc.weight.detach()
            .cpu()
            .numpy()
            .T.astype(np.float32)
        )
        weights[f"{p}.mlp.proj.weight"] = (
            block.mlp_proj.weight.detach()
            .cpu()
            .numpy()
            .T.astype(np.float32)
        )

    native = NativeTransformer(
        config,
        weights,
    )
    tokenizer_path = out / "tokenizer.json"
    checkpoint_path = out / "model.npz"
    tokenizer.save(tokenizer_path)
    save_checkpoint(
        checkpoint_path,
        native,
        training={
            "steps": steps,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "seed": seed,
            "corpus_tokens": len(token_ids),
            "final_loss": final_loss,
        },
    )
    return TrainingArtifacts(
        checkpoint_path,
        tokenizer_path,
        final_loss,
        steps,
    )
