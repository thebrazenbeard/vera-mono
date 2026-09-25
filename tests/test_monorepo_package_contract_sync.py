import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_monorepo_package_contract_matches_root_distribution_configuration():
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    contract = load_json("architecture/VERA_MONOREPO_PACKAGE_V1.json")
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")

    project = pyproject["project"]
    assert project["name"] == contract["distribution"]["name"]
    assert project["version"] == contract["distribution"]["version"]
    assert project["requires-python"] == contract["distribution"]["python"]
    assert project["scripts"]["vera-mono"] == "vera_core.cli:main"
    assert set(project["dependencies"]) == set(
        contract["self_containment"]["external_python_dependency"]
    )

    configured_patterns = set(
        pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    )
    for package in contract["package_roots"]:
        assert any(
            pattern.rstrip("*") == package
            for pattern in configured_patterns
        )

    manifest_package = manifest["monorepo_package"]
    assert manifest_package["contract"] == (
        "architecture/VERA_MONOREPO_PACKAGE_V1.json"
    )
    assert manifest_package["root_distribution"] == project["name"]
    assert manifest_package["package_root_count"] == len(
        contract["package_roots"]
    )


def test_monorepo_package_contract_keeps_build_install_runtime_separate():
    contract = load_json("architecture/VERA_MONOREPO_PACKAGE_V1.json")
    boundaries = contract["boundaries"]
    assert boundaries["wheel_build_pass_is_not_installation"] is True
    assert (
        boundaries[
            "wheel_install_in_ci_target_is_not_project_or_production_installation"
        ]
        is True
    )
    assert boundaries["package_import_pass_is_not_runtime_consumption"] is True
    assert (
        boundaries["package_import_pass_is_not_behavioral_qualification"]
        is True
    )
    assert boundaries["package_build_is_not_deployment"] is True
