from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping

import numpy as np


@dataclass(frozen=True, slots=True)
class ModelConfig:
    vocab_size: int
    context_length: int
    n_layer: int
    n_head: int
    n_embd: int
    mlp_ratio: int = 4
    layer_norm_epsilon: float = 1e-5

    def __post_init__(self) -> None:
        for name in (
            "vocab_size",
            "context_length",
            "n_layer",
            "n_head",
            "n_embd",
            "mlp_ratio",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.n_embd % self.n_head:
            raise ValueError("n_embd must be divisible by n_head")
        if self.vocab_size < 256:
            raise ValueError("vocab_size must be >= 256")
        if self.layer_norm_epsilon <= 0:
            raise ValueError("layer_norm_epsilon must be positive")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _layer_norm(
    x: np.ndarray,
    weight: np.ndarray,
    bias: np.ndarray,
    eps: float,
) -> np.ndarray:
    mean = x.mean(axis=-1, keepdims=True)
    var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(var + eps) * weight + bias


def _gelu_tanh(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (
        1.0
        + np.tanh(
            math.sqrt(2.0 / math.pi) * (x + 0.044715 * x**3)
        )
    )


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    shifted = x - np.max(x, axis=axis, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=axis, keepdims=True)


class NativeTransformer:
    """Small dependency-light decoder-only transformer inference runtime.

    The architecture is intentionally conventional: learned token/position
    embeddings, pre-norm causal self-attention, GELU MLP blocks, residual
    connections, final LayerNorm, and a token-embedding-tied language head.
    """

    def __init__(
        self,
        config: ModelConfig,
        weights: Mapping[str, np.ndarray],
    ):
        self.config = config
        self.weights = {
            name: np.asarray(value, dtype=np.float32)
            for name, value in weights.items()
        }
        self._validate_weights()

    @classmethod
    def random(
        cls,
        config: ModelConfig,
        *,
        seed: int = 0,
        std: float = 0.02,
    ) -> "NativeTransformer":
        rng = np.random.default_rng(seed)
        d = config.n_embd
        m = d * config.mlp_ratio
        weights: dict[str, np.ndarray] = {
            "wte": rng.normal(
                0.0, std, (config.vocab_size, d)
            ).astype(np.float32),
            "wpe": rng.normal(
                0.0, std, (config.context_length, d)
            ).astype(np.float32),
            "ln_f.weight": np.ones((d,), dtype=np.float32),
            "ln_f.bias": np.zeros((d,), dtype=np.float32),
        }
        for i in range(config.n_layer):
            p = f"blocks.{i}"
            weights[f"{p}.ln1.weight"] = np.ones((d,), dtype=np.float32)
            weights[f"{p}.ln1.bias"] = np.zeros((d,), dtype=np.float32)
            weights[f"{p}.attn.qkv.weight"] = rng.normal(
                0.0, std, (d, 3 * d)
            ).astype(np.float32)
            weights[f"{p}.attn.proj.weight"] = rng.normal(
                0.0,
                std / math.sqrt(2 * config.n_layer),
                (d, d),
            ).astype(np.float32)
            weights[f"{p}.ln2.weight"] = np.ones((d,), dtype=np.float32)
            weights[f"{p}.ln2.bias"] = np.zeros((d,), dtype=np.float32)
            weights[f"{p}.mlp.fc.weight"] = rng.normal(
                0.0, std, (d, m)
            ).astype(np.float32)
            weights[f"{p}.mlp.proj.weight"] = rng.normal(
                0.0,
                std / math.sqrt(2 * config.n_layer),
                (m, d),
            ).astype(np.float32)
        return cls(config, weights)

    def _validate_weights(self) -> None:
        d = self.config.n_embd
        m = d * self.config.mlp_ratio
        expected = {
            "wte": (self.config.vocab_size, d),
            "wpe": (self.config.context_length, d),
            "ln_f.weight": (d,),
            "ln_f.bias": (d,),
        }
        for i in range(self.config.n_layer):
            p = f"blocks.{i}"
            expected.update(
                {
                    f"{p}.ln1.weight": (d,),
                    f"{p}.ln1.bias": (d,),
                    f"{p}.attn.qkv.weight": (d, 3 * d),
                    f"{p}.attn.proj.weight": (d, d),
                    f"{p}.ln2.weight": (d,),
                    f"{p}.ln2.bias": (d,),
                    f"{p}.mlp.fc.weight": (d, m),
                    f"{p}.mlp.proj.weight": (m, d),
                }
            )
        missing = set(expected) - set(self.weights)
        extra = set(self.weights) - set(expected)
        if missing or extra:
            raise ValueError(
                "checkpoint weight keys mismatch; "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        for name, shape in expected.items():
            if self.weights[name].shape != shape:
                raise ValueError(
                    f"weight {name} has shape "
                    f"{self.weights[name].shape}, expected {shape}"
                )

    def forward(self, token_ids: list[int]) -> np.ndarray:
        if not token_ids:
            raise ValueError("token_ids must be non-empty")
        if len(token_ids) > self.config.context_length:
            token_ids = token_ids[-self.config.context_length :]
        if any(
            type(t) is not int
            or not 0 <= t < self.config.vocab_size
            for t in token_ids
        ):
            raise ValueError("token_ids contain an out-of-range token")

        t = len(token_ids)
        d = self.config.n_embd
        h = self.config.n_head
        hd = d // h
        idx = np.asarray(token_ids, dtype=np.int64)
        x = self.weights["wte"][idx] + self.weights["wpe"][:t]
        causal = np.triu(np.ones((t, t), dtype=bool), k=1)

        for i in range(self.config.n_layer):
            p = f"blocks.{i}"
            a = _layer_norm(
                x,
                self.weights[f"{p}.ln1.weight"],
                self.weights[f"{p}.ln1.bias"],
                self.config.layer_norm_epsilon,
            )
            qkv = a @ self.weights[f"{p}.attn.qkv.weight"]
            q, k, v = np.split(qkv, 3, axis=-1)
            q = q.reshape(t, h, hd).transpose(1, 0, 2)
            k = k.reshape(t, h, hd).transpose(1, 0, 2)
            v = v.reshape(t, h, hd).transpose(1, 0, 2)
            scores = (q @ k.transpose(0, 2, 1)) / math.sqrt(hd)
            scores[:, causal] = -1e30
            probs = _softmax(scores, axis=-1)
            attn = (
                (probs @ v)
                .transpose(1, 0, 2)
                .reshape(t, d)
            )
            x = x + attn @ self.weights[f"{p}.attn.proj.weight"]

            m_in = _layer_norm(
                x,
                self.weights[f"{p}.ln2.weight"],
                self.weights[f"{p}.ln2.bias"],
                self.config.layer_norm_epsilon,
            )
            hidden = _gelu_tanh(
                m_in @ self.weights[f"{p}.mlp.fc.weight"]
            )
            x = x + hidden @ self.weights[f"{p}.mlp.proj.weight"]

        x = _layer_norm(
            x,
            self.weights["ln_f.weight"],
            self.weights["ln_f.bias"],
            self.config.layer_norm_epsilon,
        )
        return x @ self.weights["wte"].T

    def next_token_logits(self, token_ids: list[int]) -> np.ndarray:
        return self.forward(token_ids)[-1]

    def generate(
        self,
        token_ids: list[int],
        *,
        max_new_tokens: int,
        temperature: float = 0.8,
        top_k: int | None = 50,
        seed: int | None = None,
    ) -> list[int]:
        if type(max_new_tokens) is not int or max_new_tokens < 0:
            raise ValueError(
                "max_new_tokens must be a non-negative integer"
            )
        if temperature < 0:
            raise ValueError("temperature must be >= 0")
        if top_k is not None and (
            type(top_k) is not int or top_k <= 0
        ):
            raise ValueError(
                "top_k must be None or a positive integer"
            )

        out = list(token_ids)
        rng = np.random.default_rng(seed)
        for _ in range(max_new_tokens):
            logits = self.next_token_logits(out)
            if temperature == 0:
                token = int(np.argmax(logits))
            else:
                scaled = logits / float(temperature)
                if top_k is not None and top_k < scaled.size:
                    keep = np.argpartition(
                        scaled, -top_k
                    )[-top_k:]
                    probs = _softmax(scaled[keep])
                    token = int(rng.choice(keep, p=probs))
                else:
                    probs = _softmax(scaled)
                    token = int(
                        rng.choice(
                            np.arange(scaled.size),
                            p=probs,
                        )
                    )
            out.append(token)
        return out
