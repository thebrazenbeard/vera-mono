from pathlib import Path


RUNTIME_ROOTS = (Path("packages"),)
NETWORK_SOURCE_PATTERNS = (
    "git clone",
    "raw.githubusercontent.com",
    "https://github.com/",
    "http://github.com/",
)
REPOSITORY_IDENTIFIER = "thebrazenbeard/"
ALLOWED_REPOSITORY_ID_CODE = {
    Path("packages/vera_runtime/src/runtime_cohesion/local_bindings.py"),
}


def source_files():
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".toml"}:
                yield path


def test_no_git_submodules():
    assert not Path(".gitmodules").exists()


def test_runtime_code_has_no_network_source_checkout_dependency():
    violations = []
    for path in source_files():
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in NETWORK_SOURCE_PATTERNS:
            if token.lower() in text:
                violations.append((str(path), token))
    assert violations == []


def test_sibling_repository_ids_are_confined_to_explicit_provenance_gateway():
    violations = []
    for path in source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if REPOSITORY_IDENTIFIER not in text:
            continue
        if path in ALLOWED_REPOSITORY_ID_CODE:
            # This file owns the explicit local-repository identity plus donor
            # origin metadata. It must not fetch donor source at runtime.
            assert "git clone" not in text.lower()
            assert "https://github.com/" not in text.lower()
            continue
        violations.append(str(path))
    assert violations == []
