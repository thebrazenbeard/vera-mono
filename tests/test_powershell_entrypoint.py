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
    assert "$ForwardArgs += $ConsoleArgs" in text
    assert "@ForwardArgs" in text


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


def test_powershell_entrypoint_exposes_runtime_binding_parameters():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8")
    for parameter in ("$StateRoot", "$ProjectId", "$IdentityId"):
        assert parameter in text
    for cli_flag in ("--state-root", "--project-id", "--identity-id"):
        assert cli_flag in text
    assert "$ForwardArgs" in text


def test_py_launcher_fallback_accepts_any_supported_python_3_minor():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8")
    # A Windows host with Python 3.13/3.14 but no 3.12 and no `python`
    # command must not be forced onto a missing interpreter version.
    assert '& $py.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"' in text
    assert "& $py.Source -3 -m venv $VenvRoot" in text
    assert "& $py.Source -3.12" not in text
