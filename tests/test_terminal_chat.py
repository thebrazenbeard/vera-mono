from __future__ import annotations

import pytest

from vera_core.terminal_chat import (
    ChatMessage,
    OpenAICompatibleBackend,
    TerminalChatSession,
    build_terminal_system_prompt,
)


class FakeBackend:
    descriptor = "fake-model @ local-test"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_source_only_prompt_loads_governed_identity_and_behavior():
    prompt = build_terminal_system_prompt()

    assert "terminal_mode=SOURCE_ONLY" in prompt
    assert "VERA_PROJECT_IDENTITY_V1" in prompt
    assert "VERA_BEHAVIOR_PROFILE_V1" in prompt
    assert "Do not claim installation" in prompt


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
    assert "not as permission for new external effects" in prompt
    assert "DO_NOT_EXPORT_THIS" not in prompt
    assert "private_payload" not in prompt


def test_terminal_session_keeps_ephemeral_history_and_clear():
    backend = FakeBackend(["First reply", "Second reply"])
    session = TerminalChatSession.source_only(backend)

    first = session.ask("hello")
    assert first == "First reply"
    assert [message.role for message in session.history] == [
        "system",
        "user",
        "assistant",
    ]
    assert backend.calls[0][1] == ChatMessage("user", "hello")

    session.clear()
    assert [message.role for message in session.history] == ["system"]

    second = session.ask("again")
    assert second == "Second reply"


def test_failed_generation_does_not_poison_history():
    class BrokenBackend:
        descriptor = "broken"

        def complete(self, messages):
            raise RuntimeError("backend failed")

    session = TerminalChatSession.source_only(BrokenBackend())

    with pytest.raises(RuntimeError, match="backend failed"):
        session.ask("hello")

    assert [message.role for message in session.history] == ["system"]


def test_openai_compatible_backend_normalizes_endpoint_without_network():
    backend = OpenAICompatibleBackend(
        base_url="http://localhost:1234/v1/",
        model="local-model",
    )

    assert backend.chat_completions_url == (
        "http://localhost:1234/v1/chat/completions"
    )
    assert backend.descriptor == "local-model @ http://localhost:1234/v1"


@pytest.mark.parametrize(
    "base_url",
    ["", "localhost:1234/v1", "file:///tmp/model"],
)
def test_openai_compatible_backend_rejects_invalid_base_url(base_url):
    with pytest.raises(ValueError):
        OpenAICompatibleBackend(base_url=base_url, model="model")
