from pathlib import Path

import numpy as np

from vera_model import BPETokenizer, ModelConfig, NativeTransformer
from vera_model.checkpoint import load_checkpoint, save_checkpoint


def test_bpe_tokenizer_roundtrip_and_serialization(tmp_path: Path):
    tok = BPETokenizer.train("hello hello vera vera", vocab_size=264)
    ids = tok.encode("hello vera")
    assert tok.decode(ids) == "hello vera"
    path = tmp_path / "tokenizer.json"
    tok.save(path)
    assert BPETokenizer.load(path).decode(ids) == "hello vera"


def test_native_transformer_checkpoint_and_generation(tmp_path: Path):
    tok = BPETokenizer.train("vera mono vera mono", vocab_size=260)
    cfg = ModelConfig(
        vocab_size=tok.vocab_size,
        context_length=16,
        n_layer=1,
        n_head=1,
        n_embd=8,
    )
    model = NativeTransformer.random(cfg, seed=7)
    prompt = tok.encode("vera")
    logits = model.next_token_logits(prompt)
    assert logits.shape == (tok.vocab_size,)
    checkpoint = tmp_path / "model.npz"
    save_checkpoint(checkpoint, model)
    loaded = load_checkpoint(checkpoint)
    np.testing.assert_allclose(
        loaded.next_token_logits(prompt),
        logits,
        rtol=0,
        atol=0,
    )
    out = loaded.generate(prompt, max_new_tokens=3, temperature=0)
    assert len(out) == len(prompt) + 3


def test_torch_training_exports_loadable_native_checkpoint(tmp_path: Path):
    import pytest
    pytest.importorskip("torch")
    from vera_model.training import train_text_model

    artifacts = train_text_model(
        "User: hello\nVera: hello\n" * 20,
        tmp_path,
        vocab_size=260,
        context_length=16,
        n_layer=1,
        n_head=1,
        n_embd=8,
        steps=3,
        batch_size=2,
        learning_rate=1e-2,
        seed=11,
    )
    model = load_checkpoint(artifacts.checkpoint_path)
    tokenizer = BPETokenizer.load(artifacts.tokenizer_path)
    assert model.config.vocab_size == tokenizer.vocab_size
    assert artifacts.final_loss > 0


def test_native_chat_session_uses_checkpoint_not_external_backend():
    from vera_model.session import NativeChatSession

    tok = BPETokenizer.train(
        "<|user|>hello<|assistant|>hi",
        vocab_size=260,
    )
    cfg = ModelConfig(
        vocab_size=tok.vocab_size,
        context_length=32,
        n_layer=1,
        n_head=1,
        n_embd=8,
    )
    model = NativeTransformer.random(cfg, seed=3)
    session = NativeChatSession(
        model=model,
        tokenizer=tok,
        system_prompt="Vera",
    )
    reply = session.ask("hello", max_new_tokens=2, temperature=0)
    assert isinstance(reply, str)
    assert [turn.role for turn in session.history] == ["user", "assistant"]


def test_packaged_bootstrap_loads_and_generates_tokens():
    from vera_model.bootstrap import load_bootstrap

    model, tokenizer = load_bootstrap()
    assert model.config.vocab_size == tokenizer.vocab_size == 264
    assert model.config.n_layer == 1
    assert model.config.n_embd == 2
    prompt = tokenizer.encode("Who are you?")
    generated = model.generate(prompt, max_new_tokens=2, temperature=0)
    assert len(generated) == len(prompt) + 2
