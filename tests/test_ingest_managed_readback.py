import json
from pathlib import Path
import pytest

from ingest import BytesSource, FileSystemStore, Ingestor, IngestStatus, TextSource
from ingest.storage import StoreConflict


def fixture(tmp_path):
    store = FileSystemStore(tmp_path / "intake")
    result = Ingestor(store).ingest(TextSource("raw\r\ntext", locator="urn:fixture"))
    assert result.status is IngestStatus.ACCEPTED
    return store, result, store.root / "records" / (result.ingest_id + ".json")


@pytest.mark.parametrize("damage", ["same-size", "size", "missing", "normalized", "locator", "artifact-id", "record-id", "raw-substitution"])
def test_managed_readback_refuses_corruption(tmp_path, damage):
    store, result, record_path = fixture(tmp_path)
    record = json.loads(record_path.read_bytes())
    raw = store.root / result.raw_artifact.storage_locator
    normalized = store.root / result.normalized_artifact.storage_locator
    if damage == "same-size":
        raw.write_bytes(b"x" * result.raw_artifact.size_bytes)
    elif damage == "size":
        raw.write_bytes(b"x")
    elif damage == "missing":
        raw.unlink()
    elif damage == "normalized":
        normalized.write_bytes(b"x")
    elif damage == "locator":
        record["raw_artifact"]["storage_locator"] = "../outside"
    elif damage == "artifact-id":
        record["raw_artifact"]["artifact_id"] = "sha256:" + "0" * 64
    elif damage == "record-id":
        record["ingest_id"] = "0" * 64
    elif damage == "raw-substitution":
        other, _ = store.put_blob(b"unrelated", media_type="text/plain", kind="raw")
        record["raw_artifact"] = other.to_dict()
    if damage in {"locator", "artifact-id", "record-id", "raw-substitution"}:
        record_path.write_text(json.dumps(record))
    with pytest.raises(StoreConflict):
        store.get_record(result.ingest_id)


def test_readback_refuses_managed_symlink(tmp_path):
    store, result, _ = fixture(tmp_path)
    raw = store.root / result.raw_artifact.storage_locator
    outside = tmp_path / "outside"
    outside.write_bytes(raw.read_bytes())
    raw.unlink()
    try:
        raw.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation not available")
    with pytest.raises(StoreConflict):
        store.get_record(result.ingest_id)


@pytest.mark.parametrize("source,status", [
    (TextSource("same"), IngestStatus.ACCEPTED),
    (TextSource(""), IngestStatus.ACCEPTED),
    (BytesSource(b"\xff\x00"), IngestStatus.ACCEPTED),
    (BytesSource(b'{"broken":', media_type="application/json"), IngestStatus.QUARANTINED),
])
def test_legacy_records_readback_and_duplicate_identity(tmp_path, source, status):
    store = FileSystemStore(tmp_path / "intake")
    first = Ingestor(store).ingest(source)
    assert first.status is status
    original = (store.root / "records" / (first.ingest_id + ".json")).read_bytes()
    reopened = FileSystemStore(store.root)
    assert reopened.get_record(first.ingest_id) == json.loads(original)
    second = Ingestor(reopened).ingest(source)
    assert second.ingest_id == first.ingest_id
    assert second.status is (IngestStatus.DUPLICATE if status is IngestStatus.ACCEPTED else status)
    assert (store.root / "records" / (first.ingest_id + ".json")).read_bytes() == original

def test_readback_preserves_missing_record_contract(tmp_path):
    store = FileSystemStore(tmp_path / "intake")
    with pytest.raises(FileNotFoundError):
        store.get_record("f" * 64)

def test_duplicate_refuses_corrupt_normalized_material(tmp_path):
    store, result, _ = fixture(tmp_path)
    (store.root / result.normalized_artifact.storage_locator).write_bytes(b"bad")
    with pytest.raises(StoreConflict):
        Ingestor(store).ingest(TextSource("raw\r\ntext", locator="urn:fixture"))

