"""Distribution contract for the fixed, optional Presence V2 MCP command."""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_optional_mcp_dependency_is_explicit_and_bounded():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    assert project["optional-dependencies"]["presence-v2-mcp"] == ["mcp>=2.2,<3"]
    assert "mcp" not in [entry.split("=")[0] for entry in project["dependencies"]]


def test_fixed_console_script_is_discoverable_without_cli_enablement():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    assert project["scripts"]["vera-presence-v2-mcp"] == "vera_core.presence_mcp_v2:main"
    assert (ROOT / "packages/vera_core/src/vera_core/presence_mcp_v2.py").is_file()


def test_monorepo_ci_installs_mcp_instead_of_silently_skipping_stdio_tests():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert '"mcp>=2.2,<3"' in workflow
