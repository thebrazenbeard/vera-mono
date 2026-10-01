from __future__ import annotations

import pytest

import vera_core.cli as cli


class FakeBackend:
    descriptor = "fake-model @ http://local.test/v1"

    def __init__(
        self,
        *,
        base_url,
        model,
        api_key,
        timeout_seconds,
        temperature,
    ):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def complete(self, messages):
        assert messages[0].role == "system"
        assert messages[-1].role == "user"
        return "terminal reply"


def test_chat_cli_one_shot_source_only(monkeypatch, capsys):
    monkeypatch.setattr(cli, "OpenAICompatibleBackend", FakeBackend)

    result = cli.main(
        [
            "chat",
            "--base-url",
            "http://local.test/v1",
            "--model",
            "fake-model",
            "hello Vera",
        ]
    )

    assert result == 0
    assert capsys.readouterr().out == "terminal reply\n"


def test_chat_cli_requires_complete_state_binding(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "OpenAICompatibleBackend", FakeBackend)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "chat",
                "--base-url",
                "http://local.test/v1",
                "--model",
                "fake-model",
                "--state-root",
                str(tmp_path),
                "hello",
            ]
        )

    assert exc.value.code == 2
    assert "requires --state-root, --project-id, and --identity-id together" in (
        capsys.readouterr().err
    )


def test_chat_cli_requires_explicit_generator(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["chat", "hello"])

    assert exc.value.code == 2
    assert "requires --base-url or VERA_MODEL_BASE_URL" in capsys.readouterr().err