@pytest.mark.parametrize("damage", ["foreign-ready", "derivation-parent", "relabel-quarantine", "missing-normal", "foreign-normal", "acquire-source"])
def test_bound_lineage_refuses_inconsistent_existing_record(tmp_path, damage):
    from ingest.canonical import canonical_digest
    store, result, record_path = fixture(tmp_path)
    if damage == "relabel-quarantine":
        result = Ingestor(store).ingest(BytesSource(b'{"bad":', media_type="application/json"))
        record_path = store.root / "records" / (result.ingest_id + ".json")
    record = json.loads(record_path.read_bytes())
    if damage in {"foreign-ready", "acquire-source"}:
        ident = record["receipt_ids"][-1 if damage == "foreign-ready" else 0]
        path = store.root / "receipts" / (ident + ".json")
        receipt = json.loads(path.read_bytes())
        receipt.pop("receipt_digest")
        if damage == "foreign-ready":
            receipt["ingest_id"] = "a" * 64
        else:
            receipt["details"]["source"]["locator"] = "urn:foreign"
        receipt["receipt_digest"] = canonical_digest(receipt)
        path.write_text(json.dumps(receipt))
    elif damage == "derivation-parent":
        path = store.root / "derivations" / (record["derivation_ids"][0] + ".json")
        value = json.loads(path.read_bytes())
        value["parent_artifact_id"] = "sha256:" + "a" * 64
        path.write_text(json.dumps(value))
    elif damage == "relabel-quarantine":
        record["status"] = "ACCEPTED"
    elif damage == "missing-normal":
        record["normalized_artifact"] = None
    else:
        other, _ = store.put_blob(b"another derivative", media_type="text/plain", kind="normalized")
        record["normalized_artifact"] = other.to_dict()
    record_path.write_text(json.dumps(record))
    with pytest.raises(StoreConflict):
        store.get_record(result.ingest_id)


def test_shared_derivation_preserves_distinct_ingests(tmp_path):
    store = FileSystemStore(tmp_path / "intake")
    ingestor = Ingestor(store)
    a = ingestor.ingest(TextSource("shared\r\nmaterial", locator="urn:a"))
    b = ingestor.ingest(TextSource("shared\r\nmaterial", locator="urn:b"))
    assert a.ingest_id != b.ingest_id
    assert a.derivation_ids == b.derivation_ids and len(a.derivation_ids) == 1
    assert store.get_record(a.ingest_id)["status"] == "ACCEPTED"
    assert store.get_record(b.ingest_id)["status"] == "ACCEPTED"

@pytest.mark.parametrize("damage", ["missing-receipt", "receipt-digest", "duplicate-receipt", "record-symlink", "root-symlink"])
def test_managed_record_reference_and_root_fail_closed(tmp_path, damage):
    store, result, path = fixture(tmp_path)
    record = json.loads(path.read_bytes())
    if damage in {"missing-receipt", "receipt-digest"}:
        receipt_path = store.root / "receipts" / (record["receipt_ids"][1] + ".json")
        if damage == "missing-receipt":
            receipt_path.unlink()
        else:
            value = json.loads(receipt_path.read_bytes())
            value["receipt_digest"] = "0" * 64
            receipt_path.write_text(json.dumps(value))
    elif damage == "duplicate-receipt":
        record["receipt_ids"][2] = record["receipt_ids"][1]
        path.write_text(json.dumps(record))
    elif damage == "record-symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation unavailable")
    else:
        alias = tmp_path / "alias"
        try:
            alias.symlink_to(store.root, target_is_directory=True)
        except OSError:
            pytest.skip("symlink creation unavailable")
        store = FileSystemStore(alias)
    with pytest.raises(StoreConflict):
        store.get_record(result.ingest_id)

def test_duplicate_does_not_recreate_missing_raw_material(tmp_path):
    store, result, path = fixture(tmp_path)
    original = path.read_bytes()
    raw = store.root / result.raw_artifact.storage_locator
    raw.unlink()
    with pytest.raises(StoreConflict):
        Ingestor(store).ingest(TextSource("raw\r\ntext", locator="urn:fixture"))
    assert not raw.exists()
    assert path.read_bytes() == original

@pytest.mark.parametrize("damage", ["directory", "metadata-denied"])
def test_duplicate_nonregular_or_inaccessible_record_cannot_repair_raw(tmp_path, monkeypatch, damage):
    store, result, path = fixture(tmp_path)
    raw = store.root / result.raw_artifact.storage_locator
    raw.unlink()
    if damage == "directory":
        path.unlink()
        path.mkdir()
    else:
        original = Path.lstat
        def denied(self, *args, **kwargs):
            if self == path:
                raise PermissionError("synthetic metadata denial")
            return original(self, *args, **kwargs)
        monkeypatch.setattr(Path, "lstat", denied)
    with pytest.raises(StoreConflict):
        Ingestor(store).ingest(TextSource("raw\r\ntext", locator="urn:fixture"))
    assert not raw.exists()
