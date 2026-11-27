import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _canonical_git_bytes(path: Path) -> bytes:
    raw = path.read_bytes()
    return raw.replace(b"\r\n", b"\n")


def _git_blob_sha1(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def test_absorbed_ingest_source_matches_reviewed_donor_hash_manifest():
    provenance = json.loads(
        (ROOT / "provenance/donors/ingest_universal_intake.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["donor_head"] == "4e98996391498517976625af90cd938233fbd7d6"
    assert provenance["runtime_dependency_on_donor_repository"] is False
    assert len(provenance["source_files"]) == 17

    adaptations = provenance["local_source_adaptations"]
    assert len(adaptations) == 2
    by_path = {item["local_path"]: item for item in adaptations}
    assert set(by_path) == {"src/ingest/storage.py", "src/ingest/pipeline.py"}
    original_blobs = {
        "src/ingest/storage.py": "5fe08590c2ae48fa5584da58d645386cea22a8f9",
        "src/ingest/pipeline.py": "6c222bad94592946885485f0bb88655706c743bb",
    }
    for item in provenance["source_files"]:
        raw = _canonical_git_bytes(
            ROOT / "packages/vera_ingest" / item["local_path"]
        )
        expected = item
        if item["local_path"] in by_path:
            adapted = by_path[item["local_path"]]
            assert item["git_blob"] == adapted["base_donor_git_blob"] == original_blobs[item["local_path"]]
            assert item["sha256"] == adapted["base_donor_sha256"]
            expected = adapted
        assert len(raw) == expected["size"]
        assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
        assert _git_blob_sha1(raw) == expected["git_blob"]
