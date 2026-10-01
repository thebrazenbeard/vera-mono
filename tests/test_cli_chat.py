from __future__ import annotations

import pytest

import vera_core.cli as cli


def test_chat_cli_uses_packaged_native_checkpoint_without_model_argument(capsys):
    result = cli.main(
        [
            "chat",
            "--temperature",
            "0",
            "--max-new-tokens",
            "1",
            "hello Vera",
        ]
    )
    assert result == 0
    assert capsys.readouterr().out.endswith("\n")


def test_chat_cli_rejects_old_external_model_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "chat",
                "--base-url",
                "http://localhost:1234/v1",
                "--model",
                "anything",
                "hello",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err


def test_chat_cli_requires_complete_state_binding(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "chat",
                "--state-root",
                str(tmp_path),
                "hello",
            ]
        )
    assert exc.value.code == 2
    assert "requires --state-root, --project-id, and --identity-id together" in capsys.readouterr().err


def test_chat_cli_requires_checkpoint_and_tokenizer_together(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "chat",
                "--checkpoint",
                str(tmp_path / "model.npz"),
                "hello",
            ]
        )
    assert exc.value.code == 2
    assert "--checkpoint and --tokenizer must be supplied together" in capsys.readouterr().err


def test_model_inspect_reports_bootstrap_as_smoke_checkpoint(capsys):
    result = cli.main(["model", "inspect"])
    assert result == 0
    payload = capsys.readouterr().out
    assert "PACKAGED_BOOTSTRAP_SMOKE_CHECKPOINT" in payload
    assert "SMOKE_CHECKPOINT_NOT_USEFUL_LANGUAGE_COMPETENCE" in payload
