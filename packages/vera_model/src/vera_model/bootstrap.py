from __future__ import annotations

import base64
from importlib.resources import files

from .checkpoint import load_checkpoint_bytes
from .model import NativeTransformer
from .tokenizer import BPETokenizer


def load_bootstrap() -> tuple[NativeTransformer, BPETokenizer]:
    root = files("vera_model").joinpath("resources/bootstrap")
    chunks = []
    index = 0
    while True:
        ref = root.joinpath(f"model.npz.b64.{index:02d}")
        if not ref.is_file():
            break
        chunks.append(ref.read_text(encoding="ascii"))
        index += 1
    if not chunks:
        raise RuntimeError("packaged Vera bootstrap checkpoint is missing")
    model = load_checkpoint_bytes(base64.b64decode("".join(chunks), validate=True))
    tokenizer_payload = root.joinpath("tokenizer.json").read_text(encoding="utf-8")
    import json
    data = json.loads(tokenizer_payload)
    if data.get("schema") != "VERA_NATIVE_BPE_TOKENIZER_V1":
        raise RuntimeError("packaged Vera bootstrap tokenizer schema is invalid")
    tokenizer = BPETokenizer(tuple((int(a), int(b)) for a, b in data.get("merges", [])))
    if data.get("vocab_size") != tokenizer.vocab_size:
        raise RuntimeError("packaged Vera bootstrap tokenizer vocabulary is invalid")
    if model.config.vocab_size != tokenizer.vocab_size:
        raise RuntimeError("packaged bootstrap tokenizer/checkpoint vocabulary mismatch")
    return model, tokenizer
