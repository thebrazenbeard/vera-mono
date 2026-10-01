from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_powershell_entrypoint_is_repo_rooted_and_local():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8")
    assert "$PSScriptRoot" in text
    assert ".venv" in text
    assert "pip install" in text
    assert "-e" in text
    assert "vera-mono" in text
    assert "shell" in text


def test_powershell_entrypoint_forwards_remaining_arguments():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8")
    assert "ValueFromRemainingArguments" in text
    assert "@ConsoleArgs" in text


def test_powershell_entrypoint_has_no_external_model_server_configuration():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8").lower()
    assert "openai" not in text
    assert "ollama" not in text
    assert "lm studio" not in text
    assert "--model" not in text
    assert "--base-url" not in text
    assert "api_key" not in text


def test_local_console_environment_is_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".venv/" in ignore
