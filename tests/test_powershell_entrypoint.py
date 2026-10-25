from pathlib import Path
import shutil
import subprocess

import pytest


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


def test_powershell_default_console_does_not_select_or_start_a_model():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8").lower()
    assert "openai" not in text
    assert "ollama" not in text
    assert "lm studio" not in text
    assert "--base-url" not in text
    assert "& $veraexe shell @forwardargs" in text
    assert "& $veraexe chat @chatargs" in text
    assert "if ($chat)" in text


def test_chat_requires_existing_directory_before_virtual_environment():
    launcher=(ROOT / "vera.ps1").read_text(encoding="utf-8")
    guard="Test-Path -LiteralPath $StateRoot -PathType Container"
    assert guard in launcher
    assert launcher.index(guard) < launcher.index("if (-not (Test-Path $VenvPython))")


def test_powershell_chat_requires_explicit_all_binding_and_model_inputs():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8")
    for option in ("$Chat", "$Endpoint", "$Model", "$StateRoot", "$ProjectId", "$IdentityId"):
        assert option in text
    for requirement in ('"StateRoot"', '"ProjectId"', '"IdentityId"', '"Endpoint"', '"Model"'):
        assert requirement in text
    assert '"--interactive"' in text
    assert '"--endpoint"' in text
    assert '"--model"' in text
    assert "& $VeraExe chat @ChatArgs" in text
    assert "& $VeraExe shell @ForwardArgs" in text


def test_powershell_chat_never_uses_shell_expression_or_implicit_credentials():
    text = (ROOT / "vera.ps1").read_text(encoding="utf-8")
    assert "Invoke-Expression" not in text
    assert "iex " not in text.lower()
    assert "Start-Process" not in text
    assert "Invoke-WebRequest" not in text
    assert '"--api-key-env"' in text
    assert "--api-key=" not in text
    assert "$ChatArgs += $ConsoleArgs" not in text


@pytest.mark.skipif(
    not (shutil.which("pwsh") or shutil.which("powershell")),
    reason="PowerShell is not installed on this runner",
)
def test_powershell_chat_preflight_fails_before_installing_or_executing_arguments(tmp_path):
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    canary_path = tmp_path / "shell-injection-canary.txt"
    injected_model = f"gemma3:1b;Set-Content -Path '{canary_path}' -Value PWNED"

    # Endpoint is deliberately omitted so the test never creates a venv or
    # calls a provider, even when run against a Windows checkout.
    result = subprocess.run(
        [
            powershell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "vera.ps1"),
            "-Chat", "-StateRoot", str(tmp_path / "existing-state"),
            "-ProjectId", "explicit-project", "-IdentityId", "explicit-identity",
            "-Model", injected_model,
        ],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode != 0
    assert "Explicit -Endpoint is required with -Chat" in (result.stderr + result.stdout)
    assert not canary_path.exists()


@pytest.mark.skipif(
    not (shutil.which("pwsh") or shutil.which("powershell")),
    reason="PowerShell is not installed on this runner",
)
def test_local_chat_rejects_missing_state_root_before_invoking_environment(tmp_path):
    """Explicit chat requires an existing state directory before even checking the venv."""
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    temp_repo = tmp_path / "staged-launcher"
    temp_repo.mkdir()
    shutil.copy2(ROOT / "vera.ps1", temp_repo / "vera.ps1")
    # Preinstall inert executable stubs so the *old* launcher would reach chat
    # immediately rather than downloading dependencies or making a new venv.
    # cmd.exe invoked as "chat" fails locally, without model/network effects.
    import os
    scripts = temp_repo / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    for target in ("python.exe", "vera-mono.exe"):
        shutil.copy2(os.environ["COMSPEC"], scripts / target)
    absent = tmp_path / "does-not-exist"
    result = subprocess.run(
        [
            powershell, "-NoProfile", "-NonInteractive", "-File",
            str(temp_repo / "vera.ps1"), "-Chat",
            "-StateRoot", str(absent), "-ProjectId", "test-project",
            "-IdentityId", "test-identity",
            "-Endpoint", "http://127.0.0.1:11434/v1",
            "-Model", "gemma3:1b",
        ],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode != 0
    assert "must name an existing directory" in (result.stdout + result.stderr)
    assert not absent.exists()


@pytest.mark.skipif(
    not (shutil.which("pwsh") or shutil.which("powershell")),
    reason="PowerShell is not installed on this runner",
)
def test_powershell_shell_rejects_model_only_options_before_installing():
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "vera.ps1"),
         "-Model", "gemma3:1b"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode != 0
    assert "-Model requires explicit -Chat" in (result.stderr + result.stdout)


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
