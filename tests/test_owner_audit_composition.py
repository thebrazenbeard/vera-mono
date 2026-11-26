from contextlib import closing
import sqlite3
import pytest
from vera_memory.ledger import MemoryLedger, StaleMemoryHead
from vera_memory.integrity import audit_current_memory_ledger, CurrentMemoryAuditError
from test_current_memory_integrity import admission, setup_two, audit

def test_bound_empty_reports_matched_metadata_not_authentication(tmp_path):
    path=tmp_path/"empty.sqlite"
    MemoryLedger(path,project_id="vera-mono",identity_id="vera")
    before=path.read_bytes()
    result=audit(path)
    assert result["owner_binding"]=="LOCAL_METADATA_MATCHED"
    assert result["record_count"]==0
    assert result["evidence_class"].endswith("NOT_AUTHENTICATED")
    assert path.read_bytes()==before
    with pytest.raises(CurrentMemoryAuditError,match="identity|project"):
        audit_current_memory_ledger(path,project_id="another",identity_id="vera")
    assert path.read_bytes()==before

def test_bound_populated_audit_matches_head(tmp_path):
    path,store=setup_two(tmp_path)
    before=path.read_bytes()
    result=audit(path)
    assert result["owner_binding"]=="LOCAL_METADATA_MATCHED"
    assert result["head"]==store.current_head
    assert result["record_count"]==2
    assert path.read_bytes()==before

@pytest.mark.parametrize("populated",[False,True])
def test_legacy_unbound_is_distinguished_not_migrated(tmp_path,populated):
    if populated:
        path,_=setup_two(tmp_path)
    else:
        path=tmp_path/"empty.sqlite"
        MemoryLedger(path,project_id="vera-mono",identity_id="vera")
    with closing(sqlite3.connect(path)) as db,db:
        db.execute("DELETE FROM meta WHERE key IN ('owner_project_id','owner_identity_id')")
    before=path.read_bytes()
    result=audit(path)
    assert result["owner_binding"]=="LEGACY_UNBOUND"
    assert result["record_count"]==(2 if populated else 0)
    assert path.read_bytes()==before

@pytest.mark.parametrize("statement",[
    "DELETE FROM meta WHERE key='owner_identity_id'",
    "INSERT INTO meta(key,value) VALUES ('unexpected','x')",
    "UPDATE meta SET value='another' WHERE key='owner_project_id'",
])
def test_partial_extra_or_mismatched_owner_rejected(tmp_path,statement):
    path=tmp_path/"empty.sqlite"
    MemoryLedger(path,project_id="vera-mono",identity_id="vera")
    with closing(sqlite3.connect(path)) as db,db:
        db.execute(statement)
    before=path.read_bytes()
    with pytest.raises(CurrentMemoryAuditError):
        audit(path)
    assert path.read_bytes()==before

def test_expected_head_is_one_read_snapshot(tmp_path):
    path=tmp_path/"race.sqlite"
    writer=MemoryLedger(path,project_id="vera-mono",identity_id="vera")
    writer.admit(admission("old"),expected_head=writer.current_head)
    with closing(sqlite3.connect(path)) as db,db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0]=="wal"
    oldhead=writer.current_head
    class Reader(MemoryLedger):
        callback=None
        def _meta(self,db):
            result=super()._meta(db)
            if self.callback is not None:
                cb=self.callback
                self.callback=None
                cb()
            return result
    reader=Reader(path,project_id="vera-mono",identity_id="vera")
    reader.callback=lambda: writer.admit(admission("new",supersedes="old"),expected_head=oldhead)
    result=reader.read("old",expected_head=oldhead)
    assert result.status=="CURRENT"
    assert writer.current_head!=oldhead
    assert writer.read("old").status=="SUPERSEDED"
    with pytest.raises(StaleMemoryHead):
        reader.read("old",expected_head=oldhead)
