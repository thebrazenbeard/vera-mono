from pathlib import Path


RUNTIME_ROOTS = (Path("packages"),)
FORBIDDEN = ("git clone", ".gitmodules", "github.com/thebrazenbeard/")


def test_runtime_source_has_no_sibling_repo_dependency():
    violations = []
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".toml", ".json", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for token in FORBIDDEN:
                if token.lower() in text:
                    violations.append((str(path), token))
    assert violations == []
