import sqlite3

import pytest

from vera_assurance.effect_fence import AtomicCurrentnessStore, EffectFence, EffectFenceError, EffectState
from vera_recovery.native import NativeRecoveryCheckpointStore, StaleCheckpointHead
from vera_core.lifecycle_journal import LifecycleJournal, LifecycleJournalError
from vera_core.outbound_audit import OutboundExecutionAudit, OutboundAuditError


@pytest.fixture
def observed_connections(monkeypatch):
    actual_connect = sqlite3.connect
    connections = []

    def connect(*args, **kwargs):
        connection = actual_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        yield connections
    finally:
        for connection in connections:
            connection.close()


def assert_closed(connections):
    assert connections, "real SQLite connections must be exercised"
    open_count = 0
    for connection in connections:
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            continue
        open_count += 1
    assert open_count == 0, f"{open_count} SQLite handles remain open"


def test_currentness_operations_release_handles(tmp_path, observed_connections):
    store = AtomicCurrentnessStore(tmp_path / "current.sqlite")
    first = store.publish("subject", {"v": 1}, expected_generation=None)
    assert store.read("subject") == first
    assert store.read_payload("subject") == {"v": 1}
    with pytest.raises(EffectFenceError, match="stale"):
        store.publish("subject", {"v": 2}, expected_generation=None)
    assert store.read("subject") == first
    assert_closed(observed_connections)


def test_effect_fence_operations_release_handles(tmp_path, observed_connections):
    fence = EffectFence(tmp_path / "effects.sqlite")
    args = dict(effect_id="synthetic", request_digest="a"*64, mechanical_permit_digest="b"*64,
                authority_evidence_digest="c"*64, currentness_evidence_digest="d"*64)
    assert fence.reserve(**args).state is EffectState.RESERVED
    assert fence.claim_dispatch(**args).state is EffectState.EXECUTING
    assert fence.settle("synthetic", result_digest=None, completion_known=False).state is EffectState.ATTEMPTED_UNKNOWN
    with pytest.raises(EffectFenceError):
        fence.claim_dispatch(**args)
    assert len(fence.unresolved()) == 1
    assert fence.reconcile_unknown("synthetic", effect_occurred=False, result_digest=None,
                                   reconciliation_evidence_digest="e"*64).state is EffectState.RECONCILED_NO_EFFECT
    fence.assert_clear()
    assert fence.read("synthetic") == fence.all()[0]
    assert_closed(observed_connections)


def test_checkpoint_operations_release_handles(tmp_path, observed_connections):
    store = NativeRecoveryCheckpointStore(tmp_path / "recovery.sqlite", project_id="fixture", identity_id="fixture")
    genesis = store.current_head
    args = dict(checkpoint_id="one", runtime_id="fixture", memory_head_digest="a"*64,
                control_source_digest="b"*64, expected_head=genesis, created_at="2026-01-01T00:00:00+00:00")
    first = store.append(**args)
    assert store.append(**args) == first
    with pytest.raises(StaleCheckpointHead):
        store.append(**dict(args, checkpoint_id="two"))
    assert store.current_generation == 1
    assert store.current_head == first.checkpoint_digest
    assert store.read("one") == store.read_digest(first.checkpoint_digest) == store.latest()
    assert_closed(observed_connections)


def test_lifecycle_journal_operations_release_handles(tmp_path, observed_connections):
    journal = LifecycleJournal(tmp_path / "journal.sqlite")
    args = dict(transition_id="fixture", event_type="TEST", payload={"v": 1})
    first = journal.append(**args)
    assert journal.append(**args) == first
    with pytest.raises(LifecycleJournalError):
        journal.append(**dict(args, payload={"v": 2}))
    assert journal.sequence == 1
    assert journal.head == journal.verify_chain() == first.event_digest
    assert journal.events() == (first,)
    assert journal.latest() == first
    assert journal.has_event("fixture", "TEST")
    assert_closed(observed_connections)


def test_outbound_audit_operations_release_handles(tmp_path, observed_connections):
    fence = EffectFence(tmp_path / "fence.sqlite")
    audit = OutboundExecutionAudit(tmp_path / "audit.sqlite")
    assert audit.repair_from_fence(fence).fence_effect_count == 0
    args = dict(effect_id="fixture", effect_kind="synthetic", event_type="AUTHORITY_VERIFIED", payload={"v": 1})
    first = audit.append(**args)
    assert audit.append(**args) == first
    with pytest.raises(OutboundAuditError):
        audit.append(**dict(args, payload={"v": 2}))
    assert audit.head == audit.verify_chain() == first.event_digest
    assert audit.sequence == 1
    assert audit.events() == (first,)
    assert audit.latest("fixture") == first
    assert audit.verify_fence_consistency(fence).authority_only_effect_ids == ("fixture",)
    assert_closed(observed_connections)
