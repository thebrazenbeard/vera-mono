"""Source-only ancestry claim checks; no weights or model runtime are loaded."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.mini_vera.model_lineage_gate import assess, assess_paths
from tools.mini_vera import model_lineage_gate as gate


def fixture(tmp_path, *, train_repo="owner/base", runtime_repo="owner/base",
            config_path=r"D:\VERA\models\base", manifest_path=None,
            sha_override=None, train_revision="abc123", runtime_revision="abc123"):
    adapter = tmp_path / "adapter_model.safetensors"
    adapter.write_bytes(b"tiny synthetic adapter payload")
    sha = hashlib.sha256(adapter.read_bytes()).hexdigest()
    config = {"base_model_name_or_path": config_path}
    manifest = {
        "schema": "synthetic-training-record", "base": {
            "repository": train_repo,
            "revision": train_revision,
            "path": manifest_path if manifest_path is not None else config_path,
        },
        "adapter": {"adapter_model_sha256": sha_override or sha},
    }
    runtime = {"base": {"hf_repo": runtime_repo, "revision": runtime_revision,
                         "sha256": "0" * 64}, "lora": {"sha256": "1" * 64}}
    config_file = tmp_path / "adapter_config.json"
    manifest_file = tmp_path / "MODEL_MANIFEST.json"
    runtime_file = tmp_path / "qualification.json"
    for file, content in ((config_file, config), (manifest_file, manifest), (runtime_file, runtime)):
        file.write_text(json.dumps(content, sort_keys=True), encoding="utf-8")
    pin = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    return config_file, adapter, manifest_file, runtime_file, pin


def test_metadata_claim_match_is_not_weight_qualification(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path)
    report = assess_paths(config, adapter, manifest, runtime, expected_manifest_sha256=pin)
    assert report["metadata_relation"] == "MATCH"
    assert report["runtime_qualified"] is False
    assert report["authority_effect"] == "NONE"
    assert "metadata" in report["scope"].lower()


def test_different_base_repo_claim_is_mismatch_not_proven_incompatibility(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path, runtime_repo="other/repack")
    report = assess_paths(config, adapter, manifest, runtime, expected_manifest_sha256=pin)
    assert report["metadata_relation"] == "MISMATCH"
    assert report["runtime_qualified"] is False
    assert report["checks"]["repository_claim"] == "MISMATCH"


def test_r13_h07_style_adapter_mismatch_is_unknown(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(
        tmp_path, train_repo="rodrigomt/Qwen3.5-4B-Uncensored-Aggressive",
        runtime_repo="lmstudio-community/Qwen3.5-4B-GGUF",
        manifest_path=r"C:\Vera\models\latest-trained\base",
        sha_override="2" * 64,
    )
    report = assess_paths(config, adapter, manifest, runtime, expected_manifest_sha256=pin)
    assert report["metadata_relation"] == "UNKNOWN"
    assert report["checks"]["adapter_binding"] == "MISMATCH"
    assert report["checks"]["base_path_claim"] == "MISMATCH"


def test_unpinned_self_assertion_or_forged_manifest_never_qualifies(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path)
    unpinned = assess_paths(config, adapter, manifest, runtime)
    assert unpinned["metadata_relation"] == "UNKNOWN"
    assert unpinned["runtime_qualified"] is False
    # A fabricated document can be pinned by its author. That still cannot
    # independently attest training ancestry or authorize model execution.
    fabricated = assess_paths(config, adapter, manifest, runtime, expected_manifest_sha256=pin)
    assert fabricated["metadata_relation"] == "MATCH"
    assert fabricated["runtime_qualified"] is False
    assert fabricated["proves_weight_equivalence"] is False


def test_utf8_bom_real_world_qualification_json_accepted(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path)
    runtime.write_bytes(b"\xef\xbb\xbf" + runtime.read_bytes())
    assert assess_paths(config, adapter, manifest, runtime,
                        expected_manifest_sha256=pin)["metadata_relation"] == "MATCH"


def test_duplicate_json_keys_rejected(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path)
    runtime.write_text('{"base": {}, "base": {}}', encoding="utf-8")
    try:
        assess_paths(config, adapter, manifest, runtime, expected_manifest_sha256=pin)
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("ambiguous metadata must be rejected")


def test_untrusted_adapter_file_symlink_rejected(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path)
    symlink_dir = tmp_path / "link"
    symlink_dir.mkdir()
    (symlink_dir / "adapter_model.safetensors").symlink_to(adapter)
    try:
        assess_paths(config, symlink_dir / "adapter_model.safetensors", manifest,
                     runtime, expected_manifest_sha256=pin)
    except ValueError:
        pass
    else:
        raise AssertionError("symlink must not supply provenance data")


def test_ambiguous_alias_unknown_not_name_based_match(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(
        tmp_path, config_path="Qwen3.5-4B", manifest_path="Qwen3.5-4B")
    report = assess_paths(config, adapter, manifest, runtime, expected_manifest_sha256=pin)
    assert report["metadata_relation"] == "UNKNOWN"
    assert report["checks"]["base_path_claim"] == "UNKNOWN"


def test_manifest_t1_parse_t2_swap_cannot_self_certify_other_bytes(tmp_path, monkeypatch):
    config, adapter, manifest, runtime, original_pin = fixture(tmp_path)
    swapped = json.loads(manifest.read_text(encoding="utf-8"))
    swapped["base"]["repository"] = "other/pinned-base"
    swapped_bytes = json.dumps(swapped, sort_keys=True).encode("utf-8")
    swapped_pin = hashlib.sha256(swapped_bytes).hexdigest()
    original_open = Path.open
    manifest_opens = []

    def adversarial_swap_on_second_open(path, *args, **kwargs):
        if Path(path) == manifest:
            manifest_opens.append(True)
            if len(manifest_opens) == 2:
                # Bypass the instrumentation while replacing bytes at T2.
                with original_open(manifest, "wb") as output:
                    output.write(swapped_bytes)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", adversarial_swap_on_second_open)
    report = gate.assess_paths(config, adapter, manifest, runtime,
                               expected_manifest_sha256=swapped_pin)
    # There is no T2 manifest open to race against the snapshot.
    assert len(manifest_opens) == 1
    assert report["metadata_relation"] == "UNKNOWN"
    assert report["checks"]["manifest_pin"] == "MISMATCH"
    monkeypatch.undo()
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == original_pin


def test_idempotent_and_optimization_independent(tmp_path):
    args = fixture(tmp_path)
    expected = assess_paths(*args[:-1], expected_manifest_sha256=args[-1])
    assert expected == assess_paths(*args[:-1], expected_manifest_sha256=args[-1])
    script = "import json,sys; from pathlib import Path; from tools.mini_vera.model_lineage_gate import assess_paths; print(json.dumps(assess_paths(*(Path(x) for x in sys.argv[1:5]), expected_manifest_sha256=sys.argv[5]),sort_keys=True))"
    for optimize in (False, True):
        command = [sys.executable] + (["-O"] if optimize else []) + ["-c", script]
        proc = subprocess.run(command + [str(x) for x in args], capture_output=True,
                              text=True, check=True, cwd=Path(__file__).resolve().parents[1])
        assert json.loads(proc.stdout) == expected


def test_cli_always_exits_nonzero_if_only_metadata_matches(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(tmp_path)
    command = [sys.executable, "-m", "tools.mini_vera.model_lineage_gate",
               "--adapter-config", str(config), "--adapter-file", str(adapter),
               "--training-manifest", str(manifest), "--runtime-qualification", str(runtime),
               "--expected-training-manifest-sha256", pin]
    proc = subprocess.run(command, capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parents[1])
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["metadata_relation"] == "MATCH"


def test_cli_metadata_mismatch_is_non_authoritative(tmp_path):
    config, adapter, manifest, runtime, pin = fixture(
        tmp_path, runtime_repo="other/base")
    command = [sys.executable, "-m", "tools.mini_vera.model_lineage_gate",
               "--adapter-config", str(config), "--adapter-file", str(adapter),
               "--training-manifest", str(manifest), "--runtime-qualification", str(runtime),
               "--expected-training-manifest-sha256", pin]
    proc = subprocess.run(command, capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parents[1])
    assert proc.returncode == 2
    report = json.loads(proc.stdout)
    assert report["metadata_relation"] == "MISMATCH"
    assert report["runtime_qualified"] is False
    assert report["manifest_pin_authority"] == "CALLER_PROVIDED_DIGEST_NOT_SIGNED"
