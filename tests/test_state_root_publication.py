"""Opening a denied state directory must not change process-local recovery roots."""
import sqlite3
import pytest
import r8a0.trust as trust
from vera_core import VeraStateDirectory
from vera_memory import MemoryLedger
from vera_memory.ledger import MemoryLedgerError
from vera_core.outbound_audit import OutboundExecutionAudit, OutboundAuditError

ROOT_FIELDS = ("PROVISIONING_ROOT", "AUTHORITY_ROOT_CONFIG_PATH",
               "TRUST_REGISTRY_CONFIG_PATH", "LIFECYCLE_REGISTRY_KEY_PATH")

def snapshot():
    return tuple(getattr(trust, name) for name in ROOT_FIELDS)

@pytest.fixture
def previous(tmp_path, monkeypatch):
    # Restore all process globals at test teardown; never load actual trust files.
    for name in ROOT_FIELDS:
        monkeypatch.setattr(trust, name, getattr(trust, name))
    prior = tmp_path / "previous"
    VeraStateDirectory(prior, initialize=True, project_id="fixture", identity_id="A").open()
    assert trust.PROVISIONING_ROOT == prior.resolve()
    return snapshot()

def test_wrong_owner_refusal_keeps_previous_root(tmp_path, previous):
    target = VeraStateDirectory(tmp_path / "other", project_id="fixture", identity_id="A")
    MemoryLedger(target.paths.memory, project_id="fixture", identity_id="B")
    before = target.paths.memory.read_bytes()
    with pytest.raises(MemoryLedgerError):
        target.open()
    assert target.paths.memory.read_bytes() == before
    assert snapshot() == previous

def test_later_checkpoint_failure_keeps_previous_root(tmp_path, previous):
    target = VeraStateDirectory(tmp_path / "other", project_id="fixture", identity_id="A")
    MemoryLedger(target.paths.memory, project_id="fixture", identity_id="A")
    target.paths.recovery.parent.mkdir(parents=True)
    target.paths.recovery.write_bytes(b"synthetic invalid SQLite")
    with pytest.raises(sqlite3.DatabaseError):
        target.open()
    assert snapshot() == previous

def test_final_audit_failure_keeps_previous_root(tmp_path, previous):
    target = VeraStateDirectory(tmp_path / "other", project_id="fixture", identity_id="A")
    MemoryLedger(target.paths.memory, project_id="fixture", identity_id="A")
    audit = OutboundExecutionAudit(target.paths.outbound_audit)
    audit.append(effect_id="synthetic", effect_kind="fixture", event_type="RESERVED", payload={})
    with pytest.raises(OutboundAuditError, match="ordering"):
        target.open()
    assert snapshot() == previous

def test_success_publishes_all_expected_paths(tmp_path, previous):
    target = VeraStateDirectory(tmp_path / "other", initialize=True, project_id="fixture", identity_id="A")
    runtime = target.open()
    root = target.paths.root
    assert runtime.memory.identity_id == "A"
    assert snapshot() == (root, root/"recovery"/"trust"/"authority-root.json",
                          root/"recovery"/"trust"/"trust-registry.json",
                          root/"recovery"/"trust"/"lifecycle-registry.key")
    assert not (root/"recovery"/"trust").exists()
