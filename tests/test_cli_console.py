from __future__ import annotations

import io

import pytest

import vera_core.cli as cli


def test_shell_one_shot_source_only(capsys):
    result = cli.main(["shell", ":status"])
    assert result == 0
    out = capsys.readouterr().out
    assert "SOURCE_ONLY" in out


def test_shell_identity_one_shot(capsys):
    result = cli.main(["shell", "who are you?"])
    assert result == 0
    assert "configured interaction identity" in capsys.readouterr().out


def test_shell_requires_complete_state_binding(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["shell", "--state-root", str(tmp_path), ":status"])
    assert exc.value.code == 2
    assert "requires --state-root, --project-id, and --identity-id together" in capsys.readouterr().err


def test_shell_rejects_external_model_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["shell", "--model", "anything", ":status"])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_shell_reads_piped_stdin(monkeypatch, capsys):
    fake = io.StringIO(":status\n")
    monkeypatch.setattr(cli.sys, "stdin", fake)
    result = cli.main(["shell"])
    assert result == 0
    assert "SOURCE_ONLY" in capsys.readouterr().out
