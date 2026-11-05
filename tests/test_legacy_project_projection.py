"""Red/green synthetic tests for July 2026 five-file historical Project exports."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from ingest.legacy_project_projection import (
    LegacyProjectionError, audit_legacy_project_projection,
)

FILES = (
    "VERA_CORE_AND_BOOT.md", "VERA_INSTANCE_AND_IDENTITY.md",
    "VERA_GOVERNANCE_AND_PROVENANCE.md", "VERA_SEMANTIC_MEMORY.md",
    "VERA_STATE_AND_CONTEXT.md",
)
MANIFEST = "VERA_PROJECT_PROJECTION_MANIFEST.json"


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical(data: dict) -> bytes:
    return json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()


def make_fixture(tmp_path: Path, *, degraded: bool = False) -> Path:
    directory = tmp_path/"project-export"
    directory.mkdir(parents=True)
    for name in FILES:
        (directory/name).write_bytes(("# Historical: "+name+"\n"
                                      "SYNTHETIC_PERSONAL_DATA_DO_NOT_LEAK\n").encode())
    manifest = {
        "projection_schema_version":"1.0.0", "projection_version":"1.0.0",
        "kernel_contract_version":"0.2.3","lifecycle_version":"0.2.0",
        "branch_id":"branch-synthetic", "canonical_memory_available":not degraded,
        "generated_file_hashes":{name:_sha((directory/name).read_bytes()) for name in sorted(FILES)},
        "runtime_context_hash":_sha(b""),
        "instance_identity_hash":None,
    }
    if degraded:
        manifest["degraded_reason"]="synthetic-unavailable"
    else:
        manifest["source_event_max_seq"]=21
        manifest["canonical_state_fingerprint"]="a"*64
        manifest["lifecycle_operation"]="refresh"
    manifest["projection_fingerprint"]=_sha(_canonical(manifest))
    (directory/MANIFEST).write_bytes((json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode())
    return directory


def audit(directory:Path, **kwargs):
    return audit_legacy_project_projection(directory,expected_branch_id="branch-synthetic",**kwargs)


def test_valid_five_files_historical_only_with_no_mutations(tmp_path):
    directory=make_fixture(tmp_path)
    names={x.name for x in directory.iterdir()}
    before={x.name:x.read_bytes() for x in directory.iterdir()}
    report=audit(directory)
    assert report["ok"] is True
    assert report["status"]=="HISTORICAL_STRUCTURE_ONLY_NOT_CURRENT"
    assert report["file_count"]==5
    assert report["authority_effect"]=="NONE"
    assert report["memory_admission_effect"]=="NONE"
    assert "SYNTHETIC_PERSONAL_DATA_DO_NOT_LEAK" not in json.dumps(report)
    assert {x.name for x in directory.iterdir()}==names
    assert {x.name:x.read_bytes() for x in directory.iterdir()}==before


def test_degraded_export_is_never_called_current(tmp_path):
    directory=make_fixture(tmp_path,degraded=True)
    result=audit(directory)
    assert result["ok"] is True
    assert result["status"]=="HISTORICAL_DEGRADED_NOT_CURRENT"
    assert result["currentness_verified"] is False


def test_reject_changed_content_without_private_output(tmp_path):
    directory=make_fixture(tmp_path)
    with (directory/FILES[0]).open("ab") as f:f.write(b"tamper-private-unchanged-hash")
    with pytest.raises(LegacyProjectionError,match="file digest"):
        audit(directory)


def test_reject_wrong_manifest_fingerprint_even_with_consistent_file_hash(tmp_path):
    directory=make_fixture(tmp_path)
    p=directory/MANIFEST
    state=json.loads(p.read_text())
    state["canonical_state_fingerprint"]="b"*64
    p.write_text(json.dumps(state))
    with pytest.raises(LegacyProjectionError,match="fingerprint"):
        audit(directory)


def test_reject_duplicate_manifest_json_key(tmp_path):
    directory=make_fixture(tmp_path)
    p=directory/MANIFEST
    p.write_bytes(p.read_bytes().replace(b'"branch_id": "branch-synthetic"',
        b'"branch_id": "branch-synthetic", "branch_id": "branch-synthetic"'))
    with pytest.raises(LegacyProjectionError,match="JSON|manifest"):
        audit(directory)


def test_reject_wrong_version_and_degraded_flag_type(tmp_path):
    directory=make_fixture(tmp_path)
    p=directory/MANIFEST
    for key,value in (("kernel_contract_version","0.2.2"),("lifecycle_version","0.1.0"),
                      ("canonical_memory_available","false")):
        state=json.loads(p.read_text())
        state[key]=value
        state["projection_fingerprint"]=_sha(_canonical({k:v for k,v in state.items() if k!="projection_fingerprint"}))
        p.write_text(json.dumps(state))
        with pytest.raises(LegacyProjectionError,match="version|schema|availability"):
            audit(directory)
        # Restore the original fixture content before testing another mutation.
        baseline = json.loads((make_fixture(tmp_path / ("fresh-"+key))/MANIFEST).read_text())
        p.write_text(json.dumps(baseline,indent=2,sort_keys=True)+"\n")


def test_exact_branch_required_and_mismatch_fails_without_echo(tmp_path):
    directory=make_fixture(tmp_path)
    with pytest.raises(LegacyProjectionError,match="branch"):
        audit_legacy_project_projection(directory,expected_branch_id="other")
    with pytest.raises((ValueError,TypeError)):
        audit_legacy_project_projection(directory,expected_branch_id="")


def test_missing_unexpected_and_empty_files_fail(tmp_path):
    directory=make_fixture(tmp_path)
    (directory/FILES[1]).unlink()
    with pytest.raises(LegacyProjectionError,match="missing|file"):
        audit(directory)
    directory=make_fixture(tmp_path/"second")
    (directory/"EXTRA_PROJECT_INSTRUCTIONS.md").write_text("should never be implicitly projected")
    with pytest.raises(LegacyProjectionError,match="unexpected|file"):
        audit(directory)
    directory=make_fixture(tmp_path/"third")
    (directory/FILES[2]).write_bytes(b"")
    with pytest.raises(LegacyProjectionError,match="empty|file"):
        audit(directory)


def test_reject_symlinks_and_oversize_before_file_payload_read(tmp_path):
    directory=make_fixture(tmp_path)
    with pytest.raises(LegacyProjectionError,match="size|limit"):
        audit(directory,max_file_bytes=8)
    file_path=directory/FILES[0]
    original=tmp_path/"outside-private.txt"
    original.write_text("PRIVATE_OUTSIDE")
    file_path.unlink()
    try:file_path.symlink_to(original)
    except (OSError,NotImplementedError):pytest.skip("symlinks unavailable")
    with pytest.raises(LegacyProjectionError,match="symlink|reparse|unsafe"):
        audit(directory)


def test_invalid_manifest_structure_fails_closed(tmp_path):
    directory=make_fixture(tmp_path)
    p=directory/MANIFEST
    state=json.loads(p.read_text())
    state["generated_file_hashes"]["unexpected.md"]="b"*64
    state["projection_fingerprint"]=_sha(_canonical({k:v for k,v in state.items() if k!="projection_fingerprint"}))
    p.write_text(json.dumps(state))
    with pytest.raises(LegacyProjectionError,match="manifest|file"):
        audit(directory)



def test_cli_prints_redacted_historical_report(tmp_path, capsys):
    from ingest.legacy_project_projection_cli import main
    directory = make_fixture(tmp_path)
    assert main(["--project-directory", str(directory),
                 "--expected-branch", "branch-synthetic"]) == 0
    output=capsys.readouterr().out
    payload=json.loads(output)
    assert payload["ok"] is True
    assert payload["currentness_verified"] is False
    assert "SYNTHETIC_PERSONAL_DATA_DO_NOT_LEAK" not in output
    assert str(directory) not in output


def test_cli_rejects_bad_branch_without_echoing_file_contents(tmp_path, capsys):
    from ingest.legacy_project_projection_cli import main
    directory=make_fixture(tmp_path)
    assert main(["--project-directory",str(directory),
                 "--expected-branch","wrong"])==2
    output=capsys.readouterr().out
    assert json.loads(output)["ok"] is False
    assert "SYNTHETIC_PERSONAL_DATA_DO_NOT_LEAK" not in output
    assert str(directory) not in output



def test_local_manifest_hashes_cannot_authenticate_coordinated_rewrite(tmp_path):
    """An attacker able to rewrite every local byte can forge a self-consistent set."""
    directory=make_fixture(tmp_path)
    path=directory/FILES[0]
    path.write_bytes(b"# FORGED HISTORICAL CONTENT\nno current control authority\n")
    manifest_path=directory/MANIFEST
    state=json.loads(manifest_path.read_text())
    state["generated_file_hashes"][FILES[0]]=_sha(path.read_bytes())
    state["projection_fingerprint"]=_sha(_canonical({
        key:value for key,value in state.items() if key!="projection_fingerprint"
    }))
    manifest_path.write_text(json.dumps(state,sort_keys=True))
    result=audit(directory)
    assert result["ok"] is True  # local integrity only
    assert result["currentness_verified"] is False
    assert result["authority_effect"] == "NONE"
    assert result["memory_admission_effect"] == "NONE"


def test_reject_missing_manifest_and_unexpected_control_file(tmp_path):
    directory=make_fixture(tmp_path)
    (directory/MANIFEST).unlink()
    with pytest.raises(LegacyProjectionError,match="missing|unexpected"):
        audit(directory)
    directory=make_fixture(tmp_path/"other")
    (directory/"VERA_NATIVE_PROJECT_INSTRUCTIONS.md").write_text("UNTRUSTED_ARCHIVED_CONTROL")
    with pytest.raises(LegacyProjectionError,match="unexpected"):
        audit(directory)
