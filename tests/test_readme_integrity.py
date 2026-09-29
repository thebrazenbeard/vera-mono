from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_readme_has_no_literal_paragraph_escape_artifacts():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "\\n\\n" not in readme


def test_readme_package_counts_match_root_distribution_configuration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]
    assert len(package_find["where"]) == 12
    assert len(package_find["include"]) == 15
    assert (
        "searches twelve monorepo source roots and includes fifteen "
        "runtime package namespaces"
    ) in readme
