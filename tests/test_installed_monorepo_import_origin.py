"""The installed bundle may not silently combine site-packages with checkout code."""
from pathlib import Path

import pytest

from scripts.verify_installed_monorepo import require_single_install_root


def test_installed_imports_must_share_one_distribution_root(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    selected = root / "runtime_cohesion" / "__init__.py"
    sibling = root / "portfolio_runtime" / "__init__.py"
    nested = root / "vera_core" / "cli.py"
    assert require_single_install_root(selected, {
        "runtime_cohesion": selected,
        "portfolio_runtime": sibling,
        "vera_core.cli": nested,
    }) == root


def test_checkout_import_cannot_disguise_itself_as_installed_bundle(tmp_path: Path) -> None:
    root = tmp_path / "site-packages"
    installed = root / "runtime_cohesion" / "__init__.py"
    checkout = tmp_path / "vera-mono" / "packages" / "portfolio_runtime" / "src" / "portfolio_runtime" / "__init__.py"
    with pytest.raises(ValueError, match="portfolio_runtime"):
        require_single_install_root(installed, {
            "runtime_cohesion": installed,
            "portfolio_runtime": checkout,
        })
