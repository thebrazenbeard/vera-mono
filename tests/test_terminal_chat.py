from __future__ import annotations

from vera_core.terminal_chat import TerminalChatSession, build_terminal_system_prompt
from vera_model import BPETokenizer, ModelConfig, NativeTransformer


def _tiny_artifacts():
    tokenizer = BPETokenizer.train(
        "<|user|> hello <|assistant|> Vera",
        vocab_size=260,
    )
    config = ModelConfig(
        vocab_size=tokenizer.vocab_size,
        context_length=32,
        n_layer=1,
        n_head=1,
        n_embd=8,
    )
    return NativeTransformer.random(config, seed=9), tokenizer


def test_source_only_prompt_loads_governed_identity_and_behavior():
    prompt = build_terminal_system_prompt()
    assert "terminal_mode=SOURCE_ONLY" in prompt
    assert "VERA_PROJECT_IDENTITY_V1" in prompt
    assert '"candor"' in prompt
    assert "Source presence does not prove installation" in prompt


def test_runtime_bound_prompt_preserves_evidence_boundary_and_privacy():
    prompt = build_terminal_system_prompt(
        runtime_context={
            "status": "ACCEPTED_CURRENT",
            "accepted_runtime_id": "runtime-test",
            "tasks": {"private_payload": "DO_NOT_EXPORT_THIS"},
        }
    )
    assert "terminal_mode=QUALIFIED_STATE_BOUND" in prompt
    assert '"full_context_sha256":"' in prompt
    assert '"status":"ACCEPTED_CURRENT"' in prompt
    assert "Runtime evidence is not permission" in prompt
    assert "DO_NOT_EXPORT_THIS" not in prompt
    assert "private_payload" not in prompt


def test_terminal_session_generates_with_native_model_and_keeps_ephemeral_history():
    model, tokenizer = _tiny_artifacts()
    session = TerminalChatSession.source_only(
        model,
        tokenizer,
        max_new_tokens=2,
        temperature=0,
    )
    reply = session.ask("hello")
    assert isinstance(reply, str)
    assert [turn.role for turn in session.history] == ["user", "assistant"]
    assert "VERA_NATIVE_TRANSFORMER_V1" in session.descriptor
    session.clear()
    assert session.history == ()


def test_terminal_session_has_no_external_backend_surface():
    model, tokenizer = _tiny_artifacts()
    session = TerminalChatSession.source_only(model, tokenizer)
    assert not hasattr(session, "backend")
