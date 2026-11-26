"""Existing-state selection must not silently create a new memory identity."""
from pathlib import Path
import pytest
from vera_core import VeraStateDirectory, QualifiedVeraRuntime
from vera_core.cli import main
from vera_memory import MemoryLedger
from vera_memory.ledger import MemoryLedgerError

def state(root, **kwargs):
    return VeraStateDirectory(root, project_id="fixture", identity_id="A", **kwargs)

@pytest.mark.parametrize("condition", ["absent", "empty-root", "missing-ledger", "zero-byte"])
def test_existing_state_selection_refuses_missing_or_empty_memory(tmp_path, condition):
    root = tmp_path / "selected"
    if condition != "absent":
        root.mkdir()
    if condition == "missing-ledger":
        (root / "unrelated").write_bytes(b"existing state")
    if condition == "zero-byte":
        path = root / "memory" / "memory.sqlite"
        path.parent.mkdir()
        path.touch()
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    existed = root.exists()
    with pytest.raises(MemoryLedgerError, match="existing|empty|fresh"):
        QualifiedVeraRuntime.from_state_directory(state(root))
    assert root.exists() == existed
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before

def test_direct_existing_zero_byte_refused_even_with_creation_permission(tmp_path):
    target = tmp_path / "memory.sqlite"
    target.touch()
    with pytest.raises(MemoryLedgerError, match="empty|fresh"):
        MemoryLedger(target, project_id="fixture", identity_id="A")
    assert target.read_bytes() == b""

def test_cli_existing_empty_root_refused(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["status", "--state-root", str(tmp_path), "--project-id", "fixture", "--identity-id", "A"])
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())

def test_explicit_fresh_and_bound_reopen(tmp_path):
    root = tmp_path / "fresh"
    selected = state(root, initialize=True)
    initial = selected.open().memory.current_head
    assert state(root).open().memory.current_head == initial
    assert selected.open().memory.current_head == initial
    selected.paths.memory.unlink()
    with pytest.raises(MemoryLedgerError):
        selected.open()
    assert not selected.paths.memory.exists()

def test_explicit_fresh_cannot_adopt_partial_root(tmp_path):
    (tmp_path / "existing-evidence").write_bytes(b"do not overwrite")
    with pytest.raises(MemoryLedgerError):
        state(tmp_path, initialize=True).open()
    assert list(tmp_path.iterdir()) == [tmp_path / "existing-evidence"]
