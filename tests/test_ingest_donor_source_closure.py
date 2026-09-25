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

    for item in provenance["source_files"]:
        raw = _canonical_git_bytes(
            ROOT / "packages/vera_ingest" / item["local_path"]
        )
        assert len(raw) == item["size"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert _git_blob_sha1(raw) == item["git_blob"]
