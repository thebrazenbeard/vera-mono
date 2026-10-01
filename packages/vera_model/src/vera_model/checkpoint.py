from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .model import ModelConfig, NativeTransformer


_SCHEMA = "VERA_NATIVE_TRANSFORMER_CHECKPOINT_V1"


def save_checkpoint(
    path: str | Path,
    model: NativeTransformer,
    *,
    training: dict[str, object] | None = None,
) -> None:
    metadata = {
        "schema": _SCHEMA,
        "config": model.config.as_dict(),
        "training": training or {},
    }
    arrays = {
        name: value.astype(np.float32, copy=False)
        for name, value in model.weights.items()
    }
    arrays["__metadata__"] = np.asarray(
        json.dumps(
            metadata,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    with Path(path).open("wb") as fh:
        np.savez_compressed(fh, **arrays)


def load_checkpoint(path: str | Path) -> NativeTransformer:
    with np.load(Path(path), allow_pickle=False) as archive:
        if "__metadata__" not in archive.files:
            raise ValueError("checkpoint metadata is missing")
        metadata = json.loads(
            str(archive["__metadata__"].item())
        )
        if metadata.get("schema") != _SCHEMA:
            raise ValueError("unsupported checkpoint schema")
        cfg = ModelConfig(**metadata["config"])
        weights = {
            name: archive[name].copy()
            for name in archive.files
            if name != "__metadata__"
        }
    return NativeTransformer(cfg, weights)


def inspect_checkpoint(
    path: str | Path,
) -> dict[str, object]:
    with np.load(Path(path), allow_pickle=False) as archive:
        metadata = json.loads(
            str(archive["__metadata__"].item())
        )
        parameter_count = sum(
            int(np.prod(archive[name].shape))
            for name in archive.files
            if name != "__metadata__"
        )
    return {
        **metadata,
        "parameter_count": parameter_count,
    }
