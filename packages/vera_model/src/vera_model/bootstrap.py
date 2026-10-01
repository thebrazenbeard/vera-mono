from __future__ import annotations

from importlib.resources import as_file, files

from .checkpoint import load_checkpoint
from .model import NativeTransformer
from .tokenizer import BPETokenizer


def load_bootstrap(
) -> tuple[NativeTransformer, BPETokenizer]:
    root = files("vera_model").joinpath(
        "resources/bootstrap"
    )
    with as_file(root.joinpath("model.npz")) as model_path:
        model = load_checkpoint(model_path)
    with as_file(
        root.joinpath("tokenizer.json")
    ) as tokenizer_path:
        tokenizer = BPETokenizer.load(tokenizer_path)
    if (
        model.config.vocab_size
        != tokenizer.vocab_size
    ):
        raise RuntimeError(
            "packaged bootstrap tokenizer/checkpoint "
            "vocabulary mismatch"
        )
    return model, tokenizer
